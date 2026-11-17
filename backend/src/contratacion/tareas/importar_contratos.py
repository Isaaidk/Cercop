"""Importación mensual de contratos adjudicados por RUC (ver `fuentes/contratos_ocp.py`).

    python -m contratacion.tareas.importar_contratos           # importa ya
    python -m contratacion.tareas.importar_contratos --si-toca # solo si la última tiene >30 días

Corre en un **proceso aparte** que lanza el worker: lee ~400 MB comprimidos y retiene unos cientos
de MB mientras agrupa; al terminar el proceso, esa memoria vuelve al sistema. Dentro del worker,
Python se quedaría con ella todo el mes (y Railway cobra la RAM reservada).

Si falla la descarga de cualquier año, o el resultado es mucho menor que el anterior (archivo
truncado), no se toca lo que ya hay.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from contratacion.infraestructura.adaptadores.salida.bd.contratos import RepositorioContratos
from contratacion.infraestructura.adaptadores.salida.bd.sesion import cerrar_bd, obtener_motor
from contratacion.infraestructura.adaptadores.salida.fuentes.contratos_ocp import (
    URL_ANIO,
    Acumulado,
    leer_anio,
)

registro = logging.getLogger("contratacion.importar_contratos")

ANIOS = 3
CADA = timedelta(days=30)
_TIMEOUT = httpx.Timeout(120.0, connect=20.0)


def toca(ultima: datetime | None, ahora: datetime | None = None) -> bool:
    return ultima is None or (ahora or datetime.now(UTC)) - ultima >= CADA


async def _bajar(cliente: httpx.AsyncClient, anio: int, destino: Path) -> None:
    async with cliente.stream("GET", URL_ANIO.format(anio=anio)) as respuesta:
        respuesta.raise_for_status()
        with destino.open("wb") as archivo:
            async for trozo in respuesta.aiter_bytes(1 << 20):
                archivo.write(trozo)


async def importar(*, solo_si_toca: bool = False) -> int:
    repositorio = RepositorioContratos(obtener_motor())
    if solo_si_toca and not toca(await repositorio.ultima_importacion()):
        return 0
    # Sin bloqueo de asesoría: su conexión quedaba ociosa el minuto largo de la descarga y el
    # servidor la cerraba. El worker ya impide lanzar dos a la vez, y el reemplazo es una sola
    # transacción: dos importaciones a mano solo harían el trabajo dos veces.
    inicio = time.monotonic()
    actual = datetime.now(UTC).year
    anios = [actual - n for n in range(ANIOS)]
    acumulado = Acumulado()
    async with httpx.AsyncClient(
        timeout=_TIMEOUT, follow_redirects=True, headers={"User-Agent": "CercoApp"}
    ) as cliente:
        for anio in anios:
            with tempfile.TemporaryDirectory() as carpeta:
                ruta = Path(carpeta) / f"{anio}.csv.tar.gz"
                await _bajar(cliente, anio, ruta)
                with ruta.open("rb") as archivo:
                    leidas = await asyncio.to_thread(leer_anio, archivo, acumulado, anio)
            registro.info("Contratos %s: %s adjudicaciones leídas.", anio, leidas)

    anterior = await repositorio.proveedores_importados()
    nuevos = len(acumulado.proveedores)
    if anterior and nuevos < anterior // 2:
        registro.error(
            "Importación descartada: %s proveedores frente a %s de la anterior.",
            nuevos,
            anterior,
        )
        return 1

    proveedores = []
    usados: set[str] = set()  # solo se guardan los nombres de los CPC que algún RUC muestra
    for ruc, proveedor in acumulado.proveedores.items():
        resumen = proveedor.resumen()
        usados.update(str(c) for c, _ in resumen["cpc"])
        usados.update(str(e[3]) for e in resumen["experiencia"] if e[3])
        proveedores.append((ruc, json.dumps(resumen, ensure_ascii=False, separators=(",", ":"))))
    await repositorio.reemplazar(
        proveedores=proveedores,
        cpc=sorted((c, d) for c, d in acumulado.cpc.items() if c in usados),
        entidades=[(i, n) for n, i in acumulado.entidades.items()],
        anios=",".join(str(a) for a in sorted(anios)),
    )
    registro.info(
        "Contratos importados: %s proveedores, %s CPC, %s entidades en %.0f s.",
        nuevos,
        len(usados),
        len(acumulado.entidades),
        time.monotonic() - inicio,
    )
    return 0


async def _principal(solo_si_toca: bool) -> int:
    try:
        return await importar(solo_si_toca=solo_si_toca)
    finally:
        await cerrar_bd()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Importa los contratos adjudicados por RUC.")
    parser.add_argument("--si-toca", action="store_true", help="Solo si la última tiene >30 días.")
    argumentos = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return asyncio.run(_principal(argumentos.si_toca))


if __name__ == "__main__":
    sys.exit(main())
