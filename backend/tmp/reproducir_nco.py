"""Reproduce el fallo de NCO: reutilizar la conexión después de que el servidor la haya cerrado.

El servidor del listado responde con esta cabecera:

    keep-alive: timeout=5, max=56

Es decir: **cierra la conexión si pasan cinco segundos sin usarla**, y admite 56 peticiones por
conexión. Detrás hay un Citrix NetScaler (se ve por la cookie `NSC_…` que reparte).

El worker pide el listado cada 150 segundos y mantiene el cliente HTTP entre ciclos, así que siempre
llega con una conexión que el servidor ya cerró. Esta sonda hace exactamente eso —pide, espera más de
cinco segundos y vuelve a pedir con el mismo cliente— para ver si el fallo se reproduce aquí.

Si se reproduce, la causa no es la IP ni la red: es **reutilizar una conexión que el otro extremo ya
cerró**, y se arregla en el código.

    python tmp/reproducir_nco.py
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

import httpx  # noqa: E402

from contratacion.infraestructura.adaptadores.salida.fuentes.nco import (  # noqa: E402
    CABECERAS,
    ENDPOINT,
)

ESPERAS = (0.0, 8.0, 8.0, 30.0)


async def principal() -> None:
    async with httpx.AsyncClient(timeout=30, headers=CABECERAS, follow_redirects=True) as cliente:
        for numero, espera in enumerate(ESPERAS, start=1):
            if espera:
                print(f"  … esperando {espera:.0f} s sin tocar la conexión")
                await asyncio.sleep(espera)

            inicio = time.monotonic()
            try:
                respuesta = await cliente.get(ENDPOINT, params={"lot": 1})
            except Exception as error:  # noqa: BLE001 - es una sonda
                print(
                    f"  petición {numero} tras {espera:>4.0f} s de espera: "
                    f"FALLO en {time.monotonic() - inicio:.1f} s · "
                    f"{type(error).__name__}: {error}"
                )
                continue
            print(
                f"  petición {numero} tras {espera:>4.0f} s de espera: "
                f"{respuesta.status_code} · {len(respuesta.content)} bytes · "
                f"{time.monotonic() - inicio:.1f} s"
            )


if __name__ == "__main__":
    asyncio.run(principal())
