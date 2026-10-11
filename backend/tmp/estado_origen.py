"""Fotografía de la base de ORIGEN: versión, tamaño y qué ocupa el espacio.

Antes de copiar 110.000 registros conviene saber dos cosas que no se pueden adivinar: qué versión de
PostgreSQL hay al otro lado —porque `pg_dump` no puede leer de un servidor más nuevo que él— y **dónde
está el peso**. Un plan de copia que ignora el tamaño se decide por lo que parece grande, y lo que
parece grande casi nunca es lo que lo es.

Se ejecuta contra la base configurada en el `.env` (la anterior, en Supabase):

    python tmp/estado_origen.py

Es de solo lectura: no crea, no cambia y no borra nada.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from contratacion.infraestructura.adaptadores.salida.bd.sesion import (  # noqa: E402
    normalizar_url_bd,
)
from contratacion.infraestructura.config.ajustes import obtener_ajustes  # noqa: E402

# `reltuples` es una estimación que mantiene el propio PostgreSQL al analizar una tabla, no un
# recuento. Para saber dónde está el peso es mejor que un `count(*)` de cada tabla: contar 110.000
# filas cuesta tiempo y, sobre todo, abre una consulta por tabla en un servidor que no es nuestro.
TABLAS = """
SELECT c.relname,
       c.reltuples::bigint AS filas,
       pg_total_relation_size(c.oid) AS bytes,
       pg_size_pretty(pg_total_relation_size(c.oid)) AS peso
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
ORDER BY pg_total_relation_size(c.oid) DESC
"""


async def principal() -> None:
    ajustes = obtener_ajustes()
    motor = create_async_engine(
        normalizar_url_bd(ajustes.database_url).render_as_string(hide_password=False)
    )

    async with motor.connect() as conexion:
        version = (await conexion.execute(text("SELECT version()"))).scalar_one()
        print(f"Servidor: {version}\n")

        base, peso = (
            await conexion.execute(
                text(
                    """
                    SELECT current_database(),
                           pg_size_pretty(pg_database_size(current_database()))
                    """
                )
            )
        ).one()
        print(f"Base: {base}  ·  {peso}\n")

        extensiones = (
            await conexion.execute(
                text("SELECT extname, extversion FROM pg_extension ORDER BY extname")
            )
        ).all()
        print("Extensiones instaladas:")
        for nombre, version_extension in extensiones:
            print(f"  {nombre:<24} {version_extension}")
        print()

        print("Tablas por peso (las filas son estimación del propio servidor):")
        print(f"  {'tabla':<28} {'filas':>10}  {'peso':>10}")
        print("  " + "-" * 52)
        total = 0
        for nombre, filas, bytes_tabla, peso_tabla in (
            await conexion.execute(text(TABLAS))
        ).all():
            total += bytes_tabla
            print(f"  {nombre:<28} {filas:>10}  {peso_tabla:>10}")
        print("  " + "-" * 52)
        print(f"  {'suma de las tablas':<28} {'':>10}  {total / 1024 / 1024:>9.1f}M")


if __name__ == "__main__":
    asyncio.run(principal())
