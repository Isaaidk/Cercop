"""Trae el listado de necesidades y lo mira por dentro: total, fechas y lo más reciente.

La sonda anterior (`sondear_nco.py`) solo comprobaba que la fuente contesta. Eso contesta a «¿está
viva?», que no es la pregunta. La pregunta es si el listado **trae las necesidades de estos días**, y
para eso hay que mirar dos campos y no el código de estado:

* `fecha_publicacion` — cuándo salió la necesidad.
* `fecha_limite_propuesta` — el plazo de proformas, que es lo que decide **cuándo desaparece** del
  listado. Una necesidad sale del listado en cuanto vence ese plazo, y la fuente no publica
  histórico: lo que no se capture a tiempo se pierde para siempre.

Por eso un listado con 1.800 filas puede estar «funcionando» y a la vez no traer ni una necesidad
de hoy.

    python tmp/analizar_nco.py
"""

from __future__ import annotations

import asyncio
import sys
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

import httpx  # noqa: E402

from contratacion.infraestructura.adaptadores.salida.fuentes.nco import (  # noqa: E402
    CABECERAS,
    ENDPOINT,
)

ESPERA = 60.0
DIAS_A_MIRAR = 10


def _dia(valor: Any) -> date | None:
    """El día de una fecha del listado, que viene como «2021-10-06 12:10:00»."""
    texto = str(valor or "").strip()
    if len(texto) >= 10:
        try:
            return datetime.strptime(texto[:10], "%Y-%m-%d").date()
        except ValueError:
            pass
    for formato in ("%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(texto[:10], formato).date()
        except ValueError:
            continue
    return None


async def principal() -> None:
    async with httpx.AsyncClient(
        timeout=ESPERA, headers=CABECERAS, follow_redirects=True
    ) as cliente:
        respuesta = await cliente.get(ENDPOINT, params={"lot": 1})

    respuesta.raise_for_status()
    datos = respuesta.json().get("data") or []
    print(f"Registros en el listado: {len(datos)}\n")

    publicacion = Counter(dia for dia in (_dia(f.get("fecha_publicacion")) for f in datos) if dia)
    limite = Counter(dia for dia in (_dia(f.get("fecha_limite_propuesta")) for f in datos) if dia)

    hoy = datetime.now(UTC).date()
    print(f"Publicación — últimos {DIAS_A_MIRAR} días:")
    for desplazamiento in range(DIAS_A_MIRAR):
        dia = hoy - timedelta(days=desplazamiento)
        print(f"  {dia}  {publicacion.get(dia, 0):>5}")
    print(
        f"  (anteriores a {hoy - timedelta(days=DIAS_A_MIRAR)}: "
        f"{sum(v for k, v in publicacion.items() if k < hoy - timedelta(days=DIAS_A_MIRAR))})"
    )

    print(f"\nPlazo de proformas — próximos {DIAS_A_MIRAR} días:")
    for desplazamiento in range(DIAS_A_MIRAR):
        dia = hoy + timedelta(days=desplazamiento)
        print(f"  {dia}  {limite.get(dia, 0):>5}")
    vencidos = sum(v for k, v in limite.items() if k < hoy)
    print(f"  (plazo ya vencido: {vencidos})")

    recientes = sorted(
        datos,
        key=lambda f: str(f.get("fecha_publicacion") or ""),
        reverse=True,
    )[:15]
    print("\nLas 15 publicaciones más recientes del listado:")
    print(f"  {'publicada':<20} {'plazo proformas':<20} {'código':<28} objeto")
    for fila in recientes:
        codigo = str(fila.get("codigo_contratacion") or "(sin código)")[:27]
        objeto = str(fila.get("objeto_contratacion") or "")[:40]
        print(
            f"  {str(fila.get('fecha_publicacion') or ''):<20} "
            f"{str(fila.get('fecha_limite_propuesta') or ''):<20} {codigo:<28} {objeto}"
        )


if __name__ == "__main__":
    asyncio.run(principal())
