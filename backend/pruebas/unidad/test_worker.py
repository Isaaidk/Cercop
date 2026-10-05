"""Pruebas del precalentado de catálogos al cerrar un ciclo de ingesta.

Se comprueban dos cosas pequeñas y una que no lo es. Las pequeñas: que el precalentado ocurre —el
recorrido del histórico se paga en el worker y no en la primera visita de cada persona— y que
ocurre **dentro** del ciclo, no como algo que alguien tenga que acordarse de llamar.

La que importa: que un fallo al precalentar **no puede tumbar el ciclo**. El ciclo es lo que trae
los datos; el precalentado es una mejora de latencia. Perder el primero cuesta datos, perder el
segundo cuesta unos segundos de base de datos en la siguiente visita.
"""

from __future__ import annotations

from typing import Any

import pytest

from contratacion.tareas import worker


@pytest.fixture
def precalentado_vigilado(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Sustituye el precalentado real por uno que solo anota con qué se le llamó."""
    llamadas: list[dict[str, Any]] = []

    async def falso(**kwargs: Any) -> dict[str, Any]:
        llamadas.append(kwargs)
        return {}

    monkeypatch.setattr(worker, "obtener_catalogos", falso)
    return llamadas


async def test_precalentar_pide_los_catalogos_con_su_tiempo_de_vida(
    precalentado_vigilado: list[dict[str, Any]],
) -> None:
    await worker._precalentar_catalogos()

    assert len(precalentado_vigilado) == 1
    assert "cache" in precalentado_vigilado[0]
    assert precalentado_vigilado[0]["ttl_seg"] > 0


async def test_un_fallo_al_precalentar_no_se_propaga(monkeypatch: pytest.MonkeyPatch) -> None:
    """El ciclo no puede caerse por una mejora de latencia."""

    async def falla(**kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("el almacén no responde")

    monkeypatch.setattr(worker, "obtener_catalogos", falla)

    await worker._precalentar_catalogos()


async def test_el_ciclo_precalienta_sin_que_nadie_se_lo_pida(
    monkeypatch: pytest.MonkeyPatch,
    precalentado_vigilado: list[dict[str, Any]],
) -> None:
    """Va dentro del ciclo a propósito: si hubiera que llamarlo aparte, algún día no se llamaría."""

    async def ciclo(*_: Any, **__: Any) -> list[Any]:
        return []

    monkeypatch.setattr(worker, "ejecutar_todos", ciclo)
    monkeypatch.setattr(worker, "RepositorioIngesta", lambda *_: object())

    codigo = await worker.ejecutar_un_ciclo()

    assert len(precalentado_vigilado) == 1
    assert codigo == 0
