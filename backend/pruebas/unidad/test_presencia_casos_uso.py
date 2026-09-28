"""Pruebas de los casos de uso de presencia.

Aquí se defienden tres cosas que no se ven en el color:

1. **No se puede latir por una sesión que no es tuya.** Sin esto, cualquiera con un token válido
   podría mantener en verde la sesión de otra persona —o de otra empresa— mandando latidos ajenos.
2. **El latido no toca `ultimo_uso`.** Es la prueba que protege la regla de expulsión: si el latido
   escribiera ahí, una pestaña olvidada sería la última en expulsarse y se cerraría la que la
   persona tiene delante.
3. **Un rol de lectura no ve la presencia de los demás.** Que un compañero esté conectado es
   información sobre una persona, y el rol existe para consultar contrataciones.
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
    latir,
)
from contratacion.aplicacion.puertos.cuentas import SesionGuardada
from contratacion.aplicacion.puertos.presencia import Suscripcion
from contratacion.dominio.errores import SinPermiso
from contratacion.dominio.presencia import (
    EstadoPresencia,
    EventoPresencia,
    Latido,
    Motivo,
    TipoEvento,
)
from contratacion.dominio.sesiones import EstadoSesion, MotivoRevocacion, Sesion

AHORA = datetime(2026, 10, 5, 15, 0, tzinfo=UTC)
TTL = 60

NEGOCIO = UUID("22222222-2222-2222-2222-222222222222")
USUARIO = UUID("11111111-1111-1111-1111-111111111111")
OTRO_NEGOCIO = UUID("33333333-3333-3333-3333-333333333333")

ADMIN = Actor(usuario_id=USUARIO, negocio_id=NEGOCIO, rol="admin_negocio")
LECTOR = Actor(usuario_id=USUARIO, negocio_id=NEGOCIO, rol="lector")


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

    async def usuarios(self, *, negocio_id: UUID, limite: int = 200) -> list[dict[str, Any]]:
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
        bus=bus,
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
        bus=BusFalso(),
        momento=AHORA,
        ttl_seg=TTL,
    )

    assert "rotar" not in sesiones.llamadas
    assert sesiones.llamadas == ["por_id"], "el latido solo debe leer la sesión"


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
            bus=BusFalso(),
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
            bus=BusFalso(),
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
        ADMIN,
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
        ADMIN,
        accesos=AccesosFalsos([_cuenta(USUARIO, "Ana"), _cuenta(uuid4(), "Luis")]),
        sesiones=sesiones,
        registro=registro,
        momento=AHORA,
        ttl_seg=TTL,
    )

    assert cuadro.presencias[0].estado is EstadoPresencia.VERDE
    assert cuadro.presencias[-1].estado is EstadoPresencia.ROJO


async def test_un_lector_solo_se_ve_a_si_mismo() -> None:
    """Ver quién está conectado es información sobre personas, no sobre contrataciones."""
    otro = uuid4()
    cuadro = await cuadro_del_negocio(
        LECTOR,
        accesos=AccesosFalsos([_cuenta(USUARIO, "Ana"), _cuenta(otro, "Luis")]),
        sesiones=SesionesFalsas(),
        registro=RegistroFalso(),
        momento=AHORA,
        ttl_seg=TTL,
    )

    assert [presencia.usuario_id for presencia in cuadro.presencias] == [USUARIO]


async def test_un_administrador_si_ve_a_todo_el_negocio() -> None:
    otro = uuid4()
    cuadro = await cuadro_del_negocio(
        ADMIN,
        accesos=AccesosFalsos([_cuenta(USUARIO, "Ana"), _cuenta(otro, "Luis")]),
        sesiones=SesionesFalsas(),
        registro=RegistroFalso(),
        momento=AHORA,
        ttl_seg=TTL,
    )

    assert len(cuadro.presencias) == 2


async def test_consultar_otro_negocio_exige_ser_administrador() -> None:
    """El negocio no lo elige el cliente: sin permiso, ni se intenta."""
    with pytest.raises(SinPermiso):
        await cuadro_del_negocio(
            LECTOR,
            accesos=AccesosFalsos([]),
            sesiones=SesionesFalsas(),
            registro=RegistroFalso(),
            momento=AHORA,
            ttl_seg=TTL,
            negocio_solicitado=OTRO_NEGOCIO,
        )


async def test_un_administrador_puede_consultar_su_propio_negocio_explicitamente() -> None:
    cuadro = await cuadro_del_negocio(
        ADMIN,
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
        ADMIN,
        accesos=AccesosFalsos([]),
        sesiones=SesionesFalsas(),
        registro=RegistroFalso(compartida=True),
        momento=AHORA,
        ttl_seg=TTL,
    )
    local = await cuadro_del_negocio(
        ADMIN,
        accesos=AccesosFalsos([]),
        sesiones=SesionesFalsas(),
        registro=RegistroFalso(compartida=False),
        momento=AHORA,
        ttl_seg=TTL,
    )

    assert comun.como_diccionario()["alcance"] == "compartido"
    assert local.como_diccionario()["alcance"] == "proceso"


async def test_el_motivo_de_un_rojo_llega_al_listado() -> None:
    """La revocación se lee de la base y se traduce: el administrador sabe por qué no está."""
    expulsado = uuid4()
    pasada = _sesion(
        usuario_id=expulsado,
        estado=EstadoSesion.REVOCADA,
        motivo=MotivoRevocacion.EVICCION,
    )
    sesiones = SesionesFalsas()
    sesiones.a_devolver_revocadas = [pasada]

    cuadro = await cuadro_del_negocio(
        ADMIN,
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
        ADMIN,
        accesos=AccesosFalsos([_cuenta(USUARIO, "Ana", estado="inactivo")]),
        sesiones=sesiones,
        registro=registro,
        momento=AHORA,
        ttl_seg=TTL,
    )

    assert cuadro.presencias[0].motivo is Motivo.CUENTA_INACTIVA
    assert cuadro.conectados == 0
