"""Pruebas del bus de avisos sobre Redis.

Lo que se comprueba aquí es una sola propiedad, pero es la que decide si el sistema aguanta:
**abrir paneles no abre conexiones**. La versión anterior creaba un cliente Redis dentro de
`suscribir()`, es decir una conexión por pestaña, y un plan gestionado pequeño permite del orden de
treinta: el sistema dejaba de aceptar paneles hacia el vigésimo, y lo hacía sin error, solo dejando
de funcionar.

Se sustituye el cliente de Redis por un doble para poder contar las conexiones reales que pediría
el adaptador, y para poder entregar mensajes a mano en el momento exacto. El formato del mensaje es
el que produce Pub/Sub con suscripción por patrón (`pmessage`), que es distinto del de una
suscripción por canal: si se confundieran, el reparto descartaría todo en silencio.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, ClassVar
from uuid import UUID

import pytest

from contratacion.dominio.presencia import (
    PATRON_CANALES,
    EstadoPresencia,
    EventoPresencia,
    Motivo,
    Presencia,
    canal_de_negocio,
    evento_conectado,
    negocio_de_canal,
)
from contratacion.infraestructura.adaptadores.salida.presencia import redis as modulo_redis
from contratacion.infraestructura.adaptadores.salida.presencia.memoria import serializar_evento
from contratacion.infraestructura.adaptadores.salida.presencia.redis import BusRedis

AHORA = datetime(2026, 10, 5, 15, 0, tzinfo=UTC)

NEGOCIO = UUID("22222222-2222-2222-2222-222222222222")
OTRO_NEGOCIO = UUID("33333333-3333-3333-3333-333333333333")
USUARIO = UUID("11111111-1111-1111-1111-111111111111")

# Centinela que se mete en la cola para simular que el enlace se cae mientras el lector espera un
# mensaje. Sin esto habría que esperar al siguiente aviso real para que se enterara del corte.
_FALLO = object()


class PubSubFalso:
    """Pub/Sub de mentira: recuerda el patrón al que se suscribió y sirve lo que le den."""

    def __init__(self) -> None:
        self.patron: str | None = None
        self._cola: asyncio.Queue[Any] = asyncio.Queue()

    async def psubscribe(self, patron: str) -> None:
        self.patron = patron

    async def listen(self) -> AsyncIterator[dict[str, Any]]:
        while True:
            mensaje = await self._cola.get()
            if mensaje is _FALLO:
                raise RuntimeError("el enlace se cayó")
            yield mensaje

    async def entregar(self, mensaje: dict[str, Any]) -> None:
        await self._cola.put(mensaje)

    async def caerse(self) -> None:
        await self._cola.put(_FALLO)


class RedisFalso:
    """Cliente de mentira. Registra cada ejemplar para poder contar conexiones."""

    creados: ClassVar[list[RedisFalso]] = []

    def __init__(self, url: str) -> None:
        self.url = url
        self.pubsubs: list[PubSubFalso] = []
        self.cerrado = False
        RedisFalso.creados.append(self)

    @classmethod
    def from_url(cls, url: str, **_: Any) -> RedisFalso:
        return cls(url)

    def pubsub(self, **_: Any) -> PubSubFalso:
        nuevo = PubSubFalso()
        self.pubsubs.append(nuevo)
        return nuevo

    async def publish(self, canal: str, datos: str) -> None:
        raise AssertionError("estas pruebas no publican por el cliente real")

    async def aclose(self) -> None:
        self.cerrado = True


async def _esperar_pubsub(indice: int = 1) -> PubSubFalso:
    """Espera a que el lector compartido exista y se haya suscrito.

    El lector arranca en una tarea, así que hay que cederle el turno. El paso es un retardo real, y
    no `sleep(0)`: tras una caída el bucle espera antes de reintentar, y ceder el turno sin dejar
    pasar el tiempo no lo despertaría nunca. Se acota el número de vueltas para que un fallo se vea
    como una prueba que falla, y no como una suite colgada.
    """
    for _ in range(200):
        if len(RedisFalso.creados) > indice:
            cliente = RedisFalso.creados[indice]
            if cliente.pubsubs and cliente.pubsubs[0].patron is not None:
                return cliente.pubsubs[0]
        await asyncio.sleep(0.01)
    raise AssertionError("el lector compartido no llegó a suscribirse")


def _presencia(usuario_id: UUID = USUARIO) -> Presencia:
    return Presencia(
        usuario_id=usuario_id,
        estado=EstadoPresencia.VERDE,
        motivo=Motivo.CONECTADO,
        ultimo_latido_en=AHORA,
        dispositivos=1,
    )


def _mensaje(negocio_id: UUID, evento: EventoPresencia | None = None) -> dict[str, Any]:
    aviso = evento if evento is not None else evento_conectado(negocio_id, _presencia(), AHORA)
    return {
        "type": "pmessage",
        "pattern": PATRON_CANALES,
        "channel": canal_de_negocio(negocio_id),
        "data": serializar_evento(aviso),
    }


@pytest.fixture(autouse=True)
def _cliente_falso(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sustituye el cliente de Redis por el doble y vacía el registro de conexiones."""
    RedisFalso.creados.clear()
    monkeypatch.setattr(modulo_redis, "Redis", RedisFalso)


@pytest.fixture
async def bus(_cliente_falso: None) -> AsyncIterator[BusRedis]:
    """Bus real con cliente de mentira, cerrado al terminar cada prueba."""
    instrumento = BusRedis("redis://prueba")
    try:
        yield instrumento
    finally:
        await instrumento.cerrar()


# --------------------------------------------------------------------------- #
# La vuelta del nombre del canal
# --------------------------------------------------------------------------- #


def test_el_negocio_sobrevive_a_la_ida_y_vuelta_por_el_canal() -> None:
    assert negocio_de_canal(canal_de_negocio(NEGOCIO)) == NEGOCIO


def test_un_nombre_ajeno_no_devuelve_negocio() -> None:
    """Lo que llega por un canal puede ser cualquier cosa, empezando por una clave de señal."""
    assert negocio_de_canal("presencia:22222222-2222-2222-2222-222222222222:sesion") is None


def test_un_canal_con_identificador_ilegible_no_devuelve_negocio() -> None:
    """Un mensaje raro se descarta en lugar de cortar el reparto de todos los demás."""
    assert negocio_de_canal("presencia:canal:no-es-un-uuid") is None


def test_el_patron_abarca_los_canales_de_cualquier_negocio() -> None:
    assert canal_de_negocio(NEGOCIO).startswith(PATRON_CANALES.removesuffix("*"))


# --------------------------------------------------------------------------- #
# Una sola conexión por proceso
# --------------------------------------------------------------------------- #


async def test_muchos_paneles_comparten_una_sola_conexion(bus: BusRedis) -> None:
    """Es el objetivo del cambio: el número de paneles deja de multiplicar las conexiones."""
    async with (
        bus.suscribir(negocio_id=NEGOCIO),
        bus.suscribir(negocio_id=NEGOCIO),
        bus.suscribir(negocio_id=OTRO_NEGOCIO),
        bus.suscribir(negocio_id=OTRO_NEGOCIO),
        bus.suscribir(negocio_id=OTRO_NEGOCIO),
    ):
        await _esperar_pubsub()

    # Una conexión para el publicador (la del constructor) y **una** para el lector compartido,
    # frente a las seis que harían falta con una suscripción por panel.
    assert len(RedisFalso.creados) == 2


async def test_se_escucha_por_patron_y_no_canal_a_canal(bus: BusRedis) -> None:
    """Suscribirse y desuscribirse según quién mira exigiría escribir en la conexión que se lee."""
    async with bus.suscribir(negocio_id=NEGOCIO):
        pubsub = await _esperar_pubsub()

    assert pubsub.patron == PATRON_CANALES


async def test_quedarse_sin_paneles_no_cierra_la_suscripcion(bus: BusRedis) -> None:
    """Los paneles son un ir y venir continuo: cerrar y reabrir costaría más que dejarlo abierto."""
    async with bus.suscribir(negocio_id=NEGOCIO):
        await _esperar_pubsub()

    assert len(RedisFalso.creados) == 2
    assert not RedisFalso.creados[1].cerrado


async def test_un_panel_nuevo_reutiliza_el_lector(bus: BusRedis) -> None:
    async with bus.suscribir(negocio_id=NEGOCIO):
        await _esperar_pubsub()

    async with bus.suscribir(negocio_id=OTRO_NEGOCIO) as canal:
        assert await canal.siguiente(0.01) is None

    assert len(RedisFalso.creados) == 2


async def test_cerrar_libera_la_conexion_del_proceso(bus: BusRedis) -> None:
    async with bus.suscribir(negocio_id=NEGOCIO):
        await _esperar_pubsub()

    await bus.cerrar()

    assert RedisFalso.creados[1].cerrado
    assert RedisFalso.creados[0].cerrado


# --------------------------------------------------------------------------- #
# Reparto
# --------------------------------------------------------------------------- #


async def test_un_aviso_llega_a_todos_los_paneles_del_negocio(bus: BusRedis) -> None:
    async with (
        bus.suscribir(negocio_id=NEGOCIO) as uno,
        bus.suscribir(negocio_id=NEGOCIO) as otro,
    ):
        pubsub = await _esperar_pubsub()
        await pubsub.entregar(_mensaje(NEGOCIO))

        assert await uno.siguiente(1) is not None
        assert await otro.siguiente(1) is not None


async def test_un_aviso_no_llega_al_canal_de_otro_negocio(bus: BusRedis) -> None:
    """El aislamiento se resuelve al repartir: un negocio no ve lo que pasa en otro."""
    async with (
        bus.suscribir(negocio_id=NEGOCIO) as mio,
        bus.suscribir(negocio_id=OTRO_NEGOCIO) as ajeno,
    ):
        pubsub = await _esperar_pubsub()
        await pubsub.entregar(_mensaje(OTRO_NEGOCIO))

        assert await ajeno.siguiente(1) is not None
        assert await mio.siguiente(0.05) is None


async def test_un_aviso_sin_paneles_se_descarta_sin_fallar(bus: BusRedis) -> None:
    """Escuchar por patrón trae avisos de empresas que este proceso no atiende."""
    async with bus.suscribir(negocio_id=NEGOCIO) as canal:
        pubsub = await _esperar_pubsub()
        await pubsub.entregar(_mensaje(OTRO_NEGOCIO))

        assert await canal.siguiente(0.05) is None


async def test_un_mensaje_que_no_es_un_aviso_no_corta_el_reparto(bus: BusRedis) -> None:
    """`listen()` entrega también las confirmaciones de suscripción; descartarlas no basta:
    tienen que no romper nada para que el aviso que viene detrás llegue."""
    async with bus.suscribir(negocio_id=NEGOCIO) as canal:
        pubsub = await _esperar_pubsub()
        await pubsub.entregar({"type": "psubscribe", "channel": canal_de_negocio(NEGOCIO)})
        await pubsub.entregar(_mensaje(NEGOCIO))

        assert await canal.siguiente(1) is not None


async def test_un_canal_cerrado_deja_de_entregar(bus: BusRedis) -> None:
    async with bus.suscribir(negocio_id=NEGOCIO) as canal:
        await _esperar_pubsub()
        await canal.cerrar()

        assert await canal.siguiente(1) is None


# --------------------------------------------------------------------------- #
# Reconexión
# --------------------------------------------------------------------------- #


async def test_la_suscripcion_se_reconecta_tras_un_fallo(
    bus: BusRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sin reconectar, una caída dejaría los canales abiertos y mudos, sin un solo error."""
    monkeypatch.setattr(modulo_redis, "RECONEXION_INICIAL_SEG", 0.01)
    monkeypatch.setattr(modulo_redis, "RECONEXION_MAXIMA_SEG", 0.05)

    async with bus.suscribir(negocio_id=NEGOCIO) as canal:
        primero = await _esperar_pubsub()
        await primero.caerse()

        segundo = await _esperar_pubsub(indice=2)

        assert segundo is not primero
        assert segundo.patron == PATRON_CANALES

        await segundo.entregar(_mensaje(NEGOCIO))
        assert await canal.siguiente(1) is not None
