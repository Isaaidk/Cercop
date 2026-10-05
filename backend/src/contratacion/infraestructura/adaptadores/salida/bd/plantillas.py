"""Implementación de la plantilla sobre PostgreSQL.

Una sola tabla, una sola fila por empresa y una operación de escritura que reemplaza. Lo que merece
explicación es el **`ON CONFLICT`** del método de reemplazo y no un `DELETE` seguido de `INSERT`.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from contratacion.aplicacion.puertos.plantillas import PlantillaGuardada
from contratacion.infraestructura.adaptadores.salida.bd.contexto import contexto_negocio

CAMPOS = "negocio_id, nombre_archivo, ruta, hash_contenido, tamano_bytes, actualizado_en"


def _a_plantilla(fila: Mapping[Any, Any]) -> PlantillaGuardada:
    return PlantillaGuardada(
        negocio_id=fila["negocio_id"],
        nombre_archivo=str(fila["nombre_archivo"]),
        ruta=str(fila["ruta"]),
        hash_contenido=str(fila["hash_contenido"]),
        tamano_bytes=int(fila["tamano_bytes"]),
        actualizado_en=fila["actualizado_en"],
    )


class RepositorioPlantillasBd:
    """Plantillas por empresa sobre PostgreSQL."""

    def __init__(self, motor: AsyncEngine) -> None:
        self._motor = motor

    async def obtener(self, *, negocio_id: UUID) -> PlantillaGuardada | None:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            fila = (
                (
                    await conexion.execute(
                        text(
                            f"SELECT {CAMPOS} FROM plantilla_excel WHERE negocio_id = :negocio_id"
                        ),
                        {"negocio_id": negocio_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return None if fila is None else _a_plantilla(fila)

    async def reemplazar(
        self,
        *,
        negocio_id: UUID,
        nombre_archivo: str,
        ruta: str,
        hash_contenido: str,
        tamano_bytes: int,
        subida_por: UUID | None,
        momento: datetime,
    ) -> None:
        """Deja esta plantilla como la del negocio.

        **Una sola sentencia, con `ON CONFLICT`.** La alternativa natural —borrar la fila y volver a
        insertarla— tiene un fallo que no se ve: si el `INSERT` no llega a ejecutarse —un corte, un
        error de serialización, un proceso que muere entre las dos— la empresa se queda **sin
        plantilla** por haber intentado cambiarla. Con una sola sentencia no existe el estado
        intermedio.

        La clave primaria es `negocio_id`, así que el `ON CONFLICT` no puede equivocarse de fila: no
        hay dos plantillas posibles para la misma empresa. Y `creado_en` **no** se actualiza, porque
        es cuándo se subió la primera; `actualizado_en`, cuándo se cambió por última vez: son dos
        datos distintos que conviene poder distinguir.
        """
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            await conexion.execute(
                text(
                    """
                    INSERT INTO plantilla_excel (negocio_id, nombre_archivo, ruta,
                                                 hash_contenido, tamano_bytes, subida_por,
                                                 creado_en, actualizado_en)
                    VALUES (:negocio_id, :nombre_archivo, :ruta, :hash_contenido,
                            :tamano_bytes, :subida_por, :momento, :momento)
                    ON CONFLICT (negocio_id) DO UPDATE
                        SET nombre_archivo = EXCLUDED.nombre_archivo,
                            ruta           = EXCLUDED.ruta,
                            hash_contenido = EXCLUDED.hash_contenido,
                            tamano_bytes   = EXCLUDED.tamano_bytes,
                            subida_por     = EXCLUDED.subida_por,
                            actualizado_en = EXCLUDED.actualizado_en
                    """
                ),
                {
                    "negocio_id": negocio_id,
                    "nombre_archivo": nombre_archivo,
                    "ruta": ruta,
                    "hash_contenido": hash_contenido,
                    "tamano_bytes": tamano_bytes,
                    "subida_por": subida_por,
                    "momento": momento,
                },
            )

    async def eliminar(self, *, negocio_id: UUID) -> PlantillaGuardada | None:
        """Quita la fila y devuelve cuál era, para poder borrar su archivo.

        `DELETE ... RETURNING` en lugar de leer y luego borrar: con dos consultas, dos peticiones
        simultáneas podrían leer la misma fila y una de las dos borraría un archivo que la otra
        acaba de sustituir. Con una sola, la base decide quién se lleva la fila y **solo uno**
        recibe la ruta que hay que borrar.
        """
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            fila = (
                (
                    await conexion.execute(
                        text(
                            f"""
                            DELETE FROM plantilla_excel
                            WHERE negocio_id = :negocio_id
                            RETURNING {CAMPOS}
                            """
                        ),
                        {"negocio_id": negocio_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return None if fila is None else _a_plantilla(fila)
