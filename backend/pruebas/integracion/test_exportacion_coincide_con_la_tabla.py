"""El total de la tabla y las filas del Excel salen de la misma consulta (QA ciclo 3).

Contra la base real y **solo lectura**: para varias combinaciones de filtros, el `total` de
`buscar` (lo que dice la pantalla) tiene que ser igual al número de filas de `todos` (lo que lleva
el archivo). También comprueba la búsqueda jerárquica por CPC: un código padre trae a sus hijos.

Requiere una base real: ejecutar con `PRUEBAS_INTEGRACION=1`.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from contratacion.dominio.busqueda import Categoria, Filtros, ModoBusqueda, normalizar_terminos
from contratacion.infraestructura.adaptadores.salida.bd.consultas import RepositorioConsultasBd
from contratacion.infraestructura.adaptadores.salida.bd.sesion import normalizar_url_bd
from contratacion.infraestructura.config.ajustes import obtener_ajustes

pytestmark = pytest.mark.skipif(
    os.getenv("PRUEBAS_INTEGRACION") != "1",
    reason="Requiere una base real: ejecutar con PRUEBAS_INTEGRACION=1",
)

BASE = {"categoria": Categoria.INFIMAS, "fuentes_permitidas": ("NCO",)}


@pytest.fixture
async def motor() -> AsyncIterator[AsyncEngine]:
    ajustes = obtener_ajustes()
    motor = create_async_engine(
        normalizar_url_bd(ajustes.database_url).render_as_string(hide_password=False)
    )
    yield motor
    await motor.dispose()


@pytest.mark.parametrize(
    "filtros",
    [
        Filtros(**BASE),
        Filtros(solo_con_plazo=True, **BASE),
        Filtros(terminos=normalizar_terminos(["servicios", "mantenimientos"]), **BASE),
        Filtros(
            terminos=normalizar_terminos(["mantenimiento", "vehiculos"]),
            modo=ModoBusqueda.TODAS,
            **BASE,
        ),
        Filtros(cpc=normalizar_terminos(["87"]), solo_cpc=True, **BASE),
    ],
)
async def test_el_total_de_la_tabla_es_el_numero_de_filas_del_archivo(
    motor: AsyncEngine, filtros: Filtros
) -> None:
    repositorio = RepositorioConsultasBd(motor)
    _, total = await repositorio.buscar(filtros)
    filas = await repositorio.todos(filtros, 100_000)
    assert len(filas) == total


async def test_un_cpc_padre_trae_a_todos_sus_hijos(motor: AsyncEngine) -> None:
    async with motor.connect() as conexion:
        fila = (
            await conexion.execute(
                text(
                    "SELECT c.codigo FROM registro r, unnest(r.cpc_codigos) AS c(codigo) "
                    "WHERE length(c.codigo) >= 6 LIMIT 1"
                )
            )
        ).first()
        if fila is None:
            pytest.skip("La base no tiene ítems con CPC leídos")
        padre = str(fila[0])[:4]
        esperados = (
            await conexion.execute(
                text(
                    "SELECT count(*) FROM registro r JOIN fuente f ON f.id = r.fuente_id "
                    "WHERE f.codigo = 'NCO' AND EXISTS (SELECT 1 FROM unnest(r.cpc_codigos) c "
                    "WHERE c LIKE :patron)"
                ),
                {"patron": f"{padre}%"},
            )
        ).scalar_one()

    _, total = await RepositorioConsultasBd(motor).buscar(
        Filtros(cpc=normalizar_terminos([padre]), solo_cpc=True, **BASE)
    )
    assert total == esperados
    assert total > 0
