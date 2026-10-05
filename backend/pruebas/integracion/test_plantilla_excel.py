"""Repositorio de plantillas contra una base real.

Lo que ninguna prueba de unidad puede cubrir: que el `INSERT ... ON CONFLICT` deje **una sola fila**
por empresa, que el `DELETE ... RETURNING` devuelva lo que borró y que `actualizado_en` se mueva sin
tocar `creado_en`.

El primero es el que importa. La regla acordada es «una plantilla por empresa, subir otra
reemplaza la anterior», y la garantiza la clave primaria. Si el `ON CONFLICT` estuviera mal
escrito, la segunda subida fallaría con un error de clave duplicada —visible— o, peor, si alguien
hubiera puesto un `UNIQUE` sobre otra columna, dejaría dos filas y la exportación usaría la que
devolviera el motor,
que no es una decisión que se pueda dejar al azar.

Requiere una base real: ejecutar con `PRUEBAS_INTEGRACION=1`.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from contratacion.infraestructura.adaptadores.salida.bd.plantillas import RepositorioPlantillasBd
from contratacion.infraestructura.adaptadores.salida.bd.sesion import normalizar_url_bd
from contratacion.infraestructura.config.ajustes import obtener_ajustes

pytestmark = pytest.mark.skipif(
    os.getenv("PRUEBAS_INTEGRACION") != "1",
    reason="Requiere una base real: ejecutar con PRUEBAS_INTEGRACION=1",
)

AHORA = datetime.now(UTC)


class Escenario(NamedTuple):
    motor: AsyncEngine
    negocio_id: uuid.UUID
    otro_negocio_id: uuid.UUID
    usuario_id: uuid.UUID


@pytest.fixture
async def escenario() -> AsyncIterator[Escenario]:
    """Dos negocios con un usuario cada uno. Uno sirve para comprobar el aislamiento."""
    ajustes = obtener_ajustes()
    motor = create_async_engine(
        normalizar_url_bd(ajustes.database_url).render_as_string(hide_password=False),
        pool_pre_ping=True,
    )
    negocio_id, otro_negocio_id = uuid.uuid4(), uuid.uuid4()
    usuario_id = uuid.uuid4()

    async with motor.begin() as conexion:
        for negocio, nombre in ((negocio_id, "Plantilla A"), (otro_negocio_id, "Plantilla B")):
            await conexion.execute(
                text("SELECT set_config('app.negocio_id', :valor, true)"),
                {"valor": str(negocio)},
            )
            await conexion.execute(
                text("INSERT INTO negocio (id, nombre, estado) VALUES (:id, :nombre, 'activo')"),
                {"id": str(negocio), "nombre": nombre},
            )
            await conexion.execute(
                text(
                    "INSERT INTO usuario (id, negocio_id, email, hash_password, nombre, rol, "
                    "estado) VALUES (:id, :negocio, :email, 'x', 'Ana', 'admin_negocio', 'activo')"
                ),
                {
                    "id": str(usuario_id if negocio == negocio_id else uuid.uuid4()),
                    "negocio": str(negocio),
                    "email": f"plantilla-{negocio.hex[:12]}@prueba.ec",
                },
            )

    try:
        yield Escenario(motor, negocio_id, otro_negocio_id, usuario_id)
    finally:
        async with motor.begin() as conexion:
            for negocio in (negocio_id, otro_negocio_id):
                await conexion.execute(
                    text("SELECT set_config('app.negocio_id', :valor, true)"),
                    {"valor": str(negocio)},
                )
                # `plantilla_excel` cae con `ON DELETE CASCADE`, así que borrar el negocio basta.
                await conexion.execute(
                    text("DELETE FROM negocio WHERE id = :id"), {"id": str(negocio)}
                )
        await motor.dispose()


async def _reemplazar(
    escenario: Escenario,
    *,
    negocio_id: uuid.UUID,
    nombre: str,
    tamano: int = 2048,
    subida_por: uuid.UUID | None = None,
) -> None:
    repositorio = RepositorioPlantillasBd(escenario.motor)
    await repositorio.reemplazar(
        negocio_id=negocio_id,
        nombre_archivo=nombre,
        ruta=f"/plantillas/{negocio_id}.xlsx",
        hash_contenido="a" * 64,
        tamano_bytes=tamano,
        subida_por=subida_por,
        momento=AHORA,
    )


async def _contar_filas(escenario: Escenario, negocio_id: uuid.UUID) -> int:
    """Cuenta las filas **sin** el contexto del negocio, para ver el estado real de la tabla."""
    async with escenario.motor.connect() as conexion:
        return int(
            (
                await conexion.execute(
                    text("SELECT count(*) FROM plantilla_excel WHERE negocio_id = :id"),
                    {"id": str(negocio_id)},
                )
            ).scalar_one()
        )


async def test_sin_plantilla_devuelve_nada(escenario: Escenario) -> None:
    repositorio = RepositorioPlantillasBd(escenario.motor)

    assert await repositorio.obtener(negocio_id=escenario.negocio_id) is None


async def test_guardar_y_leer_devuelve_lo_guardado(escenario: Escenario) -> None:
    await _reemplazar(
        escenario, negocio_id=escenario.negocio_id, nombre="mi-plantilla.xlsx", subida_por=None
    )
    repositorio = RepositorioPlantillasBd(escenario.motor)

    guardada = await repositorio.obtener(negocio_id=escenario.negocio_id)

    assert guardada is not None
    assert guardada.nombre_archivo == "mi-plantilla.xlsx"
    assert guardada.tamano_bytes == 2048
    assert guardada.hash_contenido == "a" * 64


async def test_subir_dos_veces_deja_una_sola_fila(escenario: Escenario) -> None:
    """Es la regla acordada, y la garantiza la clave primaria: la última subida gana."""
    await _reemplazar(escenario, negocio_id=escenario.negocio_id, nombre="primera.xlsx")
    await _reemplazar(
        escenario, negocio_id=escenario.negocio_id, nombre="segunda.xlsx", tamano=4096
    )

    repositorio = RepositorioPlantillasBd(escenario.motor)
    guardada = await repositorio.obtener(negocio_id=escenario.negocio_id)

    assert await _contar_filas(escenario, escenario.negocio_id) == 1
    assert guardada is not None
    assert guardada.nombre_archivo == "segunda.xlsx"
    assert guardada.tamano_bytes == 4096


async def test_al_reemplazar_se_conserva_la_fecha_de_la_primera(escenario: Escenario) -> None:
    """`creado_en` y `actualizado_en` son dos datos distintos y hay que poder distinguirlos."""
    await _reemplazar(escenario, negocio_id=escenario.negocio_id, nombre="primera.xlsx")

    despues = AHORA + timedelta(days=3)
    repositorio = RepositorioPlantillasBd(escenario.motor)
    await repositorio.reemplazar(
        negocio_id=escenario.negocio_id,
        nombre_archivo="segunda.xlsx",
        ruta=f"/plantillas/{escenario.negocio_id}.xlsx",
        hash_contenido="b" * 64,
        tamano_bytes=1024,
        subida_por=None,
        momento=despues,
    )

    async with escenario.motor.connect() as conexion:
        fila: Any = (
            await conexion.execute(
                text(
                    "SELECT creado_en, actualizado_en FROM plantilla_excel WHERE negocio_id = :id"
                ),
                {"id": str(escenario.negocio_id)},
            )
        ).one()

    assert fila[0].date() == AHORA.date()
    assert fila[1].date() == despues.date()


async def test_eliminar_devuelve_lo_que_quito_y_deja_la_tabla_limpia(escenario: Escenario) -> None:
    """Devuelve la fila porque quien llama necesita la ruta del archivo que hay que borrar.

    Después de borrar la fila ya no hay dónde preguntarla, así que si no la devolviera aquí, el
    archivo se quedaría en el disco para siempre.
    """
    await _reemplazar(escenario, negocio_id=escenario.negocio_id, nombre="mi-plantilla.xlsx")
    repositorio = RepositorioPlantillasBd(escenario.motor)

    quitada = await repositorio.eliminar(negocio_id=escenario.negocio_id)

    assert quitada is not None
    assert quitada.nombre_archivo == "mi-plantilla.xlsx"
    assert quitada.ruta == f"/plantillas/{escenario.negocio_id}.xlsx"
    assert await repositorio.obtener(negocio_id=escenario.negocio_id) is None
    assert await _contar_filas(escenario, escenario.negocio_id) == 0


async def test_eliminar_sin_plantilla_no_falla(escenario: Escenario) -> None:
    repositorio = RepositorioPlantillasBd(escenario.motor)

    assert await repositorio.eliminar(negocio_id=escenario.negocio_id) is None


async def test_la_plantilla_de_un_negocio_no_es_la_de_otro(escenario: Escenario) -> None:
    """Cada empresa tiene la suya: quitar una no puede tocar la de al lado."""
    await _reemplazar(escenario, negocio_id=escenario.negocio_id, nombre="de-A.xlsx")
    await _reemplazar(escenario, negocio_id=escenario.otro_negocio_id, nombre="de-B.xlsx")

    repositorio = RepositorioPlantillasBd(escenario.motor)
    await repositorio.eliminar(negocio_id=escenario.negocio_id)

    assert await repositorio.obtener(negocio_id=escenario.negocio_id) is None
    vecina = await repositorio.obtener(negocio_id=escenario.otro_negocio_id)
    assert vecina is not None
    assert vecina.nombre_archivo == "de-B.xlsx"
