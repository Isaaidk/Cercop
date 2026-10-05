"""Sonda: cuántos valores distintos tienen `tipo_proceso` y `estado` en el histórico.

Es la medida que decide el tope del reparto: si se recorta por debajo de la cardinalidad real, la
gráfica deja fuera valores y el «las otras suman X» cuenta mal. Se ejecuta a mano y se borra.
"""

from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, "src")

from sqlalchemy import text

from contratacion.infraestructura.adaptadores.salida.bd.sesion import cerrar_bd, obtener_motor


async def principal() -> None:
    motor = obtener_motor()
    async with motor.connect() as conexion:
        for columna in ("tipo_proceso", "estado", "tipo_necesidad", "entidad"):
            fila = (
                await conexion.execute(
                    text(
                        f"""
                        SELECT count(*) AS filas,
                               count(DISTINCT btrim(r.datos ->> '{columna}')) AS distintos,
                               count(*) FILTER (
                                   WHERE coalesce(btrim(r.datos ->> '{columna}'), '') = ''
                               ) AS vacios
                        FROM registro r
                        """
                    )
                )
            ).first()
            print(f"{columna:16} filas={fila[0]:>7} distintos={fila[1]:>6} vacíos={fila[2]:>7}")

        print("\nLos 6 valores más frecuentes:")
        for columna in ("tipo_proceso", "estado"):
            filas = (
                await conexion.execute(
                    text(
                        f"""
                        SELECT btrim(r.datos ->> '{columna}') AS valor, count(*) AS total
                        FROM registro r
                        WHERE coalesce(btrim(r.datos ->> '{columna}'), '') <> ''
                        GROUP BY 1 ORDER BY 2 DESC LIMIT 6
                        """
                    )
                )
            ).all()
            print(f"\n  {columna}:")
            for valor, total in filas:
                print(f"    {total:>7}  {valor[:88]}")
    await cerrar_bd()


if __name__ == "__main__":
    asyncio.run(principal())
