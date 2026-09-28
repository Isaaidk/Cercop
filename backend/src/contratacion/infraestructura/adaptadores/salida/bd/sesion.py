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

import logging

from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from contratacion.infraestructura.config.ajustes import obtener_ajustes

registro = logging.getLogger(__name__)

HOSTS_LOCALES = frozenset({"localhost", "127.0.0.1", "::1", "host.docker.internal"})
CONTROLADORES_ACEPTADOS = frozenset(
    {"postgres", "postgresql", "postgresql+psycopg2", "postgresql+asyncpg"}
)

# Minutos tras los cuales una conexión del pool se cierra y se reabre. Ver `obtener_motor`.
RECICLADO_CONEXION_SEG = 180

_motor: AsyncEngine | None = None
_fabrica_sesiones: async_sessionmaker[AsyncSession] | None = None


def _es_host_local(host: str | None) -> bool:
    return host is None or host in HOSTS_LOCALES


def normalizar_url_bd(destino: str) -> URL:
    """Adapta la URI de PostgreSQL al controlador asíncrono.

    - Acepta `postgresql://` y `postgres://` (lo que copia el panel de Supabase) y añade `asyncpg`.
    - Añade `ssl=require` en hosts remotos cuando el usuario no indica cifrado, porque los
      proveedores gestionados lo exigen y, sin él, el error resultante es difícil de interpretar.
      Para desactivarlo, hay que indicar `?ssl=disable` de forma explícita.
    """
    url = make_url(destino)

    if url.drivername not in CONTROLADORES_ACEPTADOS:
        raise ValueError(
            f"Controlador no soportado en DATABASE_URL: {url.drivername!r}. "
            "Se espera PostgreSQL (por ejemplo `postgresql://` o `postgresql+asyncpg://`)."
        )

    if url.drivername != "postgresql+asyncpg":
        url = url.set(drivername="postgresql+asyncpg")

    if "ssl" not in url.query and not _es_host_local(url.host):
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
    """
    global _motor
    if _motor is None:
        ajustes = obtener_ajustes()
        _motor = create_async_engine(
            normalizar_url_bd(ajustes.database_url),
            pool_pre_ping=False,
            pool_recycle=RECICLADO_CONEXION_SEG,
        )
    return _motor


def obtener_fabrica_sesiones() -> async_sessionmaker[AsyncSession]:
    """Fábrica de sesiones asíncronas reutilizable."""
    global _fabrica_sesiones
    if _fabrica_sesiones is None:
        _fabrica_sesiones = async_sessionmaker(
            bind=obtener_motor(),
            expire_on_commit=False,
        )
    return _fabrica_sesiones


async def verificar_bd() -> bool:
    """`True` si Postgres responde a una consulta trivial."""
    try:
        async with obtener_motor().connect() as conexion:
            await conexion.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - cualquier fallo de conexión significa "no disponible"
        registro.warning("Postgres no responde", exc_info=False)
        return False
    return True


async def cerrar_bd() -> None:
    """Libera el pool de conexiones al apagar el proceso."""
    global _motor, _fabrica_sesiones
    if _motor is not None:
        await _motor.dispose()
    _motor = None
    _fabrica_sesiones = None
