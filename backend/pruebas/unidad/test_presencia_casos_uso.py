"""Pruebas de los casos de uso de presencia.

Aquí se defienden tres cosas que no se ven en el color:

1. **No se puede latir por una sesión que no es tuya.** Sin esto, cualquiera con un token válido
   podría mantener en verde la sesión de otra persona —o de otra empresa— mandando latidos ajenos.
2. **El latido no toca `ultimo_uso`.** Es la prueba que protege la regla de expulsión: si el latido
   escribiera ahí, una pestaña olvidada sería la última en expulsarse y se cerraría la que la
   persona tiene delante.
3. **El cuadro lo ve solo el dueño de la plataforma.** Saber quién tiene el panel abierto es
   información sobre personas y sobre la operación —cuánta gente está dentro ahora mismo—, no
   sobre contrataciones. Un administrador de empresa lo veía antes y ya no: que un cliente sepa
   cuándo entra y sale su gente, y menos la de otro cliente, no hace falta para contratar.
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.casos_uso.presencia import (
    NO_ENCONTRADA,
    cerrar_por_ventana,
    cuadro_del_negocio,
    cuadro_serializado,
    latir,
)
from contratacion.aplicacion.puertos.cuentas import SesionGuardada
from contratacion.aplicacion.puertos.presencia import Suscripcion
from contratacion.dominio.errores import SinPermiso
from contratacion.dominio.presencia import (
    AMBITO_TODOS,
    EstadoPresencia,
    EventoPresencia,
    Latido,
    Motivo,
    TipoEvento,
    clave_cuadro,
)
from contratacion.dominio.sesiones import EstadoSesion, MotivoRevocacion, Sesion
from contratacion.dominio.sesiones_vivas import clave_de_sesion, valor_de_sesion
from contratacion.infraestructura.adaptadores.salida.cache.nula import CacheNula

AHORA = datetime(2026, 10, 5, 15, 0, tzinfo=UTC)
TTL = 60

# Plazo de inactividad de las pruebas. Cualquier valor sirve: lo que se comprueba aquí es por dónde
# se pregunta, no cuándo caduca.
INACTIVIDAD = 480 * 60

NEGOCIO = UUID("22222222-2222-2222-2222-222222222222")
USUARIO = UUID("11111111-1111-1111-1111-111111111111")
OTRO_NEGOCIO = UUID("33333333-3333-3333-3333-333333333333")

ADMIN = Actor(usuario_id=USUARIO, negocio_id=NEGOCIO, rol="admin_negocio")
LECTOR = Actor(usuario_id=USUARIO, negocio_id=NEGOCIO, rol="lector")
# El único que puede pedir el cuadro de presencia. Se distingue de `ADMIN` a propósito: la mitad
# administrativa —latir, cerrar la ventana— sigue siendo cosa de cualquiera, y usar el mismo actor
# para las dos cosas dejaría pasar como bueno un cuadro que un cliente no debería poder ver.
PLATAFORMA = Actor(usuario_id=USUARIO, negocio_id=NEGOCIO, rol="super_admin")


# --------------------------------------------------------------------------- #
# Dobles
# --------------------------------------------------------------------------- #


class SesionesFalsas:
    """Registra cada llamada para poder afirmar lo que **no** se hizo.

    Implementa el puerto completo aunque la presencia solo use cuatro operaciones: los métodos que
    no se usan revientan si alguien los llama. Es lo que convierte este doble en una red que detecta
    el día que un caso de uso empiece a tocar la sesión —y sobre todo `rotar`, que es lo que no debe
    ocurrir nunca desde un latido—.
    """

    def __init__(self, *, por_id: dict[UUID, Sesion] | None = None) -> None:
        self.llamadas: list[str] = []
        self._por_id = por_id or {}
        self.a_devolver_activas: list[Sesion] = []
        self.a_devolver_revocadas: list[Sesion] = []
        self.revocadas: list[tuple[UUID, MotivoRevocacion]] = []

    async def por_id(self, *, negocio_id: UUID, sesion_id: UUID) -> SesionGuardada | None:
        self.llamadas.append("por_id")
        sesion = self._por_id.get(sesion_id)
        return None if sesion is None else SesionGuardada(sesion=sesion, refresh_hash="h")

    async def activas_del_negocio(self, *, negocio_id: UUID, momento: datetime) -> list[Sesion]:
        self.llamadas.append("activas_del_negocio")
        return list(self.a_devolver_activas)

    async def revocadas_del_negocio(self, *, negocio_id: UUID, limite: int = 500) -> list[Sesion]:
        self.llamadas.append("revocadas_del_negocio")
        return list(self.a_devolver_revocadas)

    async def revocar(
        self,
        *,
        negocio_id: UUID,
        sesion_id: UUID,
        motivo: MotivoRevocacion,
        momento: datetime,
    ) -> None:
        self.llamadas.append("revocar")
        self.revocadas.append((sesion_id, motivo))

    async def vigentes(
        self, *, negocio_id: UUID, usuario_id: UUID, momento: datetime
    ) -> list[Sesion]:
        self.llamadas.append("vigentes")
        return []

    # Miembros del puerto que la presencia no usa. Se declaran para ser estructuralmente compatibles
    # y para que una llamada inesperada se note en vez de pasar desapercibida.
    async def crear(self, **_: Any) -> UUID:
        raise AssertionError("crear no se debe llamar desde la presencia")

    async def rotar(self, **_: Any) -> None:
        raise AssertionError("rotar no se debe llamar desde la presencia")

    async def revocar_varias(self, **_: Any) -> int:
        raise AssertionError("revocar_varias no se debe llamar desde la presencia")

    async def revocar_todas(self, **_: Any) -> int:
        raise AssertionError("revocar_todas no se debe llamar desde la presencia")


class AccesosFalsos:
    """Listado de cuentas del negocio. Lo demás del puerto no se usa aquí."""

    def __init__(self, usuarios: list[dict[str, Any]]) -> None:
        self._usuarios = usuarios
        # Cuántas veces se fue a buscar el listado. Es lo que permite afirmar que la instantánea
        # guardada ahorró el trabajo, que es el motivo entero de que exista.
        self.consultas = 0

    async def usuarios(self, *, negocio_id: UUID, limite: int = 200) -> list[dict[str, Any]]:
        self.consultas += 1
        return list(self._usuarios)

    async def conceder(self, **_: Any) -> UUID:
        raise AssertionError("conceder no se debe llamar desde la presencia")

    async def retirar(self, **_: Any) -> int:
        raise AssertionError("retirar no se debe llamar desde la presencia")

    async def obtener(self, **_: Any) -> list[Any]:
        raise AssertionError("obtener no se debe llamar desde la presencia")

    async def historial(self, **_: Any) -> list[Any]:
        raise AssertionError("historial no se debe llamar desde la presencia")

    async def usuario(self, **_: Any) -> dict[str, Any] | None:
        raise AssertionError("usuario no se debe llamar desde la presencia")


class RegistroFalso:
    """Señales en memoria, con el alcance declarado a mano."""

    def __init__(self, *, compartida: bool = True) -> None:
        self.senales: dict[UUID, Latido] = {}
        self._compartida = compartida
        self.marcados: list[UUID] = []
        self.olvidados: list[UUID] = []

    @property
    def compartida(self) -> bool:
        return self._compartida

    async def marcar(self, **datos: Any) -> None:
        self.marcados.append(datos["sesion_id"])
        self.senales[datos["sesion_id"]] = Latido(
            usuario_id=datos["usuario_id"],
            sesion_id=datos["sesion_id"],
            momento=datos["momento"],
        )

    async def olvidar(self, *, negocio_id: UUID, sesion_id: UUID) -> None:
        self.olvidados.append(sesion_id)
        self.senales.pop(sesion_id, None)

    async def vivas(self, *, negocio_id: UUID) -> tuple[Latido, ...]:
        return tuple(self.senales.values())

    async def ping(self) -> bool:
        return True

    async def cerrar(self) -> None:
        return None


class BusFalso:
    """Solo publica: lo único que los casos de uso le piden al bus."""

    def __init__(self) -> None:
        self.publicados: list[EventoPresencia] = []

    async def publicar(self, *, negocio_id: UUID, evento: EventoPresencia) -> None:
        self.publicados.append(evento)

    def suscribir(self, *, negocio_id: UUID) -> AbstractAsyncContextManager[Suscripcion]:
        raise AssertionError("el bus falso no se usa para escuchar")

    async def cerrar(self) -> None:
        return None


def _sesion(
    *,
    usuario_id: UUID = USUARIO,
    negocio_id: UUID = NEGOCIO,
    expira_en: datetime | None = None,
    estado: EstadoSesion = EstadoSesion.ACTIVA,
    motivo: MotivoRevocacion | None = None,
    ultimo_uso_en: datetime | None = None,
    sesion_id: UUID | None = None,
) -> Sesion:
    return Sesion(
        id=sesion_id or uuid4(),
        usuario_id=usuario_id,
        negocio_id=negocio_id,
        creada_en=AHORA - timedelta(hours=2),
        ultimo_uso_en=ultimo_uso_en or AHORA - timedelta(minutes=10),
        expira_en=expira_en or AHORA + timedelta(days=7),
        estado=estado,
        motivo_revocacion=motivo,
    )


def _cuenta(usuario_id: UUID, nombre: str, estado: str = "activo") -> dict[str, Any]:
    return {
        "usuario_id": usuario_id,
        "email": f"{nombre}@test.ec",
        "nombre": nombre,
        "rol": "consultor",
        "estado": estado,
        "ultimo_acceso": None,
    }


# --------------------------------------------------------------------------- #
# Latir
# --------------------------------------------------------------------------- #


async def test_latir_anota_la_senal_y_anuncia_la_conexion() -> None:
    sesion = _sesion()
    registro, bus = RegistroFalso(), BusFalso()

    evento = await latir(
        ADMIN,
        sesion_id=sesion.id,
        registro=registro,
        sesiones=SesionesFalsas(por_id={sesion.id: sesion}),
        cache=CacheNula(),
        bus=bus,
        inactividad_seg=INACTIVIDAD,
        momento=AHORA,
        ttl_seg=TTL,
    )

    assert registro.marcados == [sesion.id]
    assert evento.tipo is TipoEvento.CONECTADO
    assert evento.presencia is not None
    assert evento.presencia.estado is EstadoPresencia.VERDE
    assert [publicado.tipo for publicado in bus.publicados] == [TipoEvento.CONECTADO]


async def test_latir_no_toca_el_ultimo_uso_de_la_sesion() -> None:
    """La prueba que protege la expulsión de la tercera sesión.

    Si el latido escribiera `ultimo_uso`, una pestaña abierta y olvidada en un equipo que nadie mira
    sería siempre la más reciente y nunca se expulsaría. Se acabaría cerrando la sesión que la
    persona tiene delante, que es justo lo contrario de lo que quiere la regla.

    El doble revienta si se llama a `rotar` o a `revocar`, así que esta prueba falla ruidosamente si
    alguien «arregla» el latido para que actualice el uso.
    """
    sesion = _sesion()
    sesiones = SesionesFalsas(por_id={sesion.id: sesion})

    await latir(
        ADMIN,
        sesion_id=sesion.id,
        registro=RegistroFalso(),
        sesiones=sesiones,
        cache=CacheNula(),
        bus=BusFalso(),
        inactividad_seg=INACTIVIDAD,
        momento=AHORA,
        ttl_seg=TTL,
    )

    assert "rotar" not in sesiones.llamadas
    assert sesiones.llamadas == ["por_id"], "sin almacén, el latido pregunta a la base"


async def test_latir_por_una_sesion_ajena_se_rechaza() -> None:
    """Ni de otra persona ni de otro negocio: las dos cosas se comprueban con la misma lectura."""
    otra = _sesion(usuario_id=uuid4())
    registro = RegistroFalso()

    with pytest.raises(SinPermiso) as fallo:
        await latir(
            ADMIN,
            sesion_id=otra.id,
            registro=registro,
            sesiones=SesionesFalsas(por_id={otra.id: otra}),
            cache=CacheNula(),
            bus=BusFalso(),
            inactividad_seg=INACTIVIDAD,
            momento=AHORA,
            ttl_seg=TTL,
        )

    assert str(fallo.value) == NO_ENCONTRADA
    assert registro.marcados == [], "no se puede dejar señal de una sesión ajena"


async def test_latir_por_una_sesion_inexistente_se_rechaza_igual() -> None:
    """El mismo mensaje que la ajena, a propósito.

    Distinguir «no existe» de «es de otro» permitiría averiguar qué sesiones existen probando
    identificadores, y eso es información de otra cuenta.
    """
    with pytest.raises(SinPermiso) as fallo:
        await latir(
            ADMIN,
            sesion_id=uuid4(),
            registro=RegistroFalso(),
            sesiones=SesionesFalsas(),
            cache=CacheNula(),
            bus=BusFalso(),
            inactividad_seg=INACTIVIDAD,
            momento=AHORA,
            ttl_seg=TTL,
        )

    assert str(fallo.value) == NO_ENCONTRADA


# --------------------------------------------------------------------------- #
# Cerrar por cierre de ventana
# --------------------------------------------------------------------------- #


async def test_cerrar_ventana_revoca_con_su_motivo_y_retira_la_senal() -> None:
    """`cierre_ventana` y no `logout`: irse no es despedirse, y el registro debe distinguirlo."""
    sesion = _sesion()
    registro, bus, sesiones = (
        RegistroFalso(),
        BusFalso(),
        SesionesFalsas(por_id={sesion.id: sesion}),
    )

    evento = await cerrar_por_ventana(
        ADMIN,
        sesion_id=sesion.id,
        registro=registro,
        sesiones=sesiones,
        bus=bus,
        momento=AHORA,
    )

    assert sesiones.revocadas == [(sesion.id, MotivoRevocacion.CIERRE_VENTANA)]
    assert registro.olvidados == [sesion.id]
    assert evento.tipo is TipoEvento.DESCONECTADO
    assert evento.presencia is not None
    assert evento.presencia.motivo is Motivo.SESION_CERRADA


async def test_cerrar_ventana_sobre_una_sesion_ajena_se_rechaza() -> None:
    agena = _sesion(usuario_id=uuid4())
    sesiones = SesionesFalsas(por_id={agena.id: agena})

    with pytest.raises(SinPermiso):
        await cerrar_por_ventana(
            ADMIN,
            sesion_id=agena.id,
            registro=RegistroFalso(),
            sesiones=sesiones,
            bus=BusFalso(),
            momento=AHORA,
        )

    assert sesiones.revocadas == [], "nadie cierra la sesión de otra persona"


# --------------------------------------------------------------------------- #
# El cuadro del negocio
# --------------------------------------------------------------------------- #


async def test_el_cuadro_combina_cuentas_sesiones_y_senales() -> None:
    conectado = _sesion()
    ausente = _sesion(usuario_id=uuid4())
    registro = RegistroFalso()
    registro.senales[conectado.id] = Latido(
        usuario_id=USUARIO, sesion_id=conectado.id, momento=AHORA
    )

    sesiones = SesionesFalsas()
    sesiones.a_devolver_activas = [conectado, ausente]

    cuadro = await cuadro_del_negocio(
        PLATAFORMA,
        accesos=AccesosFalsos([_cuenta(USUARIO, "Ana"), _cuenta(ausente.usuario_id, "Luis")]),
        sesiones=sesiones,
        registro=registro,
        momento=AHORA,
        ttl_seg=TTL,
    )

    assert cuadro.total == 2
    assert cuadro.conectados == 1
    por_usuario = {presencia.usuario_id: presencia for presencia in cuadro.presencias}
    assert por_usuario[USUARIO].estado is EstadoPresencia.VERDE
    assert por_usuario[ausente.usuario_id].estado is EstadoPresencia.ROJO
    assert por_usuario[ausente.usuario_id].motivo is Motivo.SIN_SENAL


async def test_los_conectados_van_primero_y_el_orden_es_estable() -> None:
    """Un listado que se reordena solo cada quince segundos no se puede leer."""
    conectado = _sesion()
    registro = RegistroFalso()
    registro.senales[conectado.id] = Latido(
        usuario_id=USUARIO, sesion_id=conectado.id, momento=AHORA
    )
    sesiones = SesionesFalsas()
    sesiones.a_devolver_activas = [conectado]

    cuadro = await cuadro_del_negocio(
        PLATAFORMA,
        accesos=AccesosFalsos([_cuenta(USUARIO, "Ana"), _cuenta(uuid4(), "Luis")]),
        sesiones=sesiones,
        registro=registro,
        momento=AHORA,
        ttl_seg=TTL,
    )

    assert cuadro.presencias[0].estado is EstadoPresencia.VERDE
    assert cuadro.presencias[-1].estado is EstadoPresencia.ROJO


async def test_un_lector_no_puede_ver_el_cuadro() -> None:
    """Ver quién está conectado es información sobre personas, no sobre contrataciones.

    Se niega con un error y no con una lista vacía: el panel tiene que poder decir «no puedes ver
    esto», y no inventarse que no hay nadie dentro.
    """
    with pytest.raises(SinPermiso):
        await cuadro_del_negocio(
            LECTOR,
            accesos=AccesosFalsos([_cuenta(USUARIO, "Ana"), _cuenta(uuid4(), "Luis")]),
            sesiones=SesionesFalsas(),
            registro=RegistroFalso(),
            momento=AHORA,
            ttl_seg=TTL,
        )


async def test_un_administrador_de_empresa_tampoco_ve_el_cuadro() -> None:
    """El caso que cambió: quien administra una empresa lo veía y ya no lo ve.

    Es la prueba que distingue «un administrador» de «el dueño de la plataforma». Si alguien
    volviera a relajar el guardián a `es_administrativo`, esta prueba falla y la anterior no.
    """
    with pytest.raises(SinPermiso):
        await cuadro_del_negocio(
            ADMIN,
            accesos=AccesosFalsos([_cuenta(USUARIO, "Ana"), _cuenta(uuid4(), "Luis")]),
            sesiones=SesionesFalsas(),
            registro=RegistroFalso(),
            momento=AHORA,
            ttl_seg=TTL,
        )


async def test_el_dueno_de_la_plataforma_ve_a_todo_el_negocio() -> None:
    otro = uuid4()
    cuadro = await cuadro_del_negocio(
        PLATAFORMA,
        accesos=AccesosFalsos([_cuenta(USUARIO, "Ana"), _cuenta(otro, "Luis")]),
        sesiones=SesionesFalsas(),
        registro=RegistroFalso(),
        momento=AHORA,
        ttl_seg=TTL,
    )

    assert len(cuadro.presencias) == 2


async def test_consultar_otro_negocio_exige_ser_el_dueno_de_la_plataforma() -> None:
    """El negocio no lo elige el cliente: sin permiso, ni se intenta."""
    with pytest.raises(SinPermiso):
        await cuadro_del_negocio(
            ADMIN,
            accesos=AccesosFalsos([]),
            sesiones=SesionesFalsas(),
            registro=RegistroFalso(),
            momento=AHORA,
            ttl_seg=TTL,
            negocio_solicitado=OTRO_NEGOCIO,
        )


async def test_el_dueno_de_la_plataforma_consulta_su_propio_negocio_explicitamente() -> None:
    cuadro = await cuadro_del_negocio(
        PLATAFORMA,
        accesos=AccesosFalsos([_cuenta(USUARIO, "Ana")]),
        sesiones=SesionesFalsas(),
        registro=RegistroFalso(),
        momento=AHORA,
        ttl_seg=TTL,
        negocio_solicitado=NEGOCIO,
    )
    assert cuadro.total == 1


async def test_el_cuadro_declara_su_alcance() -> None:
    """Con varias réplicas, un alcance de proceso da respuestas incompletas sin fallar.

    Publicarlo es lo único que permite advertirlo en la interfaz en lugar de mostrar un dato falso
    con toda tranquilidad.
    """
    comun = await cuadro_del_negocio(
        PLATAFORMA,
        accesos=AccesosFalsos([]),
        sesiones=SesionesFalsas(),
        registro=RegistroFalso(compartida=True),
        momento=AHORA,
        ttl_seg=TTL,
    )
    local = await cuadro_del_negocio(
        PLATAFORMA,
        accesos=AccesosFalsos([]),
        sesiones=SesionesFalsas(),
        registro=RegistroFalso(compartida=False),
        momento=AHORA,
        ttl_seg=TTL,
    )

    assert comun.como_diccionario()["alcance"] == "compartido"
    assert local.como_diccionario()["alcance"] == "proceso"


async def test_el_motivo_de_un_rojo_llega_al_listado() -> None:
    """La revocación se lee de la base y se traduce: quien mira el cuadro sabe por qué no está."""
    expulsado = uuid4()
    pasada = _sesion(
        usuario_id=expulsado,
        estado=EstadoSesion.REVOCADA,
        motivo=MotivoRevocacion.EVICCION,
    )
    sesiones = SesionesFalsas()
    sesiones.a_devolver_revocadas = [pasada]

    cuadro = await cuadro_del_negocio(
        PLATAFORMA,
        accesos=AccesosFalsos([_cuenta(expulsado, "Luis")]),
        sesiones=sesiones,
        registro=RegistroFalso(),
        momento=AHORA,
        ttl_seg=TTL,
    )

    unica = cuadro.presencias[0]
    assert unica.motivo is Motivo.EVICCION
    assert "otro dispositivo" in unica.descripcion


async def test_una_cuenta_deshabilitada_no_aparece_en_verde_aunque_tenga_senal() -> None:
    sesion = _sesion()
    registro = RegistroFalso()
    registro.senales[sesion.id] = Latido(usuario_id=USUARIO, sesion_id=sesion.id, momento=AHORA)
    sesiones = SesionesFalsas()
    sesiones.a_devolver_activas = [sesion]

    cuadro = await cuadro_del_negocio(
        PLATAFORMA,
        accesos=AccesosFalsos([_cuenta(USUARIO, "Ana", estado="inactivo")]),
        sesiones=sesiones,
        registro=registro,
        momento=AHORA,
        ttl_seg=TTL,
    )

    assert cuadro.presencias[0].motivo is Motivo.CUENTA_INACTIVA
    assert cuadro.conectados == 0


# --------------------------------------------------------------------------- #
# El latido y el almacén de sesiones vivas
# --------------------------------------------------------------------------- #

# El latido es el camino más transitado del sistema: uno cada treinta segundos por persona
# conectada. Antes costaba una consulta a la base cada vez, y en una instalación con miles de
# paneles eso es el grueso del tráfico. Ahora lo resuelve el almacén, y estas pruebas fijan las tres
# respuestas posibles, porque confundirlas tiene los dos finales que hay que evitar: echar a todo el
# mundo cuando el almacén se apaga, o dejar latiendo una sesión que ya se cerró.


class CacheFalso:
    """Almacén en memoria, con la posibilidad de decir que no responde.

    Se implementa el contrato completo aunque el latido solo use una parte: un doble al que le falte
    un método no falla al escribirlo, falla el día que alguien usa el que falta.
    """

    def __init__(self, *, habilitada: bool = True, falla: bool = False) -> None:
        self._habilitada = habilitada
        self._falla = falla
        self.contenido: dict[str, str] = {}
        self.lecturas = 0
        self.escrituras = 0

    @property
    def habilitada(self) -> bool:
        return self._habilitada

    async def obtener(self, clave: str) -> str | None:
        self.lecturas += 1
        if self._falla:
            raise RuntimeError("el almacén no responde")
        return self.contenido.get(clave)

    async def obtener_renovando(self, clave: str, ttl_seg: int) -> str | None:
        return await self.obtener(clave)

    async def guardar(self, clave: str, valor: str, ttl_seg: int) -> None:
        self.escrituras += 1
        self.contenido[clave] = valor

    async def eliminar(self, clave: str) -> None:
        self.contenido.pop(clave, None)

    async def incrementar(self, clave: str) -> int:
        raise AssertionError("el latido no debe incrementar contadores")

    async def ping(self) -> bool:
        return not self._falla

    async def cerrar(self) -> None:
        return None


def _cache_con(sesion: Sesion, usuario_id: UUID = USUARIO) -> CacheFalso:
    cache = CacheFalso()
    cache.contenido[clave_de_sesion(sesion.id)] = valor_de_sesion(usuario_id)
    return cache


async def test_con_almacen_el_latido_no_toca_la_base() -> None:
    """Es el objetivo de todo esto: una señal de vida sin ninguna consulta.

    El doble de sesiones revienta si le llaman, así que esta prueba falla ruidosamente si alguien
    vuelve a meter una lectura de la base en el camino del latido.
    """
    sesion = _sesion()
    sesiones = SesionesFalsas()

    evento = await latir(
        ADMIN,
        sesion_id=sesion.id,
        registro=RegistroFalso(),
        sesiones=sesiones,
        cache=_cache_con(sesion),
        bus=BusFalso(),
        inactividad_seg=INACTIVIDAD,
        momento=AHORA,
        ttl_seg=TTL,
    )

    assert sesiones.llamadas == [], "el latido no debe preguntar a la base si el almacén contesta"
    assert evento.presencia is not None
    assert evento.presencia.estado is EstadoPresencia.VERDE


async def test_una_sesion_que_no_consta_en_el_almacen_no_late() -> None:
    """Con el almacén funcionando, la ausencia **es** una respuesta: la sesión se cerró.

    Es la prueba que impide que una sesión cerrada por inactividad siga latiendo para siempre, que
    es exactamente lo que pasaría si la ausencia se tratara como «no se sabe».
    """
    sesion = _sesion()
    registro = RegistroFalso()
    sesiones = SesionesFalsas(por_id={sesion.id: sesion})

    with pytest.raises(SinPermiso):
        await latir(
            ADMIN,
            sesion_id=sesion.id,
            registro=registro,
            sesiones=sesiones,
            cache=CacheFalso(),
            bus=BusFalso(),
            inactividad_seg=INACTIVIDAD,
            momento=AHORA,
            ttl_seg=TTL,
        )

    assert registro.marcados == [], "no se deja señal de una sesión cerrada"
    assert sesiones.llamadas == [], "y no hace falta preguntar a la base para saberlo"


async def test_un_almacen_roto_no_impide_latir() -> None:
    """Un problema del almacén no puede dejar sin presencia a toda la instalación.

    Se degrada a la base, que es lo que se hacía antes de que existiera el almacén. La diferencia
    con la prueba anterior es todo: aquí la ausencia de la clave **no significa nada**, porque nadie
    pudo contestar.
    """
    sesion = _sesion()
    registro = RegistroFalso()
    sesiones = SesionesFalsas(por_id={sesion.id: sesion})

    evento = await latir(
        ADMIN,
        sesion_id=sesion.id,
        registro=registro,
        sesiones=sesiones,
        cache=CacheFalso(falla=True),
        bus=BusFalso(),
        inactividad_seg=INACTIVIDAD,
        momento=AHORA,
        ttl_seg=TTL,
    )

    assert sesiones.llamadas == ["por_id"], "con el almacén caído se pregunta a la base"
    assert evento.presencia is not None
    assert evento.presencia.estado is EstadoPresencia.VERDE
    assert registro.marcados == [sesion.id]


async def test_una_sesion_de_otro_usuario_en_el_almacen_se_rechaza() -> None:
    """El valor de la clave lleva el dueño justamente para poder comprobarlo."""
    sesion = _sesion()

    with pytest.raises(SinPermiso):
        await latir(
            ADMIN,
            sesion_id=sesion.id,
            registro=RegistroFalso(),
            sesiones=SesionesFalsas(),
            cache=_cache_con(sesion, usuario_id=uuid4()),
            bus=BusFalso(),
            inactividad_seg=INACTIVIDAD,
            momento=AHORA,
            ttl_seg=TTL,
        )


# --------------------------------------------------------------------------- #
# La instantánea guardada del cuadro
# --------------------------------------------------------------------------- #

# El cuadro de presencia es, con diferencia, lo que más consulta la base: se recalcula cada quince
# segundos por cada panel abierto. Guardarlo unos segundos es el arreglo de capacidad más rentable
# que tiene el sistema, y estas pruebas defienden las dos cosas que pueden salir mal al hacerlo:
# servir a alguien un listado que no le corresponde, y servir una entrada que ya no es válida.


def _cuadro(actor: Actor, cache: Any, accesos: AccesosFalsos) -> Any:
    return cuadro_serializado(
        actor,
        accesos=accesos,
        sesiones=SesionesFalsas(),
        registro=RegistroFalso(),
        cache=cache,
        momento=AHORA,
        ttl_seg=TTL,
    )


async def test_la_segunda_consulta_se_sirve_de_la_instantanea() -> None:
    """Dos paneles releyendo a la vez cuestan un solo cálculo. Es el objetivo de todo esto."""
    cache = CacheFalso()
    accesos = AccesosFalsos([_cuenta(USUARIO, "Ana"), _cuenta(uuid4(), "Luis")])

    primero = await _cuadro(PLATAFORMA, cache, accesos)
    segundo = await _cuadro(PLATAFORMA, cache, accesos)

    assert accesos.consultas == 1, "la segunda relectura no debe tocar la base"
    assert primero == segundo
    assert cache.escrituras == 1


async def test_lo_guardado_no_le_sirve_a_quien_no_es_de_la_plataforma() -> None:
    """El cuadro de la plataforma está en el almacén y aun así no se sirve a nadie más.

    Antes esta prueba medía dos alcances distintos del mismo negocio; hoy el corte es anterior, y
    eso la hace más fuerte: el lector no recibe el listado de sus compañeros **ni aunque esté ya
    calculado**, y ni siquiera se llega a leerlo del almacén. Si alguien bajara el guardián a
    `es_administrativo`, esta prueba volvería a fallar.
    """
    cache = CacheFalso()
    accesos = AccesosFalsos([_cuenta(USUARIO, "Ana"), _cuenta(uuid4(), "Luis")])

    del_dueno = await _cuadro(PLATAFORMA, cache, accesos)
    lecturas_antes = cache.lecturas
    with pytest.raises(SinPermiso):
        await _cuadro(LECTOR, cache, accesos)

    assert len(del_dueno["usuarios"]) == 2
    assert accesos.consultas == 1, "el rechazado no puede llegar ni a consultar"
    assert cache.lecturas == lecturas_antes, "el rechazo es anterior a mirar la instantánea"


async def test_la_clave_del_cuadro_separa_a_cada_persona() -> None:
    """El alcance sigue dentro de la clave aunque hoy solo haya un alcance posible.

    El filtro por alcance se conservó como red de seguridad para el día que el cuadro vuelva a
    abrirse a más gente. Lo que no puede quedar sin comprobar es la pieza que lo hace seguro: si la
    clave fuese solo el negocio, lo guardado para quien ve a todos se serviría a quien solo debe
    verse a sí mismo. Se prueba donde vive —en la función de la clave— y no a través de un caso de
    uso que hoy no puede producir esa situación.
    """
    propia = clave_cuadro(NEGOCIO, str(USUARIO))
    ajena = clave_cuadro(NEGOCIO, str(uuid4()))

    assert propia != ajena
    assert propia != clave_cuadro(NEGOCIO, AMBITO_TODOS)
    assert clave_cuadro(NEGOCIO, AMBITO_TODOS) == clave_cuadro(NEGOCIO, AMBITO_TODOS)


async def test_el_cuadro_guardado_conserva_lo_que_el_panel_necesita() -> None:
    """Ida y vuelta por el almacén: el panel recibe exactamente las mismas claves.

    Un campo que se pierda al guardar no daría un error, daría un panel incompleto: el color sin el
    motivo, o el resumen sin el total. Por eso se comparan las dos respuestas enteras.
    """
    cache = CacheFalso()
    accesos = AccesosFalsos([_cuenta(USUARIO, "Ana")])
    sesion = _sesion(usuario_id=USUARIO)
    sesiones = SesionesFalsas()
    sesiones.a_devolver_activas = [sesion]
    senales = RegistroFalso()
    await senales.marcar(
        usuario_id=USUARIO, sesion_id=sesion.id, negocio_id=NEGOCIO, momento=AHORA, ttl_seg=TTL
    )

    def _una_vez() -> Any:
        return cuadro_serializado(
            PLATAFORMA,
            accesos=accesos,
            sesiones=sesiones,
            registro=senales,
            cache=cache,
            momento=AHORA,
            ttl_seg=TTL,
        )

    sin_guardar = await _una_vez()
    guardado = await _una_vez()

    assert guardado == sin_guardar
    assert guardado["conectados"] == 1
    assert guardado["total"] == 1
    assert guardado["alcance"] == "compartido"


async def test_un_cuadro_de_otro_negocio_no_se_guarda() -> None:
    """Con un negocio ajeno el resultado depende de quién pregunta, así que no puede compartirse.

    El aislamiento de la base decide qué ve cada administrador sobre una empresa que no es la suya.
    Una entrada común haría que el segundo en preguntar leyera lo que se calculó para el primero.
    """
    cache = CacheFalso()
    accesos = AccesosFalsos([_cuenta(USUARIO, "Ana")])
    de_plataforma = Actor(usuario_id=USUARIO, negocio_id=OTRO_NEGOCIO, rol="super_admin")

    def _ajeno() -> Any:
        return cuadro_serializado(
            de_plataforma,
            accesos=accesos,
            sesiones=SesionesFalsas(),
            registro=RegistroFalso(),
            cache=cache,
            momento=AHORA,
            ttl_seg=TTL,
            negocio_solicitado=NEGOCIO,
        )

    await _ajeno()
    await _ajeno()

    assert accesos.consultas == 2, "el cuadro de un negocio ajeno se calcula siempre"
    assert cache.escrituras == 0


async def test_sin_almacen_se_calcula_cada_vez() -> None:
    """Sin Redis el sistema funciona igual, solo cuesta más. Es la degradación que ya se aceptó."""
    accesos = AccesosFalsos([_cuenta(USUARIO, "Ana")])

    await _cuadro(PLATAFORMA, CacheNula(), accesos)
    await _cuadro(PLATAFORMA, CacheNula(), accesos)

    assert accesos.consultas == 2


async def test_un_almacen_roto_no_deja_sin_cuadro_al_panel() -> None:
    """Un problema del almacén no puede vaciar la pantalla de quién está conectado."""
    accesos = AccesosFalsos([_cuenta(USUARIO, "Ana")])
    cuadro = await _cuadro(PLATAFORMA, CacheFalso(falla=True), accesos)

    assert accesos.consultas == 1
    assert len(cuadro["usuarios"]) == 1


async def test_una_entrada_ilegible_se_descarta_en_vez_de_servirse() -> None:
    """Un valor corrupto no puede llegar al panel disfrazado de cuadro.

    Se prefiere gastar el cálculo a devolver algo que no es la respuesta: el panel pintaría una
    lista sin saber que no lo es, y el fallo aparecería lejos de su causa.
    """
    cache = CacheFalso()
    cache.contenido[clave_cuadro(NEGOCIO, AMBITO_TODOS)] = "esto no es un cuadro"
    accesos = AccesosFalsos([_cuenta(USUARIO, "Ana")])

    cuadro = await _cuadro(PLATAFORMA, cache, accesos)

    assert accesos.consultas == 1
    assert len(cuadro["usuarios"]) == 1


async def test_una_lista_json_tampoco_cuela_como_cuadro() -> None:
    """JSON válido pero de la forma equivocada. Se descarta por la misma razón."""
    cache = CacheFalso()
    cache.contenido[clave_cuadro(NEGOCIO, AMBITO_TODOS)] = "[1, 2, 3]"
    accesos = AccesosFalsos([_cuenta(USUARIO, "Ana")])

    cuadro = await _cuadro(PLATAFORMA, cache, accesos)

    assert accesos.consultas == 1
    assert "usuarios" in cuadro
