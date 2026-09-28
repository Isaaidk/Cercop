"""Informe del contenido de la base.

Responde a la pregunta «¿qué hay dentro?» sin abrir un cliente de base de datos: cuántos registros
hay por fuente, cuántas provincias aparecen, cuántas palabras clave hay en el catálogo y cuál fue la
última vez que entró algo.

Es la comprobación que se hace antes de mirar el panel: si el histórico está vacío, una pantalla en
blanco no significa que algo esté roto.
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


async def principal() -> None:
    ajustes = obtener_ajustes()
    motor = create_async_engine(
        normalizar_url_bd(ajustes.database_url).render_as_string(hide_password=False)
    )

    async with motor.connect() as conexion:
        total: int = (await conexion.execute(text("SELECT count(*) FROM registro"))).scalar_one()
        print(f"Registros en el histórico: {total}")

        if total:
            print("\nPor fuente:")
            filas = (
                await conexion.execute(
                    text(
                        """
                        SELECT f.codigo,
                               count(*) AS total,
                               max(r.fecha_publicacion) AS ultima
                        FROM registro r
                        JOIN fuente f ON f.id = r.fuente_id
                        GROUP BY f.codigo
                        ORDER BY 2 DESC
                        """
                    )
                )
            ).all()
            for codigo, cuantos, ultima in filas:
                print(f"  {codigo:<6} {cuantos:>8}   última publicación: {ultima}")

            print("\nProvincias y cantones distintos:")
            provincias = (
                await conexion.execute(
                    text(
                        """
                        SELECT count(DISTINCT btrim(split_part(datos ->> 'provincia', '-', 1))),
                               count(DISTINCT datos ->> 'provincia')
                        FROM registro
                        WHERE COALESCE(datos ->> 'provincia', '') <> ''
                        """
                    )
                )
            ).one()
            print(f"  provincias: {provincias[0]}   valores «provincia - cantón»: {provincias[1]}")

            print("\nLos ocho valores de provincia más frecuentes:")
            for valor, cuantos in (
                await conexion.execute(
                    text(
                        """
                        SELECT COALESCE(datos ->> 'provincia', '(sin provincia)') AS valor,
                               count(*) AS total
                        FROM registro
                        GROUP BY 1
                        ORDER BY 2 DESC
                        LIMIT 8
                        """
                    )
                )
            ).all():
                print(f"  {valor:<40} {cuantos:>8}")

        print("\nPalabras clave en el catálogo:")
        for fila in (
            await conexion.execute(
                text(
                    """
                    SELECT texto, activo, ultima_ingesta_en
                    FROM termino
                    ORDER BY texto
                    LIMIT 25
                    """
                )
            )
        ).all():
            print(f"  {fila[0]:<30} activo={fila[1]}  última ingesta={fila[2]}")

        politicas = (
            await conexion.execute(
                text("SELECT tipo, version, hash FROM politica_version ORDER BY tipo, version")
            )
        ).all()
        print("\nPolíticas publicadas:")
        for tipo, version, huella in politicas:
            print(f"  {tipo:<20} v{version}  {huella[:16]}…")
        if not politicas:
            print("  (ninguna) — los términos no están publicados")

        pendientes: int = (
            await conexion.execute(
                text("SELECT count(*) FROM usuario WHERE debe_aceptar_politica_version IS NOT NULL")
            )
        ).scalar_one()
        print(f"\nCuentas con aceptación pendiente: {pendientes}")

    await motor.dispose()


if __name__ == "__main__":
    asyncio.run(principal())
