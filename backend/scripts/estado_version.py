"""Versión de los datos: el número que sube cada vez que la ingesta escribe.

    .\\.venv\\Scripts\\python.exe scripts\\estado_version.py
    .\\.venv\\Scripts\\python.exe scripts\\estado_version.py --observar 60

Es exactamente el número que el panel consulta cada minuto (`GET /v1/ingestas/version`) para saber
si tiene algo nuevo que enseñar. Sirve para dos comprobaciones que no se pueden hacer de otra forma:

1. **Que la ingesta invalide.** Un contador clavado significa que el panel no se va a enterar de
   nada y que las páginas cacheadas seguirán sirviéndose hasta caducar por tiempo.
2. **Que invalide también al escribir los CPC.** Es el caso que se escapa: el CPC entra *después*
   de que cada fuente haya invalidado lo suyo, así que si aquí no sube, la necesidad aparece en
   pantalla sin su clasificación y parece que la ficha no se leyó.

No toca la base de datos: lee contadores del caché, que es justo lo que hace barata la pregunta.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

sys.path.insert(0, "src")

from contratacion.aplicacion.generaciones import leer_generacion
from contratacion.dominio.busqueda import GENERACION_GLOBAL
from contratacion.infraestructura.adaptadores.salida.cache.cliente import (
    cerrar_cache,
    obtener_cache,
)

FUENTES = (GENERACION_GLOBAL, "NCO", "OCDS")


async def _leer(cache: object) -> dict[str, int]:
    return {fuente: await leer_generacion(cache) for fuente in FUENTES}  # type: ignore[arg-type]


async def main() -> None:
    parser = argparse.ArgumentParser(description="Versión de los datos que ve el panel.")
    parser.add_argument(
        "--observar",
        type=int,
        default=0,
        metavar="SEGUNDOS",
        help="Vuelve a leer al cabo de estos segundos y dice si el número se movió.",
    )
    argumentos = parser.parse_args()

    cache = obtener_cache()
    try:
        antes = await _leer(cache)
        print()
        for fuente, valor in antes.items():
            print(f"  {fuente:<8} {valor}")
        print()

        if argumentos.observar > 0:
            print(f"  Observando {argumentos.observar} s…")
            time.sleep(argumentos.observar)
            despues = await _leer(cache)
            print()
            for fuente in FUENTES:
                if despues[fuente] != antes[fuente]:
                    print(f"  {fuente:<8} {antes[fuente]} → {despues[fuente]}  (cambió)")
                else:
                    print(f"  {fuente:<8} {despues[fuente]}  (igual)")
            print()
            if despues[GENERACION_GLOBAL] == antes[GENERACION_GLOBAL]:
                print("  AVISO: el contador global no se movió. Si la ingesta escribió en este")
                print("         intervalo, el panel no se refrescará solo.")
            print()
    finally:
        await cerrar_cache()


if __name__ == "__main__":
    asyncio.run(main())
