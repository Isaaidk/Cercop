"""Selección de columnas de exportación sobre PostgreSQL.

Una tabla, una fila por empresa y una escritura que reemplaza con `ON CONFLICT`, igual que la
plantilla. El detalle que sí merece explicación es el `CAST(... AS text[])`: sin él, el parámetro
llega como un valor sin tipo y PostgreSQL no sabe si el destino es un arreglo o una cadena, así que
la sentencia falla en el único momento en el que se nota —al guardar— y con un error que habla de
tipos y no de columnas.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from contratacion.aplicacion.puertos.exportacion import SeleccionDeColumnas
from contratacion.infraestructura.adaptadores.salida.bd.contexto import contexto_negocio

CAMPOS = "negocio_id, columnas, actualizado_en"


def _a_seleccion(fila: Mapping[Any, Any]) -> SeleccionDeColumnas:
    crudas = fila["columnas"] or ()
    return SeleccionDeColumnas(
        negocio_id=fila["negocio_id"],
        columnas=tuple(str(clave) for clave in crudas),
        actualizado_en=fila["actualizado_en"],
    )


class RepositorioColumnasBd:
    """La selección de columnas de cada empresa sobre PostgreSQL."""

    def __init__(self, motor: AsyncEngine) -> None:
        self._motor = motor

    async def obtener(self, *, negocio_id: UUID) -> SeleccionDeColumnas | None:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            fila = (
                (
                    await conexion.execute(
                        text(
                            f"SELECT {CAMPOS} FROM exportacion_columnas "
                            "WHERE negocio_id = :negocio_id"
                        ),
                        {"negocio_id": negocio_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return None if fila is None else _a_seleccion(fila)

    async def guardar(
        self,
        *,
        negocio_id: UUID,
        columnas: Sequence[str],
        actualizado_por: UUID | None,
        momento: datetime,
    ) -> None:
        """Deja esta selección como la de la empresa.

        **Una sola sentencia**, por el mismo motivo que en la plantilla: un «borrar y luego
        insertar» que falle en el segundo paso dejaría a la empresa sin selección —es decir,
        exportando todas las columnas— por haber intentado cambiarla, y nadie lo notaría hasta ver
        un archivo más ancho de lo que se pidió.
        """
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            await conexion.execute(
                text(
                    """
                    INSERT INTO exportacion_columnas (negocio_id, columnas,
                                                      actualizado_por, actualizado_en)
                    VALUES (:negocio_id, CAST(:columnas AS text[]),
                            :actualizado_por, :momento)
                    ON CONFLICT (negocio_id) DO UPDATE
                        SET columnas        = EXCLUDED.columnas,
                            actualizado_por = EXCLUDED.actualizado_por,
                            actualizado_en  = EXCLUDED.actualizado_en
                    """
                ),
                {
                    "negocio_id": negocio_id,
                    "columnas": list(columnas),
                    "actualizado_por": actualizado_por,
                    "momento": momento,
                },
            )
