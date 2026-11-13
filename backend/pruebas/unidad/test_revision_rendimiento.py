"""Pruebas de la revisión de rendimiento (docs/41).

Cada optimización tiene que dar **exactamente** el mismo resultado que el código al que sustituye, y
las que comparten trabajo entre peticiones no pueden mezclar respuestas de preguntas distintas.
"""

from __future__ import annotations

import asyncio
import sys
import unicodedata
from types import SimpleNamespace
from uuid import uuid4

import pytest

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.coalescer import en_curso, una_vez
from contratacion.dominio.errores import (
    CambioDeContrasenaPendiente,
    ConsentimientoPendiente,
    NoEncontrado,
)
from contratacion.dominio.radar import plegar
from contratacion.dominio.texto import sin_marcas
from contratacion.infraestructura.adaptadores.entrada.http import dependencias
from contratacion.infraestructura.adaptadores.salida.bd.entrada import EstadoDeEntrada


def _plegar_de_antes(texto: str | None) -> str:
    base = unicodedata.normalize("NFKD", str(texto or ""))
    sin_tilde = "".join(caracter for caracter in base if not unicodedata.combining(caracter))
    return " ".join(sin_tilde.lower().split())


# --- plegar ---------------------------------------------------------------------------------------


def test_sin_marcas_coincide_con_el_filtro_en_todo_unicode() -> None:
    """Todos los puntos de Unicode, de golpe: ninguno puede comportarse distinto."""
    todos = "".join(
        chr(punto) for punto in range(sys.maxunicode + 1) if not 0xD800 <= punto < 0xE000
    )
    esperado = "".join(c for c in todos if not unicodedata.combining(c))
    assert sin_marcas(todos) == esperado


@pytest.mark.parametrize(
    "texto",
    [
        None,
        "",
        "PICHINCHA",
        "Pichincha - Quito",
        "  Adquisición   de  CÓMPUTO\tñandú  ",
        "İstanbul ǅ ﬁ ½ Å",
        "á̧ ë",
        "x" * 500 + " Galápagos " + "ü" * 300,
    ],
)
def test_plegar_da_lo_mismo_que_antes(texto: str | None) -> None:
    assert plegar(texto) == _plegar_de_antes(texto)
    # Dos veces: la segunda sale del recuerdo de textos cortos.
    assert plegar(texto) == _plegar_de_antes(texto)


# --- una sola consulta para peticiones idénticas -------------------------------------------------


async def test_peticiones_identicas_a_la_vez_comparten_una_consulta() -> None:
    llamadas = 0

    async def calcular() -> dict[str, int]:
        nonlocal llamadas
        llamadas += 1
        await asyncio.sleep(0.01)
        return {"total": 7}

    resultados = await asyncio.gather(*(una_vez("clave-a", calcular) for _ in range(20)))
    assert llamadas == 1
    assert all(resultado == {"total": 7} for resultado in resultados)
    assert en_curso() == 0


async def test_claves_distintas_no_comparten_nada() -> None:
    async def valor(n: int) -> int:
        await asyncio.sleep(0.01)
        return n

    a, b = await asyncio.gather(
        una_vez("clave-1", lambda: valor(1)), una_vez("clave-2", lambda: valor(2))
    )
    assert (a, b) == (1, 2)


async def test_sin_recuerdo_despues_de_terminar() -> None:
    llamadas = 0

    async def calcular() -> int:
        nonlocal llamadas
        llamadas += 1
        return llamadas

    assert await una_vez("clave-b", calcular) == 1
    assert await una_vez("clave-b", calcular) == 2


async def test_un_error_llega_a_todos_y_no_se_recuerda() -> None:
    async def falla() -> int:
        await asyncio.sleep(0.01)
        raise RuntimeError("base caída")

    resultados = await asyncio.gather(
        *(una_vez("clave-c", falla) for _ in range(3)), return_exceptions=True
    )
    assert all(isinstance(resultado, RuntimeError) for resultado in resultados)
    assert en_curso() == 0


async def test_si_se_va_quien_empezo_los_demas_reciben_el_resultado() -> None:
    async def lento() -> str:
        await asyncio.sleep(0.05)
        return "listo"

    primera = asyncio.ensure_future(una_vez("clave-d", lento))
    await asyncio.sleep(0)
    segunda = asyncio.ensure_future(una_vez("clave-d", lento))
    await asyncio.sleep(0.01)
    primera.cancel()
    assert await segunda == "listo"


# --- la puerta de entrada en una consulta ---------------------------------------------------------


def _peticion_con(estado: EstadoDeEntrada | None) -> SimpleNamespace:
    peticion = SimpleNamespace(state=SimpleNamespace())
    if estado is not None:
        peticion.state.estado_de_entrada = estado
    return peticion


def _estado(actor: Actor, **campos: object) -> EstadoDeEntrada:
    base: dict[str, object] = {
        "negocio_id": actor.negocio_id,
        "usuario_id": actor.usuario_id,
        "negocio": None,
        "cuenta_visible": True,
        "debe_cambiar_contrasena": False,
        "politica_pendiente": None,
    }
    base.update(campos)
    return EstadoDeEntrada(**base)  # type: ignore[arg-type]


class _NoDebeLlamarse:
    async def obtener(self, **_: object) -> None:
        raise AssertionError("con el estado ya leído no se vuelve a la base")

    async def pendiente_de(self, **_: object) -> None:
        raise AssertionError("con el estado ya leído no se vuelve a la base")


def _actor() -> Actor:
    return Actor(usuario_id=uuid4(), negocio_id=uuid4(), rol="usuario")


async def _puerta(peticion: SimpleNamespace, actor: Actor) -> None:
    falso = _NoDebeLlamarse()
    await dependencias.consentimiento_del_actor(
        peticion,  # type: ignore[arg-type]
        actor,
        consentimientos=falso,  # type: ignore[arg-type]
        cuentas=falso,  # type: ignore[arg-type]
    )


async def test_la_puerta_deja_pasar_sin_volver_a_la_base() -> None:
    actor = _actor()
    await _puerta(_peticion_con(_estado(actor)), actor)


async def test_la_puerta_bloquea_la_contrasena_temporal() -> None:
    actor = _actor()
    with pytest.raises(CambioDeContrasenaPendiente):
        await _puerta(_peticion_con(_estado(actor, debe_cambiar_contrasena=True)), actor)


async def test_la_puerta_bloquea_las_politicas_pendientes() -> None:
    actor = _actor()
    with pytest.raises(ConsentimientoPendiente):
        await _puerta(_peticion_con(_estado(actor, politica_pendiente=3)), actor)


async def test_la_puerta_falla_cerrada_si_la_cuenta_no_se_ve() -> None:
    actor = _actor()
    with pytest.raises(NoEncontrado):
        await _puerta(_peticion_con(_estado(actor, cuenta_visible=False)), actor)


async def test_un_estado_de_otra_persona_no_sirve_y_se_pregunta_a_la_base() -> None:
    """Si lo guardado no es de este actor, se ignora: la consulta de siempre decide."""
    actor = _actor()
    ajeno = _estado(_actor())
    with pytest.raises(AssertionError, match="no se vuelve a la base"):
        await _puerta(_peticion_con(ajeno), actor)
