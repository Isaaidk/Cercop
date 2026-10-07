"""Mantenimiento del histórico sobre PostgreSQL.

Todo lo de aquí trabaja sobre `registro.plazo_proformas_en`, la columna que la ingesta escribe al
guardar y que la migración `0021` rellena para lo que ya estaba. Los dos usos —contar vencimientos y
retirar lo viejo— son rangos sobre el índice parcial `ix_registro_plazo_proformas`.

La purga borra en **una sola sentencia** y no en varias: si se borrara primero de `registro` y
después del histórico, un fallo entre las dos dejaría filas de histórico apuntando a un registro
que ya no existe —y `registro_historial` **no** tiene clave foránea, así que nadie lo impediría—.
Con las dos escrituras en la misma sentencia, o pasan las dos o no pasa ninguna.

El punto de contacto no se nombra: `punto_contacto_entidad.registro_id` es `ON DELETE CASCADE`, así
que se va con la fila sin que haya que acordarse de él. La **única** que hay que borrar a mano es
`registro_historial`, precisamente porque no tiene la clave foránea que la ataría.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from contratacion.aplicacion.puertos.mantenimiento import ResultadoPurga


class RepositorioMantenimientoBd:
    """Implementación sobre PostgreSQL."""

    def __init__(self, motor: AsyncEngine) -> None:
        self._motor = motor

    async def contar_vencimientos(self, *, desde: datetime, hasta: datetime) -> int:
        async with self._motor.connect() as conexion:
            resultado = await conexion.execute(
                text(
                    """
                    SELECT count(*) FROM registro
                     WHERE plazo_proformas_en >= :desde
                       AND plazo_proformas_en < :hasta
                    """
                ),
                {"desde": desde, "hasta": hasta},
            )
        return int(resultado.scalar_one() or 0)

    async def contar_vencidas(self, antes_de: datetime) -> int:
        async with self._motor.connect() as conexion:
            resultado = await conexion.execute(
                text("SELECT count(*) FROM registro WHERE plazo_proformas_en < :antes"),
                {"antes": antes_de},
            )
        return int(resultado.scalar_one() or 0)

    async def purgar_vencidas(
        self, antes_de: datetime, maximo: int, *, simular: bool = False
    ) -> ResultadoPurga:
        if maximo <= 0:
            return ResultadoPurga(registros=0, historial=0, simulado=simular)

        if simular:
            return await self._simular(antes_de, maximo)

        # `objetivo` fija **qué filas** se van y se referencia desde los dos borrados, así que las
        # dos escrituras ven exactamente la misma lista. El orden por `plazo_proformas_en` hace que
        # las vueltas sucesivas sigan un orden: lo más viejo primero.
        async with self._motor.begin() as conexion:
            fila = (
                (
                    await conexion.execute(
                        text(
                            """
                            WITH objetivo AS (
                                SELECT id FROM registro
                                 WHERE plazo_proformas_en < :antes
                                 ORDER BY plazo_proformas_en
                                 LIMIT :maximo
                            ), historial AS (
                                DELETE FROM registro_historial
                                 WHERE registro_id IN (SELECT id FROM objetivo)
                                RETURNING 1
                            ), borrados AS (
                                DELETE FROM registro
                                 WHERE id IN (SELECT id FROM objetivo)
                                RETURNING 1
                            )
                            SELECT (SELECT count(*) FROM borrados) AS registros,
                                   (SELECT count(*) FROM historial) AS historial
                            """
                        ),
                        {"antes": antes_de, "maximo": maximo},
                    )
                )
                .mappings()
                .one()
            )

        return ResultadoPurga(
            registros=int(fila["registros"] or 0), historial=int(fila["historial"] or 0)
        )

    async def _simular(self, antes_de: datetime, maximo: int) -> ResultadoPurga:
        """Cuenta lo que se borraría, sin borrar. Lee, no escribe."""
        async with self._motor.connect() as conexion:
            fila = (
                (
                    await conexion.execute(
                        text(
                            """
                            WITH objetivo AS (
                                SELECT id FROM registro
                                 WHERE plazo_proformas_en < :antes
                                 ORDER BY plazo_proformas_en
                                 LIMIT :maximo
                            )
                            SELECT (SELECT count(*) FROM objetivo) AS registros,
                                   (SELECT count(*) FROM registro_historial
                                     WHERE registro_id IN (SELECT id FROM objetivo)) AS historial
                            """
                        ),
                        {"antes": antes_de, "maximo": maximo},
                    )
                )
                .mappings()
                .one()
            )
        return ResultadoPurga(
            registros=int(fila["registros"] or 0),
            historial=int(fila["historial"] or 0),
            simulado=True,
        )
