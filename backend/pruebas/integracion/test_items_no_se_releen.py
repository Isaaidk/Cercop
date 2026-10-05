"""Pruebas de cuándo se vuelve a leer la ficha de una necesidad.

La regla que se fija aquí es de **cuota**, no de corrección, y es fácil de romper sin querer: al
actualizar un registro que cambió, el detalle que ya estaba guardado **no** se invalida. Cada ficha
es una petición a un origen que limita la tasa, y volver a leer la de todo lo que cambia cada ciclo
gastaría el presupuesto en fichas ya conocidas.

Se comprueba contra la base real porque la regla vive en el `ON CONFLICT DO UPDATE` del `upsert`, y
ahí no llega ninguna prueba de unidad: un `SET items_recogidos_en = NULL` que volviera a colarse
dejaría el histórico releyéndose entero, sin ningún error y sin que ninguna otra prueba se enterara.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import NamedTuple
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from contratacion.infraestructura.adaptadores.salida.bd.ingesta import RepositorioIngesta
from contratacion.infraestructura.adaptadores.salida.bd.sesion import normalizar_url_bd
from contratacion.infraestructura.config.ajustes import obtener_ajustes

pytestmark = pytest.mark.skipif(
    os.getenv("PRUEBAS_INTEGRACION") != "1",
    reason="Requiere una base real: ejecutar con PRUEBAS_INTEGRACION=1",
)

CODIGO = "PRUEBA-ITEMS"
CLAVE = "prueba-items-1"


class Escenario(NamedTuple):
    motor: AsyncEngine
    fuente_id: UUID


@pytest.fixture
async def escenario() -> AsyncIterator[Escenario]:
    """Una fuente de prueba propia, para no tocar las de verdad."""
    ajustes = obtener_ajustes()
    motor = create_async_engine(
        normalizar_url_bd(ajustes.database_url).render_as_string(hide_password=False),
        pool_pre_ping=True,
    )
    repo = RepositorioIngesta(motor)
    fuente_id = await repo.asegurar_fuente(
        CODIGO,
        "Fuente de prueba de ítems",
        "https://ejemplo.ec/fuente.cpe",
        intervalo_min=15,
        ventana_solape_ciclos=2,
        presupuesto_peticiones_ciclo=10,
    )
    try:
        yield Escenario(motor, fuente_id)
    finally:
        # El borrado cae en cascada sobre `registro`, pero se hace explícito para no depender de que
        # el `ON DELETE` siga puesto: dejar registros huérfanos ensuciaría las pruebas siguientes.
        async with motor.begin() as conexion:
            await conexion.execute(
                text("DELETE FROM registro WHERE fuente_id = :id"), {"id": str(fuente_id)}
            )
            await conexion.execute(
                text("DELETE FROM fuente WHERE id = :id"), {"id": str(fuente_id)}
            )
        await motor.dispose()


async def _guardar(repo: RepositorioIngesta, fuente_id: UUID, *, objeto: str, hash_: str) -> None:
    await repo.guardar_registro(
        fuente_id,
        clave=CLAVE,
        datos={"codigo": "N-1", "objeto_compra": objeto},
        crudo={"objeto_contratacion": objeto},
        texto_busqueda=objeto.lower(),
        hash_contenido=hash_,
        fecha_publicacion=datetime.now(UTC),
    )


async def test_una_necesidad_nueva_queda_pendiente_de_ficha(escenario: Escenario) -> None:
    repo = RepositorioIngesta(escenario.motor)
    await _guardar(repo, escenario.fuente_id, objeto="uno", hash_="h1")

    pendientes = await repo.registros_sin_items([CODIGO], 10)

    assert [fila["clave_natural"] for fila in pendientes] == [CLAVE]


async def test_actualizar_el_contenido_no_devuelve_la_ficha_a_pendiente(
    escenario: Escenario,
) -> None:
    """El caso que importa: el detalle ya leído se conserva cuando el registro cambia."""
    repo = RepositorioIngesta(escenario.motor)
    await _guardar(repo, escenario.fuente_id, objeto="uno", hash_="h1")
    pendiente = (await repo.registros_sin_items([CODIGO], 10))[0]

    await repo.guardar_items(
        pendiente["id"],
        items=[{"codigo": "871410032", "descripcion_cpc": "LAVADO Y ENGRASADO DE AUTOMOTORES"}],
        cpc_busqueda="871410032 lavado y engrasado de automotores",
        cpc_codigos=["871410032"],
    )
    assert await repo.contar_sin_items([CODIGO]) == 0

    # Llega el mismo registro con el objeto de compra cambiado: es lo que pasa cuando la entidad
    # edita la necesidad entre dos ciclos.
    await _guardar(repo, escenario.fuente_id, objeto="dos", hash_="h2")

    assert await repo.contar_sin_items([CODIGO]) == 0
    assert await repo.registros_sin_items([CODIGO], 10) == []

    async with escenario.motor.connect() as conexion:
        fila = (
            await conexion.execute(
                text(
                    "SELECT datos ->> 'objeto_compra' AS objeto, cpc_busqueda, items_recogidos_en"
                    " FROM registro WHERE fuente_id = :id AND clave_natural = :clave"
                ),
                {"id": str(escenario.fuente_id), "clave": CLAVE},
            )
        ).one()
    # El contenido se actualizó **y** el detalle sobrevivió: las dos cosas a la vez.
    assert fila.objeto == "dos"
    assert fila.cpc_busqueda == "871410032 lavado y engrasado de automotores"
    assert fila.items_recogidos_en is not None
