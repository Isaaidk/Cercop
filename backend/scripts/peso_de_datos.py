"""Cuánto pesa lo que hay guardado y cuánto pesaría lo que se propone guardar.

    .\\.venv\\Scripts\\python.exe scripts\\peso_de_datos.py
    .\\.venv\\Scripts\\python.exe scripts\\peso_de_datos.py
    .\\.venv\\Scripts\\python.exe scripts\\peso_de_datos.py --nuevas-por-dia 378

Responde con medidas, no con estimaciones: consulta los tamaños reales que reporta PostgreSQL
(tabla, TOAST e índices), calcula el coste por fila de cada fuente y proyecta el crecimiento.

Por qué el coste **por fila** y no el de la columna `datos`: lo que ocupa una fila es la suma de sus
columnas —`datos`, `crudo`, `items`, `texto_busqueda`— **más la parte proporcional de todos sus
índices**, y los índices de texto completo (GIN) pesan más que el dato al que sirven. Medir solo
`datos` da una cifra que se queda corta varias veces.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

sys.path.insert(0, "src")

from contratacion.infraestructura.adaptadores.salida.bd.sesion import (
    cerrar_bd,
    obtener_motor,
)

MB = 1024 * 1024


async def _escalar(conexion: AsyncConnection, sql: str, **parametros: object) -> Any:
    """Un solo valor de una consulta, sin envolverlo en filas."""
    resultado = await conexion.execute(text(sql), parametros)
    return resultado.scalar_one()


def _mb(bytes_: float) -> str:
    return f"{bytes_ / MB:,.1f} MB"


async def main() -> None:
    parser = argparse.ArgumentParser(description="Peso real de los datos guardados.")
    parser.add_argument(
        "--nuevas-por-dia",
        type=int,
        default=0,
        metavar="N",
        help="Filas al día que se quieren proyectar (p. ej. 378 del listado general de OCDS).",
    )
    argumentos = parser.parse_args()

    motor = obtener_motor()
    try:
        async with motor.connect() as conexion:
            filas = int(await _escalar(conexion, "SELECT count(*) FROM registro"))
            print()
            print("  PESO DE LO GUARDADO (medido en la base)")
            print(f"  {'-' * 62}")
            if filas == 0:
                print("  El histórico está vacío; no hay nada que medir todavía.")
                print()
                return

            tabla = int(await _escalar(conexion, "SELECT pg_relation_size('registro')"))
            indices = int(await _escalar(conexion, "SELECT pg_indexes_size('registro')"))
            total = int(await _escalar(conexion, "SELECT pg_total_relation_size('registro')"))
            historial = int(
                await _escalar(conexion, "SELECT pg_total_relation_size('registro_historial')")
            )
            por_fila = total / filas

            print(f"  filas                 {filas:>10,}")
            print(f"  tabla + TOAST         {_mb(tabla):>12}")
            print(f"  indices               {_mb(indices):>12}   ({indices / total:.0%} del total)")
            print(f"  registro (todo)       {_mb(total):>12}")
            print(f"  historial             {_mb(historial):>12}")
            print(f"  coste por fila        {por_fila:>10,.0f} bytes   ({por_fila / 1024:.1f} KB)")
            print()

            print("  DE QUÉ SE COMPONE UNA FILA, POR FUENTE")
            print(f"  {'-' * 62}")
            desglose = (
                (
                    await conexion.execute(
                        text(
                            """
                            SELECT f.codigo,
                                   count(*)                        AS filas,
                                   avg(pg_column_size(r.datos))    AS datos,
                                   avg(pg_column_size(r.crudo))    AS crudo,
                                   avg(pg_column_size(r.items))    AS items,
                                   avg(length(r.texto_busqueda))   AS texto,
                                   avg(coalesce(pg_column_size(r.cpc_busqueda), 0)) AS cpc
                            FROM registro r
                            JOIN fuente f ON f.id = r.fuente_id
                            GROUP BY f.codigo
                            ORDER BY count(*) DESC
                            """
                        )
                    )
                )
                .mappings()
                .all()
            )
            print(
                f"  {'fuente':<8}{'filas':>8}{'datos':>8}{'crudo':>8}"
                f"{'items':>8}{'cpc':>7}{'texto':>8}"
            )
            for fila in desglose:
                print(
                    f"  {fila['codigo']:<8}{fila['filas']:>8,}"
                    f"{fila['datos'] or 0:>8,.0f}{fila['crudo'] or 0:>8,.0f}"
                    f"{fila['items'] or 0:>8,.0f}{fila['cpc'] or 0:>7,.0f}"
                    f"{fila['texto'] or 0:>8,.0f}"
                )
            print("  (bytes medios por fila; el coste real por fila es el de arriba, con índices)")
            print()

            print("  LOS ÍNDICES, UNO A UNO")
            print(f"  {'-' * 62}")
            indices_detalle = (
                (
                    await conexion.execute(
                        text(
                            """
                            SELECT indexrelname, pg_relation_size(indexrelid) AS bytes
                            FROM pg_stat_user_indexes
                            WHERE relname = 'registro'
                            ORDER BY pg_relation_size(indexrelid) DESC
                            """
                        )
                    )
                )
                .mappings()
                .all()
            )
            for indice in indices_detalle:
                print(f"  {indice['indexrelname']:<40} {_mb(float(indice['bytes'])):>12}")
            print()

            if argumentos.nuevas_por_dia > 0:
                al_dia = argumentos.nuevas_por_dia * por_fila
                print(f"  PROYECCIÓN CON {argumentos.nuevas_por_dia:,} FILAS NUEVAS AL DÍA")
                print(f"  {'-' * 62}")
                print(f"  al día                {_mb(al_dia):>12}")
                print(f"  al mes (30 días)      {_mb(al_dia * 30):>12}")
                print(f"  al año                {_mb(al_dia * 365):>12}")
                print()
                print(f"  Con {filas:,} filas hoy ({_mb(float(total))}), el histórico tardaría")
                print(f"  en duplicarse unos {filas / argumentos.nuevas_por_dia:,.0f} días.")
                print()
    finally:
        await cerrar_bd()


if __name__ == "__main__":
    asyncio.run(main())
