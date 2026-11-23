"""Si entran cientos de ínfimas de golpe, sus fichas (y CPC) se leen hasta vaciar la cola."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

import pytest

from contratacion.aplicacion.casos_uso.recoger_items import ResultadoDetalle
from contratacion.tareas import planificador


def _preparar(monkeypatch: pytest.MonkeyPatch, tandas: list[ResultadoDetalle]) -> dict[str, int]:
    cuenta = {"llamadas": 0, "generaciones": 0}

    @asynccontextmanager
    async def bloqueo(_nombre: str) -> Any:
        yield object()

    async def recoger(*_a: Any, **_k: Any) -> ResultadoDetalle:
        cuenta["llamadas"] += 1
        return tandas.pop(0) if tandas else ResultadoDetalle()

    async def subir(_cache: Any) -> None:
        cuenta["generaciones"] += 1

    monkeypatch.setattr(planificador, "bloqueo_de_ingesta", bloqueo)
    monkeypatch.setattr(planificador, "recoger_items", recoger)
    monkeypatch.setattr(planificador, "subir_generacion", subir)
    return cuenta


def test_vacia_la_cola_por_tandas(monkeypatch: pytest.MonkeyPatch) -> None:
    # 755 nuevas: 150 + 150 + 150 + 150 + 155 → todas con CPC en la misma pasada.
    tandas = [
        ResultadoDetalle(revisados=150, con_items=150, quedan=q) for q in (605, 455, 305, 155)
    ]
    tandas.append(ResultadoDetalle(revisados=155, con_items=155, quedan=0))
    cuenta = _preparar(monkeypatch, tandas)
    leidas = asyncio.run(
        planificador._leer_fichas(None, [], fichas=150, cache=None, tiempo_max_seg=600)  # type: ignore[arg-type]
    )
    assert leidas == 755
    assert cuenta["llamadas"] == 5
    assert cuenta["generaciones"] == 5  # cada tanda se publica según llega


def test_para_si_una_tanda_no_avanza(monkeypatch: pytest.MonkeyPatch) -> None:
    # El portal falla: no se insiste en un bucle contra él.
    tandas = [ResultadoDetalle(revisados=150, fallidos=150, quedan=605)]
    cuenta = _preparar(monkeypatch, tandas)
    leidas = asyncio.run(
        planificador._leer_fichas(None, [], fichas=150, cache=None, tiempo_max_seg=600)  # type: ignore[arg-type]
    )
    assert leidas == 0 and cuenta["llamadas"] == 1


def test_sin_tiempo_lee_una_sola_tanda(monkeypatch: pytest.MonkeyPatch) -> None:
    tandas = [ResultadoDetalle(revisados=12, con_items=12, quedan=500)]
    cuenta = _preparar(monkeypatch, tandas)
    asyncio.run(planificador._leer_fichas(None, [], fichas=12, cache=None))  # type: ignore[arg-type]
    assert cuenta["llamadas"] == 1
