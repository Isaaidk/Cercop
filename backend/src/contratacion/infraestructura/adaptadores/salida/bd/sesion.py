"""Adaptador de salida: conexión a PostgreSQL (SQLAlchemy asíncrono).

El motor y la fábrica de sesiones se crean de forma perezosa: importar este módulo no abre
conexiones, lo que permite que las pruebas de unidad se ejecuten sin base de datos.

Acepta directamente la URI que entregan los proveedores gestionados (Supabase, Neon, RDS):
`normalizar_url_bd` añade el controlador asíncrono y activa el cifrado TLS cuando el host no es
local.

Fase 1 añadirá el contexto de negocio por transacción (`app.negocio_id`) que alimenta las políticas
de Row Level Security.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from contratacion.infraestructura.adaptadores.salida.bd.motivos import motivo_legible
from contratacion.infraestructura.config.ajustes import obtener_ajustes

registro = logging.getLogger(__name__)

# Nombres que solo existen dentro de una red privada. La plataforma que los sirve no publica
# certificados, así que pedir cifrado ahí no protege nada y **rompe la conexión**: el intento de TLS
# llega a un servidor que no lo habla y contesta «rejected SSL upgrade».
#
# Esto costó un despliegue entero en Railway: la base estaba viva, el nombre se resolvía y el API
# fallaba con un error de cifrado que parecía un problema de certificados. La regla de «TLS
# obligatorio» se escribió para Supabase, donde la base está al otro lado de internet; dentro de una
# plataforma, la base y el API hablan por la red interna y no salen de ahí.
HOSTS_LOCALES = frozenset({"localhost", "127.0.0.1", "::1", "host.docker.internal"})
SUFIJOS_PRIVADOS = (".internal", ".svc.cluster.local")
CONTROLADORES_ACEPTADOS = frozenset(
    {"postgres", "postgresql", "postgresql+psycopg2", "postgresql+asyncpg"}
)

_motor: AsyncEngine | None = None
_fabrica_sesiones: async_sessionmaker[AsyncSession] | None = None


def _es_host_privado(host: str | None) -> bool:
    """`True` si el servidor vive dentro de una red privada y por tanto **no** habla TLS.

    Tres casos, y los tres han aparecido ya en este proyecto: los nombres locales conocidos
    (`localhost`, `127.0.0.1`, `host.docker.internal`), un nombre **sin punto** (`bd`, `cache`,
    que es como se llama el servicio en el `docker-compose` de `deploy/`) y un nombre con **sufijo
    privado** (`postgres.railway.internal` en Railway, `algo.svc.cluster.local` en Kubernetes).

    Una dirección IPv6 literal no entra por ninguna de las tres puertas: si no está en la lista de
    nombres conocidos se trata como remota, que es el lado seguro por el que equivocarse —de pedir
    cifrado de más se sale con `?ssl=disable`, y de pedir de menos, no tan fácil—.
    """
    if host is None or host in HOSTS_LOCALES:
        return True
    if ":" in host:
        return False
    if "." not in host:
        return True
    return any(host.endswith(sufijo) for sufijo in SUFIJOS_PRIVADOS)


def normalizar_url_bd(destino: str) -> URL:
    """Adapta la URI de PostgreSQL al controlador asíncrono.

    - Acepta `postgresql://` y `postgres://` (lo que copia el panel de Supabase) y añade `asyncpg`.
    - Añade `ssl=require` en hosts **públicos** cuando el usuario no indica cifrado, porque los
      proveedores gestionados lo exigen y, sin él, el error resultante es difícil de interpretar.
      **No** lo añade en una red privada —`bd`, `postgres.railway.internal`, `localhost`—, donde el
      servidor no tiene certificado y el intento de cifrado solo consigue tumbar la conexión.
      Para forzarlo o desactivarlo, `?ssl=require` y `?ssl=disable`, que siempre mandan.
    """
    url = make_url(destino)

    if url.drivername not in CONTROLADORES_ACEPTADOS:
        raise ValueError(
            f"Controlador no soportado en DATABASE_URL: {url.drivername!r}. "
            "Se espera PostgreSQL (por ejemplo `postgresql://` o `postgresql+asyncpg://`)."
        )

    if url.drivername != "postgresql+asyncpg":
        url = url.set(drivername="postgresql+asyncpg")

    if "ssl" not in url.query and not _es_host_privado(url.host):
        url = url.update_query_dict({"ssl": "require"})

    return url


def obtener_motor() -> AsyncEngine:
    """Devuelve el motor compartido, creándolo en la primera llamada.

    El motor se ajusta a la latencia de la base, porque la base es **remota** y cada ida y vuelta
    cuesta unos 95 ms medidos. Con esa cifra, cualquier opción que añada un viaje por operación se
    paga en cada pantalla, y el panel hace varias consultas por carga.

    `pool_pre_ping` comprueba que la conexión sigue viva **en cada uso**, y ese viaje extra se notó:
    medido en esta base, una consulta trivial tarda 569 ms con la comprobación y 287 ms sin ella.
    Como el plan de ejecución de las consultas del panel ronda los 0,5 ms, el tiempo se va entero en
    la ida y vuelta, así que duplicarla no es un detalle.

    Se sustituye por `pool_recycle`, que cierra y reabre la conexión cada pocos minutos y cubre el
    caso contra el que `pool_pre_ping` protege —una conexión que el servidor cerró por inactividad—
    sin pagar nada por operación. El reciclado tiene que ser **más corto** que la inactividad máxima
    del servidor: si fuera más largo, la conexión moriría antes de reciclarse y volvería a hacer
    falta la comprobación previa.

    El resto de las dimensiones del pool (tamaño, desbordamiento y espera máxima) se leen de
    `Ajustes` y no se escriben aquí: son decisiones de despliegue, no de código. Con varias
    réplicas, el techo contra PostgreSQL es la suma de todos los procesos, así que un número fijo
    en este módulo sería idéntico en cada réplica y nadie podría ajustarlo desde el entorno.
    """
    global _motor
    if _motor is None:
        ajustes = obtener_ajustes()
        destino = normalizar_url_bd(ajustes.database_url)
        # A dónde se conecta y si cifra, en el registro del arranque y **sin la credencial**. Es la
        # línea que faltaba cuando el despliegue decía «Postgres no responde» y nada más: con el
        # servidor, la base y el cifrado a la vista, se diagnostica en dos segundos lo que si no
        # hay que deducir de una traza de veinte pantallas.
        registro.info(
            "Base de datos: %s:%s/%s · cifrado=%s",
            destino.host,
            destino.port or 5432,
            destino.database,
            destino.query.get("ssl", "no"),
        )
        _motor = create_async_engine(
            destino,
            pool_pre_ping=False,
            pool_size=ajustes.bd_pool_size,
            max_overflow=ajustes.bd_max_overflow,
            pool_timeout=ajustes.bd_pool_timeout_seg,
            pool_recycle=ajustes.bd_pool_recycle_seg,
            # Tope para **abrir** una conexión. El de asyncpg son 60 s: con el servidor caído o
            # inalcanzable, cada petición que necesitara una conexión nueva se quedaba un minuto
            # colgada, y quinientas así agotan el proceso aunque el resto del código esté bien.
            connect_args={
                "timeout": ajustes.bd_conexion_timeout_seg,
                "server_settings": parametros_de_sesion(
                    statement_timeout_ms=ajustes.bd_statement_timeout_ms,
                    idle_tx_timeout_ms=ajustes.bd_idle_tx_timeout_ms,
                    nombre=ajustes.bd_nombre_aplicacion,
                ),
            },
        )
    return _motor


def parametros_de_sesion(
    *, statement_timeout_ms: int, idle_tx_timeout_ms: int, nombre: str = "cercoapp-api"
) -> dict[str, str]:
    """Parámetros de PostgreSQL que viajan al abrir cada conexión, sin un viaje extra.

    Van en el arranque de la conexión (`server_settings` de asyncpg) y no en un `SET` por petición:
    así no cuestan nada por operación y no dependen de que nadie se acuerde de ponerlos. Un cero
    deja el valor del servidor, que es lo que pide el worker. `application_name` identifica las
    conexiones de cada proceso (API o worker) en `pg_stat_activity`, que es lo primero que se mira
    cuando la base se llena.
    """
    parametros = {"application_name": nombre[:60] or "cercoapp"}
    if statement_timeout_ms > 0:
        parametros["statement_timeout"] = str(statement_timeout_ms)
    if idle_tx_timeout_ms > 0:
        parametros["idle_in_transaction_session_timeout"] = str(idle_tx_timeout_ms)
    return parametros


def obtener_fabrica_sesiones() -> async_sessionmaker[AsyncSession]:
    """Fábrica de sesiones asíncronas reutilizable."""
    global _fabrica_sesiones
    if _fabrica_sesiones is None:
        _fabrica_sesiones = async_sessionmaker(
            bind=obtener_motor(),
            expire_on_commit=False,
        )
    return _fabrica_sesiones


async def estado_bd() -> tuple[bool, str]:
    """`True` si Postgres responde a una consulta trivial, y **por qué no** cuando no responde.

    Devuelve el motivo y no solo el booleano porque un despliegue que falla tiene que poder
    diagnosticarse desde el registro. Sin esto, el arranque decía `Postgres no responde` y nada más:
    en un despliegue en la nube, con el nombre del servicio mal puesto, eso obliga a probar a ciegas
    una lista de sospechas y no hay forma de saber cuál era. El motivo sale de `motivo_legible`, que
    lo escribe este repositorio —nunca el mensaje del controlador, que puede llevar la cadena de
    conexión y con ella la contraseña—.
    """
    try:
        async with obtener_motor().connect() as conexion:
            await conexion.execute(text("SELECT 1"))
    except Exception as error:  # noqa: BLE001 - cualquier fallo de conexión significa "no disponible"
        motivo = motivo_legible(error)
        registro.warning("Postgres no responde: %s", motivo)
        return False, motivo
    return True, ""


async def calentar_pool() -> int:
    """Abre de antemano las conexiones del pool. Devuelve cuántas quedaron abiertas.

    El pool crea las conexiones bajo demanda. Con la primera tanda de cientos de personas —justo
    después de un reinicio, o de la hora punta de la mañana— cada petición espera a que se abra una
    conexión nueva, y las que pasan del tiempo del pool fallan. Con las conexiones ya abiertas, esa
    primera tanda cuesta lo mismo que cualquier otra. Es de mejor esfuerzo: si falla, el pool sigue
    funcionando y se abre bajo demanda como siempre.
    """
    ajustes = obtener_ajustes()
    motor = obtener_motor()

    async def una() -> None:
        async with motor.connect() as conexion:
            await conexion.execute(text("SELECT 1"))
            # Se retiene un instante para que las demás tomen otra conexión y no la misma.
            await asyncio.sleep(0.1)

    resultados = await asyncio.gather(
        *(una() for _ in range(max(1, ajustes.bd_pool_size))), return_exceptions=True
    )
    return sum(1 for resultado in resultados if not isinstance(resultado, BaseException))


async def verificar_bd() -> bool:
    """`True` si Postgres responde a una consulta trivial."""
    responde, _ = await estado_bd()
    return responde


async def rol_de_bd() -> tuple[str, bool]:
    """Usuario con el que se conecta la aplicación y si **salta el RLS** (superusuario/BYPASSRLS).

    Con un rol que lo salta, las políticas de aislamiento entre empresas no se aplican (docs/38,
    S-01). Se registra al arrancar para comprobarlo en el despliegue sin entrar a la base.
    """
    async with obtener_motor().connect() as conexion:
        fila = (
            await conexion.execute(
                text(
                    "SELECT current_user::text, rolsuper OR rolbypassrls "
                    "FROM pg_roles WHERE rolname = current_user"
                )
            )
        ).one()
    return str(fila[0]), bool(fila[1])


async def cerrar_bd() -> None:
    """Libera el pool de conexiones y **siempre** olvida la referencia.

    El cierre es *de mejor esfuerzo*, por el mismo motivo que en el caché: si el bucle de eventos
    que creó el motor ya no existe, sus conexiones murieron con él y liberarlas es una operación
    sobre un objeto muerto. Ocurre en las pruebas, donde cada caso puede tener su propio bucle, y al
    apagar de forma abrupta.

    Soltar las referencias va fuera del `try` a propósito: si se quedaran puestas, la siguiente
    llamada reutilizaría un motor de un bucle muerto y el fallo aparecería más lejos y peor.
    """
    global _motor, _fabrica_sesiones
    if _motor is not None:
        try:
            await _motor.dispose()
        except Exception:  # noqa: BLE001 - apagar no puede fallar
            registro.warning("No se pudo liberar el pool al apagar", exc_info=False)
    _motor = None
    _fabrica_sesiones = None
