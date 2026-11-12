"""Cortacircuitos, compartimentos y degradación: que un servicio caído no tumbe el API.

Las pruebas usan un reloj de mentira para no esperar enfriamientos reales, y transportes HTTP de
mentira para simular el SRI caído sin tocar la red. Lo que se comprueba, en el orden en que importa:

1. El circuito se abre tras los fallos, y abierto **no llama** al servicio: responde al instante.
2. Lo que no es un fallo del servicio (un `NoEncontrado`, un 404) no abre nada.
3. Pasado el enfriamiento deja pasar una sola llamada de prueba, y su resultado decide.
4. El compartimento rechaza en lugar de hacer cola sin fin.
5. Con Redis caído, el caché y la sesión viva degradan a «sin caché» y `/listo` sigue en 200.
"""

from __future__ import annotations

import asyncio
import time
from uuid import uuid4

import httpx
import pytest
from fastapi import status
from fastapi.testclient import TestClient

from contratacion.aplicacion.generaciones import leer_generacion
from contratacion.aplicacion.sesiones_vivas import VidaDeSesion, seguir
from contratacion.dominio.errores import EstadoInvalido, NoEncontrado, ServicioNoDisponible
from contratacion.infraestructura.adaptadores.entrada.http.routers import salud
from contratacion.infraestructura.adaptadores.salida.cache.redis import CacheRedis
from contratacion.infraestructura.adaptadores.salida.resiliencia import (
    Cortacircuitos,
    EstadoCircuito,
    FalloDelServicio,
    circuito,
    es_fallo_de_servicio,
    estado_circuitos,
)
from contratacion.infraestructura.adaptadores.salida.sri import ConsultaSri, circuito_sri
from contratacion.infraestructura.app import CODIGOS_POR_ERROR, crear_app


class Reloj:
    def __init__(self) -> None:
        self.ahora = 1000.0

    def __call__(self) -> float:
        return self.ahora


def _circuito(reloj: Reloj, **opciones: object) -> Cortacircuitos:
    configuracion: dict[str, object] = {
        "mensaje": "El servicio no responde.",
        "umbral_fallos": 3,
        "enfriamiento_seg": 30.0,
    }
    configuracion.update(opciones)
    return Cortacircuitos("prueba", reloj=reloj, **configuracion)  # type: ignore[arg-type]


async def _fallar(c: Cortacircuitos) -> None:
    with pytest.raises(httpx.ConnectError):
        async with c.proteger():
            raise httpx.ConnectError("sin conexión")


# --------------------------------------------------------------------------- #
# Estados
# --------------------------------------------------------------------------- #


async def test_se_abre_tras_el_umbral_y_abierto_no_llama() -> None:
    reloj = Reloj()
    c = _circuito(reloj)
    for _ in range(3):
        await _fallar(c)
    assert c.estado is EstadoCircuito.ABIERTO

    llamado = False
    with pytest.raises(ServicioNoDisponible, match="no responde"):
        async with c.proteger():
            llamado = True
    assert not llamado
    assert c.rechazadas == 1
    assert c.aperturas == 1


async def test_un_exito_reinicia_la_cuenta_de_fallos() -> None:
    c = _circuito(Reloj())
    await _fallar(c)
    await _fallar(c)
    async with c.proteger():
        pass
    await _fallar(c)
    assert c.estado is EstadoCircuito.CERRADO


async def test_un_error_de_negocio_no_cuenta_como_caida() -> None:
    """Diez RUC inexistentes seguidos no pueden cortar el SRI a todo el mundo."""
    c = _circuito(Reloj())
    for _ in range(10):
        with pytest.raises(NoEncontrado):
            async with c.proteger():
                raise NoEncontrado("No existe.")
    assert c.estado is EstadoCircuito.CERRADO


async def test_tras_el_enfriamiento_pasa_una_sola_llamada_de_prueba() -> None:
    reloj = Reloj()
    c = _circuito(reloj)
    for _ in range(3):
        await _fallar(c)
    reloj.ahora += 31
    assert c.estado is EstadoCircuito.SEMIABIERTO

    dentro = asyncio.Event()
    soltar = asyncio.Event()

    async def sonda() -> None:
        async with c.proteger():
            dentro.set()
            await soltar.wait()

    tarea = asyncio.create_task(sonda())
    await dentro.wait()
    # Mientras la prueba está en curso, nadie más pasa.
    with pytest.raises(ServicioNoDisponible):
        async with c.proteger():
            pass
    soltar.set()
    await tarea
    assert c.resumen()["estado"] == "cerrado"


async def test_si_la_llamada_de_prueba_falla_se_vuelve_a_abrir() -> None:
    reloj = Reloj()
    c = _circuito(reloj)
    for _ in range(3):
        await _fallar(c)
    reloj.ahora += 31
    await _fallar(c)
    assert c.estado is EstadoCircuito.ABIERTO
    assert c.aperturas == 2


# --------------------------------------------------------------------------- #
# Compartimento y tiempo límite
# --------------------------------------------------------------------------- #


async def test_el_compartimento_lleno_rechaza_en_vez_de_hacer_cola() -> None:
    c = _circuito(Reloj(), max_concurrencia=1, espera_turno_seg=0.05)
    dentro = asyncio.Event()
    soltar = asyncio.Event()

    async def ocupar() -> None:
        async with c.proteger():
            dentro.set()
            await soltar.wait()

    tarea = asyncio.create_task(ocupar())
    await dentro.wait()
    with pytest.raises(ServicioNoDisponible, match="demasiadas consultas"):
        async with c.proteger():
            pass
    soltar.set()
    await tarea
    # Estar lleno no es estar caído: el circuito sigue cerrado y se puede volver a entrar.
    assert c.estado is EstadoCircuito.CERRADO
    async with c.proteger():
        pass


async def test_el_tope_total_corta_la_espera_y_cuenta_como_fallo() -> None:
    c = _circuito(Reloj(), umbral_fallos=1, limite_seg=0.05)
    inicio = time.monotonic()
    with pytest.raises(ServicioNoDisponible):
        async with c.proteger():
            await asyncio.sleep(5)
    assert time.monotonic() - inicio < 2
    assert c.estado is EstadoCircuito.ABIERTO


# --------------------------------------------------------------------------- #
# Qué es un fallo
# --------------------------------------------------------------------------- #


def _estado_http(codigo: int) -> httpx.HTTPStatusError:
    peticion = httpx.Request("GET", "https://servicio.test")
    return httpx.HTTPStatusError(
        "error", request=peticion, response=httpx.Response(codigo, request=peticion)
    )


@pytest.mark.parametrize(
    ("error", "es_fallo"),
    [
        (httpx.ConnectTimeout("lento"), True),
        (TimeoutError(), True),
        (_estado_http(503), True),
        (_estado_http(429), True),
        (_estado_http(404), False),
        (ValueError("json roto"), False),
        (NoEncontrado("no"), False),
        (ServicioNoDisponible("ya rechazado"), False),
    ],
)
def test_clasificacion_de_fallos(error: BaseException, es_fallo: bool) -> None:
    assert es_fallo_de_servicio(error) is es_fallo


def test_la_causa_encadenada_cuenta() -> None:
    """Los adaptadores traducen el error de red a uno de dominio; la causa es la que informa."""
    try:
        try:
            raise httpx.ConnectError("caído")
        except httpx.ConnectError as red:
            raise EstadoInvalido("No se pudo consultar.") from red
    except EstadoInvalido as error:
        assert es_fallo_de_servicio(error)

    marcado = EstadoInvalido("IA saturada")
    marcado.__cause__ = FalloDelServicio("HTTP 429")
    assert es_fallo_de_servicio(marcado)


# --------------------------------------------------------------------------- #
# Un adaptador real: el SRI
# --------------------------------------------------------------------------- #


async def test_con_el_sri_caido_se_responde_al_instante_sin_llamarlo() -> None:
    llamadas = 0

    def responder(peticion: httpx.Request) -> httpx.Response:
        nonlocal llamadas
        llamadas += 1
        raise httpx.ConnectError("el SRI no contesta", request=peticion)

    sri = ConsultaSri(transporte=httpx.MockTransport(responder))
    for _ in range(5):
        with pytest.raises(EstadoInvalido):
            await sri.consultar("1790012345001")
    assert circuito_sri().estado is EstadoCircuito.ABIERTO

    antes = llamadas
    with pytest.raises(ServicioNoDisponible, match="SRI no responde"):
        await sri.consultar("1790012345001")
    assert llamadas == antes
    assert estado_circuitos()["sri"]["estado"] == "abierto"


def test_servicio_no_disponible_se_traduce_a_503_y_no_a_409() -> None:
    for tipo, codigo in CODIGOS_POR_ERROR:
        if issubclass(ServicioNoDisponible, tipo):
            assert codigo == status.HTTP_503_SERVICE_UNAVAILABLE
            break
    # Y sigue siendo un `EstadoInvalido`, para que el código que ya lo atrapaba no cambie.
    assert issubclass(ServicioNoDisponible, EstadoInvalido)


# --------------------------------------------------------------------------- #
# Redis caído: el API degrada a «sin caché»
# --------------------------------------------------------------------------- #

# Un puerto en el que no escucha nadie: la conexión se rechaza (o agota su tope corto).
_REDIS_CAIDO = "redis://127.0.0.1:1/0"


async def test_con_redis_caido_las_lecturas_degradan_y_el_circuito_se_abre() -> None:
    cache = CacheRedis(_REDIS_CAIDO, tiempo_limite_seg=0.3)
    try:
        # La generación degrada a cero, que es «sin caché», sin lanzar.
        for _ in range(3):
            assert await leer_generacion(cache, "prueba") == 0
        assert circuito("redis").estado is EstadoCircuito.ABIERTO

        # Con el circuito abierto, ni se intenta: el fallo es inmediato.
        inicio = time.monotonic()
        with pytest.raises(ServicioNoDisponible):
            await cache.obtener("cualquiera")
        assert time.monotonic() - inicio < 0.2
        assert await cache.ping() is False

        # La sesión viva no se da por cerrada: se pregunta a la base.
        vida = await seguir(
            cache, sesion_id=uuid4(), usuario_id=uuid4(), inactividad_seg=60, renovar=True
        )
        assert vida is VidaDeSesion.SIN_RESPUESTA
    finally:
        await cache.cerrar()


def test_listo_sigue_en_200_con_el_cache_caido(monkeypatch: pytest.MonkeyPatch) -> None:
    """Redis es opcional: su caída marca el servicio como degradado, no lo saca de la rotación."""

    async def cache_rota() -> str:
        return "error"

    async def bd_bien() -> tuple[bool, str]:
        return True, ""

    monkeypatch.setattr(salud, "estado_cache", cache_rota)
    monkeypatch.setattr(salud, "estado_bd", bd_bien)
    respuesta = TestClient(crear_app()).get("/listo")
    cuerpo = respuesta.json()
    assert respuesta.status_code == 200
    assert cuerpo["listo"] is True
    assert cuerpo["degradado"] is True
    assert cuerpo["dependencias"]["cache"] == "error"
    assert "circuitos" in cuerpo


def test_listo_sigue_en_503_sin_base(monkeypatch: pytest.MonkeyPatch) -> None:
    async def cache_bien() -> str:
        return "ok"

    async def bd_caida() -> tuple[bool, str]:
        return False, "no responde"

    monkeypatch.setattr(salud, "estado_cache", cache_bien)
    monkeypatch.setattr(salud, "estado_bd", bd_caida)
    respuesta = TestClient(crear_app()).get("/listo")
    assert respuesta.status_code == 503
    assert respuesta.json()["motivo"] == "no responde"
