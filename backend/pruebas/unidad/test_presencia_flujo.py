"""Pruebas del flujo en vivo: que termine, y que suelte el canal.

Esta es la prueba que faltaba. Un canal de eventos está pensado para **no terminar**, así que el
único final posible es que el cliente se vaya; si nadie comprueba eso, cada pestaña cerrada deja una
tarea y una conexión de suscripción colgadas en el servidor. No falla nada, no aparece ningún error:
el proceso simplemente se queda sin recursos y lo que se observa es que «el programa se queda
parado». Es un fallo que solo se ve en producción y solo después de un rato.

Se comprueban las tres salidas del generador:

1. el cliente se desconecta,
2. el flujo falla a mitad,
3. y en las dos anteriores el canal queda cerrado, que es lo que evita la fuga.

No hace falta servidor ni base de datos: se llama al endpoint directamente y se consume el iterador
que devuelve, que es exactamente lo que haría Starlette.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from starlette.requests import Request

from contratacion.aplicacion.actor import Actor
from contratacion.dominio.presencia import (
    EstadoPresencia,
    EventoPresencia,
    Latido,
    Motivo,
    Presencia,
    evento_conectado,
)
from contratacion.infraestructura.adaptadores.entrada.http.routers.presencia import eventos
from contratacion.infraestructura.config.ajustes import obtener_ajustes

AHORA = datetime(2026, 10, 5, 15, 0, tzinfo=UTC)
NEGOCIO = UUID("22222222-2222-2222-2222-222222222222")
USUARIO = UUID("11111111-1111-1111-1111-111111111111")
ADMIN = Actor(usuario_id=USUARIO, negocio_id=NEGOCIO, rol="admin_negocio")


class PeticionQueSeVa(Request):
    """Petición que se declara desconectada a partir de la enésima comprobación.

    Se hereda de `Request` en lugar de imitar su forma para no acabar probando un objeto que no es
    el que el endpoint recibe. Y se sobrescribe `is_disconnected` porque la implementación real
    consulta el canal del servidor con un truco de cancelación: reproducirlo en una prueba sería
    comprobar el comportamiento del framework, no el nuestro.
    """

    def __init__(self, desconectada_a_partir_de: int = 0) -> None:
        super().__init__({"type": "http", "method": "GET", "path": "/", "headers": []})
        self._comprobaciones = 0
        self._desde = desconectada_a_partir_de

    async def is_disconnected(self) -> bool:
        self._comprobaciones += 1
        return self._comprobaciones > self._desde


class SuscripcionInmediata:
    """Canal de mentira que no espera: devuelve al instante lo que tenga o nada.

    Esperar de verdad al intervalo de la instantánea haría que cada prueba tardase quince segundos,
    y una prueba lenta acaba desactivada. Lo que se comprueba aquí es el bucle del generador, no
    cuánto dura su espera.
    """

    def __init__(self, avisos: list[EventoPresencia] | None = None) -> None:
        self.avisos = list(avisos or [])
        self.cerrada = False

    async def siguiente(self, espera_seg: float) -> EventoPresencia | None:
        return self.avisos.pop(0) if self.avisos else None

    async def cerrar(self) -> None:
        self.cerrada = True


class BusQueCuenta:
    """Bus de mentira que además recuerda si alguien cerró el canal."""

    def __init__(self, suscripcion: SuscripcionInmediata | None = None) -> None:
        self.suscripcion = suscripcion or SuscripcionInmediata()
        self.abiertas = 0

    async def publicar(self, *, negocio_id: UUID, evento: EventoPresencia) -> None:
        return None

    @asynccontextmanager
    async def suscribir(self, *, negocio_id: UUID) -> AsyncIterator[SuscripcionInmediata]:
        self.abiertas += 1
        try:
            yield self.suscripcion
        finally:
            # Igual que el adaptador real: el cierre va en `finally` para que una desconexión a
            # medias pase por aquí de todas formas.
            await self.suscripcion.cerrar()

    async def cerrar(self) -> None:
        return None


class CuentasDeMentira:
    """Cuentas vacías: aquí no se está probando la composición del cuadro."""

    def __init__(self) -> None:
        self.llamadas = 0
        self.fallar_en = 0

    async def usuarios(self, *, negocio_id: UUID, limite: int = 200) -> list[dict[str, Any]]:
        self.llamadas += 1
        if self.fallar_en and self.llamadas >= self.fallar_en:
            raise RuntimeError("la base dejó de responder")
        return []

    async def conceder(self, **_: Any) -> UUID:
        raise AssertionError("no se debe conceder desde la presencia")

    async def retirar(self, **_: Any) -> int:
        raise AssertionError("no se debe retirar desde la presencia")

    async def obtener(self, **_: Any) -> list[Any]:
        raise AssertionError("no se debe consultar desde la presencia")

    async def historial(self, **_: Any) -> list[Any]:
        raise AssertionError("no se debe consultar desde la presencia")

    async def usuario(self, **_: Any) -> dict[str, Any] | None:
        raise AssertionError("no se debe consultar desde la presencia")


class SesionesDeMentira:
    """Sesiones vacías: el cuadro queda sin nadie y el flujo sigue igual."""

    async def activas_del_negocio(self, *, negocio_id: UUID, momento: datetime) -> list[Any]:
        return []

    async def revocadas_del_negocio(self, *, negocio_id: UUID, limite: int = 500) -> list[Any]:
        return []

    async def vigentes(self, **_: Any) -> list[Any]:
        return []

    async def por_id(self, **_: Any) -> Any:
        raise AssertionError("no se debe consultar una sesión desde el flujo")

    async def crear(self, **_: Any) -> UUID:
        raise AssertionError("no se debe crear desde el flujo")

    async def rotar(self, **_: Any) -> None:
        raise AssertionError("no se debe rotar desde el flujo")

    async def revocar(self, **_: Any) -> None:
        raise AssertionError("no se debe revocar desde el flujo")

    async def revocar_varias(self, **_: Any) -> int:
        raise AssertionError("no se debe revocar desde el flujo")

    async def revocar_todas(self, **_: Any) -> int:
        raise AssertionError("no se debe revocar desde el flujo")


class RegistroDeMentira:
    def __init__(self) -> None:
        self.consultas = 0

    @property
    def compartida(self) -> bool:
        return True

    async def vivas(self, *, negocio_id: UUID) -> tuple[Latido, ...]:
        self.consultas += 1
        return ()

    async def marcar(self, **_: Any) -> None:
        raise AssertionError("el flujo no marca señales")

    async def olvidar(self, **_: Any) -> None:
        raise AssertionError("el flujo no olvida señales")

    async def ping(self) -> bool:
        return True

    async def cerrar(self) -> None:
        return None


async def _abrir_flujo(
    *,
    peticion: Request,
    bus: BusQueCuenta,
    accesos: CuentasDeMentira | None = None,
) -> Any:
    """Llama al endpoint sin pasar por el enrutador, como haría Starlette."""
    return await eventos(
        peticion=peticion,
        actor=ADMIN,
        ajustes=obtener_ajustes(),
        accesos=accesos or CuentasDeMentira(),
        sesiones=SesionesDeMentira(),
        presencia=RegistroDeMentira(),
        bus=bus,
    )


async def _consumir(respuesta: Any) -> list[str]:
    return [trozo async for trozo in respuesta.body_iterator]


async def test_el_flujo_termina_cuando_el_cliente_se_desconecta() -> None:
    """La prueba que impide que el proceso se quede sin recursos.

    Sin la comprobación de desconexión, este `async for` **no terminaría nunca**: el generador se
    quedaría esperando avisos para siempre, la respuesta nunca se cerraría y la suscripción seguiría
    viva. Cada pestaña cerrada sumaría una más, en silencio.
    """
    bus = BusQueCuenta()
    respuesta = await _abrir_flujo(peticion=PeticionQueSeVa(desconectada_a_partir_de=1), bus=bus)

    trozos = await _consumir(respuesta)

    # El estado inicial, y de ahí no pasa: la comprobación siguiente ya ve que se fue.
    assert len(trozos) == 1
    assert trozos[0].startswith("event: instantanea")
    assert bus.abiertas == 1


async def test_al_desconectarse_el_cliente_se_suelta_el_canal() -> None:
    """El cierre del canal es lo que evita la fuga de conexiones, así que se comprueba aparte.

    Que el bucle termine y que el recurso se libere son dos cosas distintas: se puede salir del
    bucle dejando la suscripción abierta, y entonces el problema sigue ahí aunque la prueba anterior
    pase.
    """
    suscripcion = SuscripcionInmediata()
    bus = BusQueCuenta(suscripcion)
    respuesta = await _abrir_flujo(peticion=PeticionQueSeVa(desconectada_a_partir_de=1), bus=bus)

    await _consumir(respuesta)

    assert suscripcion.cerrada is True


async def test_un_cliente_que_se_va_antes_de_la_primera_lectura_no_consulta_nada() -> None:
    """Si ya no hay nadie mirando, no tiene sentido ir a la base a componer un cuadro."""
    accesos = CuentasDeMentira()
    bus = BusQueCuenta()
    respuesta = await _abrir_flujo(
        peticion=PeticionQueSeVa(desconectada_a_partir_de=0), bus=bus, accesos=accesos
    )

    trozos = await _consumir(respuesta)

    assert trozos == []
    assert accesos.llamadas == 0
    assert bus.suscripcion.cerrada is True


async def test_los_avisos_llegan_al_flujo_entre_instantaneas() -> None:
    """El aviso es lo que hace que el color cambie al instante, sin esperar a la relectura."""
    aviso = evento_conectado(
        NEGOCIO,
        Presencia(
            usuario_id=USUARIO,
            estado=EstadoPresencia.VERDE,
            motivo=Motivo.CONECTADO,
            ultimo_latido_en=AHORA,
            dispositivos=1,
        ),
        AHORA,
    )
    bus = BusQueCuenta(SuscripcionInmediata(avisos=[aviso]))
    respuesta = await _abrir_flujo(peticion=PeticionQueSeVa(desconectada_a_partir_de=2), bus=bus)

    trozos = await _consumir(respuesta)

    assert any(trozo.startswith("event: conectado") for trozo in trozos)
    assert trozos[0].startswith("event: instantanea"), "primero el estado, y luego los cambios"


async def test_si_el_flujo_falla_a_mitad_el_canal_se_suelta_igual() -> None:
    """Un error a mitad —la base dejando de responder, por ejemplo— no puede dejar el canal abierto.

    Es el caso que más se olvida: el camino feliz se prueba siempre y es justo en el que no se
    producen las fugas. La suscripción tiene que liberarse también cuando el generador revienta.
    """
    suscripcion = SuscripcionInmediata()
    bus = BusQueCuenta(suscripcion)
    respuesta = await _abrir_flujo(
        peticion=PeticionQueSeVa(desconectada_a_partir_de=99),
        bus=bus,
        accesos=CuentasDeMentiraConFallo(),
    )

    with suppress(RuntimeError):
        await _consumir(respuesta)

    assert suscripcion.cerrada is True


class CuentasDeMentiraConFallo(CuentasDeMentira):
    """Falla a partir de la segunda consulta: la primera pinta el panel, la segunda revienta."""

    def __init__(self) -> None:
        super().__init__()
        self.fallar_en = 2
