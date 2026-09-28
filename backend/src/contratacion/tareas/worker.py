"""Proceso `worker`: la ingesta automática.

Es el segundo punto de entrada del monolito modular y el que **acumula el activo del producto**. Se
mantiene separado del API por dos razones:

1. Ninguna petición de un usuario debe llegar a la fuente oficial. El único que habla con el SERCOP
   es este proceso, con su presupuesto de peticiones.
2. La ingesta puede tardar: si viviera dentro del API, bloquearía la atención a los usuarios.

Ejecución:

    # Bucle continuo (producción)
    python -m contratacion.tareas.worker

    # Un solo ciclo (pruebas, despliegues con cron externo)
    python -m contratacion.tareas.worker --una-vez
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time

from contratacion.infraestructura.adaptadores.salida.bd.ingesta import RepositorioIngesta
from contratacion.infraestructura.adaptadores.salida.bd.sesion import cerrar_bd, obtener_motor
from contratacion.infraestructura.adaptadores.salida.cache.cliente import (
    cerrar_cache,
    obtener_cache,
)
from contratacion.infraestructura.config.ajustes import obtener_ajustes
from contratacion.tareas.planificador import ejecutar_todos

registro = logging.getLogger("contratacion.worker")

ESPERA_MINIMA_SEG = 5.0


async def ejecutar_un_ciclo() -> int:
    """Ejecuta un ciclo completo y devuelve el código de salida."""
    ajustes = obtener_ajustes()
    repositorio = RepositorioIngesta(obtener_motor())

    try:
        resultados = await ejecutar_todos(
            repositorio,
            obtener_cache(),
            intervalo_min=ajustes.intervalo_ingesta_min,
            ventana_solape_ciclos=ajustes.ventana_solape_ciclos,
            presupuesto_peticiones=ajustes.presupuesto_peticiones_ciclo,
        )
    finally:
        await cerrar_cache()
        await cerrar_bd()

    if not resultados:
        registro.warning("Ninguna fuente se ingestó en este ciclo.")
        return 0
    return 1 if all(resultado.estado == "error" for resultado in resultados) else 0


async def bucle() -> int:
    """Ejecuta ciclos indefinidamente, espaciados por el intervalo configurado."""
    ajustes = obtener_ajustes()
    intervalo_seg = max(60, ajustes.intervalo_ingesta_min * 60)
    registro.info("Worker iniciado. Intervalo: %s min.", ajustes.intervalo_ingesta_min)

    while True:
        inicio = time.monotonic()
        try:
            await ejecutar_un_ciclo()
        except Exception:  # noqa: BLE001 - el bucle nunca debe morir por un ciclo fallido
            registro.exception("El ciclo falló; se continuará con el siguiente.")

        transcurrido = time.monotonic() - inicio
        espera = max(ESPERA_MINIMA_SEG, intervalo_seg - transcurrido)
        registro.info("Siguiente ciclo en %.0f s.", espera)
        await asyncio.sleep(espera)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Worker de ingesta de contratación pública.")
    parser.add_argument(
        "--una-vez",
        action="store_true",
        help="Ejecuta un único ciclo y termina (útil para cron externo o para probar).",
    )
    argumentos = parser.parse_args(argv)

    logging.basicConfig(
        level=obtener_ajustes().log_nivel.upper(),
        format="%(asctime)s %(levelname)-5s %(name)s %(message)s",
    )

    try:
        if argumentos.una_vez:
            return asyncio.run(ejecutar_un_ciclo())
        return asyncio.run(bucle())
    except KeyboardInterrupt:
        registro.info("Worker detenido por el usuario.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
