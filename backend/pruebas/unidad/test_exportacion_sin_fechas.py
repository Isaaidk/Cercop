"""La descarga trae exactamente lo que muestra la pantalla, con o sin fecha de publicación.

QA del cliente, ciclo 3: el panel mostraba 281 ínfimas sin filtro de fecha; al descargar, el panel
ponía solo un rango de publicación de tres meses y el archivo traía 275. Las que faltaban eran
ínfimas publicadas antes del rango y todavía abiertas. Ahora la fecha es opcional y nunca se pone
sola; lo que acota el coste es el tope de filas, y se rechaza en vez de recortar.
"""

from __future__ import annotations

import io
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest
from openpyxl import load_workbook

from contratacion.aplicacion.casos_uso.exportar_registros import exportar
from contratacion.dominio.busqueda import Categoria, Filtros
from contratacion.dominio.errores import DatoInvalido
from contratacion.dominio.exportacion import revisar_tope

AHORA = datetime(2026, 11, 18, 15, 0, tzinfo=UTC)


def _fila(numero: int, publicada: datetime) -> dict[str, Any]:
    return {
        "fuente": "NCO",
        "codigo": f"NIC-1790000000001-2026-{numero:05d}",
        "objeto_compra": "Mantenimiento de vehículos",
        "entidad": "GAD",
        "provincia": "PICHINCHA",
        "fecha_publicacion": publicada,
        # Publicada hace meses pero todavía abierta: es justo la que se perdía.
        "fecha_limite_proformas": "2026-11-30 10:00:00",
        "items": [],
    }


class RepositorioDePrueba:
    """Devuelve sus filas y apunta con qué filtros se le pidió."""

    def __init__(self, filas: list[Mapping[str, Any]]) -> None:
        self.filas = filas
        self.filtros: list[Filtros] = []

    async def todos(self, filtros: Filtros, limite: int) -> tuple[Mapping[str, Any], ...]:
        self.filtros.append(filtros)
        return tuple(self.filas[:limite])


async def test_sin_fecha_de_publicacion_se_exporta_todo_lo_que_cumple_los_filtros() -> None:
    filas = [_fila(i, datetime(2026, 5, 1, tzinfo=UTC)) for i in range(281)]
    repositorio = RepositorioDePrueba(filas)
    filtros = Filtros(categoria=Categoria.INFIMAS, fuentes_permitidas=("NCO",))

    resultado = await exportar(
        filtros,
        repositorio=repositorio,  # type: ignore[arg-type]
        limite=20_000,
        momento=AHORA,
    )

    # Las mismas 281 que dice la pantalla, sin ningún rango de fechas añadido por el camino.
    assert resultado.filas == 281
    assert repositorio.filtros[0].desde is None
    assert repositorio.filtros[0].hasta is None
    hoja = load_workbook(io.BytesIO(resultado.contenido)).worksheets[0]
    codigos = [fila[0] for fila in hoja.iter_rows(min_row=2, values_only=True) if fila[0]]
    assert len(codigos) == 281


async def test_pasar_del_tope_se_rechaza_sin_recortar() -> None:
    repositorio = RepositorioDePrueba([_fila(i, AHORA) for i in range(11)])
    with pytest.raises(DatoInvalido):
        await exportar(
            Filtros(fuentes_permitidas=("NCO",)),
            repositorio=repositorio,  # type: ignore[arg-type]
            limite=10,
            momento=AHORA,
        )


def test_el_tope_exacto_se_acepta() -> None:
    revisar_tope(10, limite=10)
    with pytest.raises(DatoInvalido):
        revisar_tope(11, limite=10)
