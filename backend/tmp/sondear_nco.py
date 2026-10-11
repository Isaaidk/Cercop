"""Prueba el listado de necesidades de la fuente NCO y enseña qué contesta de verdad.

El worker cierra los ciclos NCO como «parcial» con una sola petición y sin registros, y el único
aviso que deja es «La fuente de necesidades no respondió (límite de peticiones o corte de red)».
Esa frase es una **traducción**, no lo que dijo la fuente: el adaptador la escribe cuando la
petición no dio un JSON utilizable, y en ese camino caben un 429, un 500, una página de error con
HTML dentro y un tiempo de espera agotado. Desde el aviso, los cuatro son lo mismo.

Esto hace la misma petición que el worker —mismo endpoint, mismos parámetros, mismas cabeceras,
porque se importan del propio adaptador— y enseña el código, el tipo de contenido y el principio del
cuerpo. Con eso se sabe cuál de los cuatro es.

    python tmp/sondear_nco.py
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

ESPERA = 30.0


async def principal() -> None:
    print(f"Pidiendo: {ENDPOINT}?lot=1")
    print(f"Espera máxima: {ESPERA:.0f} s\n")

    async with httpx.AsyncClient(
        timeout=ESPERA, headers=CABECERAS, follow_redirects=True
    ) as cliente:
        inicio = time.monotonic()
        try:
            respuesta = await cliente.get(ENDPOINT, params={"lot": 1})
        except Exception as error:  # noqa: BLE001 - es una sonda: interesa cualquier fallo
            print(f"Fallo de red tras {time.monotonic() - inicio:.1f} s: "
                  f"{type(error).__name__}: {error}")
            return
        tardanza = time.monotonic() - inicio

        print(f"Estado:        {respuesta.status_code}")
        print(f"Tardanza:      {tardanza:.1f} s")
        print(f"Tipo:          {respuesta.headers.get('content-type')}")
        print(f"Comprimido:    {respuesta.headers.get('content-encoding') or 'no'}")
        print(f"Bytes:         {len(respuesta.content)} "
              f"({len(respuesta.content) / 1024 / 1024:.2f} MB, ya descomprimido)")
        if tardanza > 0:
            print(f"Velocidad:     {len(respuesta.content) / 1024 / tardanza:.0f} KB/s")
        print(f"Servidor:      {respuesta.headers.get('server')}")
        print(f"Redirección:   {respuesta.url}")
        print("\nTodas las cabeceras:")
        for nombre, valor in respuesta.headers.items():
            print(f"  {nombre}: {valor}")
        print(f"\nPrimeros 200 caracteres del cuerpo:\n{respuesta.text[:200]}")


if __name__ == "__main__":
    asyncio.run(principal())
