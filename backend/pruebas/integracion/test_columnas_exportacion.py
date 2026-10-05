"""Selección de columnas contra una base real.

Lo que ninguna prueba de unidad puede cubrir aquí:

- Que el arreglo llegue a PostgreSQL **como arreglo** y no como cadena. Sin el `CAST(:columnas AS
  text[])` del adaptador, el parámetro entra sin tipo y la sentencia falla con un error que habla de
  tipos, no de columnas: es el fallo que aparece al guardar y no al escribir el código.
- Que `ON CONFLICT` deje **una sola fila** por empresa: la regla es «una selección por empresa» y la
  garantiza la clave primaria, no el código que llama.
- Que el aislamiento funcione de verdad: dos empresas con selecciones distintas no pueden verse la
  una a la otra.

Requiere una base real: ejecutar con `PRUEBAS_INTEGRACION=1`.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import NamedTuple

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from contratacion.infraestructura.adaptadores.salida.bd.columnas import RepositorioColumnasBd
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
    """Dos negocios con un usuario cada uno. El segundo sirve para comprobar el aislamiento."""
    ajustes = obtener_ajustes()
    motor = create_async_engine(
        normalizar_url_bd(ajustes.database_url).render_as_string(hide_password=False),
        pool_pre_ping=True,
    )
    negocio_id, otro_negocio_id = uuid.uuid4(), uuid.uuid4()
    usuario_id = uuid.uuid4()

    async with motor.begin() as conexion:
        for negocio, nombre in ((negocio_id, "Columnas A"), (otro_negocio_id, "Columnas B")):
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
                    "email": f"columnas-{negocio.hex[:12]}@prueba.ec",
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
                # `exportacion_columnas` cae con `ON DELETE CASCADE`, así que basta con el negocio.
                await conexion.execute(
                    text("DELETE FROM negocio WHERE id = :id"), {"id": str(negocio)}
                )
        await motor.dispose()


async def _contar(escenario: Escenario) -> int:
    """Cuenta las filas **de este negocio**, que es lo que la prueba quiere medir.

    Contaba la tabla entera, con el argumento de «ver el estado real sin contexto de negocio». Ese
    argumento no se sostiene: el rol con el que corren estas pruebas **se salta RLS**
    (`rolbypassrls`), así que sin contexto no se ve el estado real de nada, se ven las filas de
    todas las empresas. Mientras la tabla estuvo vacía el número coincidía por casualidad; en cuanto
    otra empresa guardó sus columnas —el panel lo hace en cuanto alguien elige— la comprobación
    falló sin que nada estuviera roto. Se cuenta lo propio y se deja de depender de que la tabla
    esté vacía, que estas pruebas no pueden garantizar.
    """
    async with escenario.motor.connect() as conexion:
        fila = await conexion.execute(
            text("SELECT count(*) FROM exportacion_columnas WHERE negocio_id = :id"),
            {"id": str(escenario.negocio_id)},
        )
        return int(fila.scalar_one())


async def test_sin_seleccion_no_hay_fila(escenario: Escenario) -> None:
    """«No ha elegido nada» se representa con la ausencia de fila, no con una lista vacía."""
    repositorio = RepositorioColumnasBd(escenario.motor)

    assert await repositorio.obtener(negocio_id=escenario.negocio_id) is None


async def test_guardar_y_volver_a_leer(escenario: Escenario) -> None:
    repositorio = RepositorioColumnasBd(escenario.motor)

    await repositorio.guardar(
        negocio_id=escenario.negocio_id,
        columnas=("codigo", "entidad", "dias_proforma"),
        actualizado_por=escenario.usuario_id,
        momento=AHORA,
    )
    guardada = await repositorio.obtener(negocio_id=escenario.negocio_id)

    assert guardada is not None
    # El orden de la selección es el que eligió la persona y se conserva: el archivo lo decide el
    # catálogo, pero lo que se guarda tiene que poder compararse sin ambigüedad.
    assert guardada.columnas == ("codigo", "entidad", "dias_proforma")


async def test_una_lista_vacia_significa_todas(escenario: Escenario) -> None:
    repositorio = RepositorioColumnasBd(escenario.motor)

    await repositorio.guardar(
        negocio_id=escenario.negocio_id,
        columnas=(),
        actualizado_por=escenario.usuario_id,
        momento=AHORA,
    )
    guardada = await repositorio.obtener(negocio_id=escenario.negocio_id)

    assert guardada is not None
    assert guardada.columnas == ()


async def test_guardar_dos_veces_deja_una_sola_fila(escenario: Escenario) -> None:
    """Reemplaza: no se acumulan selecciones para la misma empresa."""
    repositorio = RepositorioColumnasBd(escenario.motor)

    for columnas in (("codigo",), ("codigo", "entidad")):
        await repositorio.guardar(
            negocio_id=escenario.negocio_id,
            columnas=columnas,
            actualizado_por=escenario.usuario_id,
            momento=AHORA,
        )

    guardada = await repositorio.obtener(negocio_id=escenario.negocio_id)

    assert await _contar(escenario) == 1
    assert guardada is not None
    assert guardada.columnas == ("codigo", "entidad")


async def test_actualizado_en_se_mueve_al_reemplazar(escenario: Escenario) -> None:
    repositorio = RepositorioColumnasBd(escenario.motor)

    await repositorio.guardar(
        negocio_id=escenario.negocio_id,
        columnas=("codigo",),
        actualizado_por=escenario.usuario_id,
        momento=AHORA,
    )
    despues = AHORA + timedelta(minutes=5)
    await repositorio.guardar(
        negocio_id=escenario.negocio_id,
        columnas=("codigo", "entidad"),
        actualizado_por=escenario.usuario_id,
        momento=despues,
    )

    guardada = await repositorio.obtener(negocio_id=escenario.negocio_id)

    assert guardada is not None
    assert guardada.actualizado_en > AHORA


async def test_cada_empresa_ve_solo_su_seleccion(escenario: Escenario) -> None:
    """El aislamiento lo aplica la base, no el código que llama."""
    repositorio = RepositorioColumnasBd(escenario.motor)

    await repositorio.guardar(
        negocio_id=escenario.negocio_id,
        columnas=("codigo",),
        actualizado_por=escenario.usuario_id,
        momento=AHORA,
    )

    assert await repositorio.obtener(negocio_id=escenario.otro_negocio_id) is None
