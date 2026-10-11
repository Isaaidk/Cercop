"""Cuántas necesidades (NCO) tenemos guardadas, por día de publicación.

Es la otra mitad de la comprobación de `analizar_nco.py`. Aquella dice lo que **publica** la fuente;
esta, lo que tenemos **nosotros**. La diferencia entre las dos es lo que se ha perdido, y con NCO no
hay vuelta atrás: el listado solo publica lo vigente y no existe histórico de las cerradas.

Se ejecuta contra la base que diga `DATABASE_URL`.

    python tmp/nco_por_dia.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from sqlalchemy import text  # noqa: E402

from contratacion.infraestructura.adaptadores.salida.bd.sesion import (  # noqa: E402
    cerrar_bd,
    obtener_motor,
)

DIAS = 12

# La fecha se guarda en UTC; el día que le importa a quien mira el panel es el de Ecuador.
POR_DIA = """
SELECT (r.fecha_publicacion AT TIME ZONE 'America/Guayaquil')::date AS dia,
       count(*) AS cuantos
FROM registro r
JOIN fuente f ON f.id = r.fuente_id
WHERE f.codigo = 'NCO'
  AND r.fecha_publicacion >= now() - make_interval(days => :dias)
GROUP BY 1
"""


async def principal() -> None:
    motor = obtener_motor()
    try:
        async with motor.connect() as conexion:
            ahora: datetime = (await conexion.execute(text("SELECT now()"))).scalar_one()
            filas = (await conexion.execute(text(POR_DIA), {"dias": DIAS})).all()
            guardados = {fila[0]: fila[1] for fila in filas}

            hoy = ahora.date()
            print(f"Ahora: {ahora:%Y-%m-%d %H:%M} UTC\n")
            print("Necesidades (NCO) guardadas, por día de publicación:")
            total = 0
            for desplazamiento in range(DIAS):
                dia = hoy - timedelta(days=desplazamiento)
                cuantos = guardados.get(dia, 0)
                total += cuantos
                print(f"  {dia}  {cuantos:>5}")
            print(f"  {'— suma de los 12 días':<12} {total:>5}")

            ultima: datetime | None = (
                await conexion.execute(
                    text(
                        """
                        SELECT max(r.fecha_publicacion)
                        FROM registro r
                        JOIN fuente f ON f.id = r.fuente_id
                        WHERE f.codigo = 'NCO'
                        """
                    )
                )
            ).scalar_one()
            print(f"\nPublicación más reciente que tenemos: {ultima}")
    finally:
        await cerrar_bd()


if __name__ == "__main__":
    asyncio.run(principal())
