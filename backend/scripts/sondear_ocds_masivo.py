"""Sonda de la **descarga masiva** de OCDS: ¿qué trae el fichero del mes y qué nos falta hoy?

    .\\.venv\\Scripts\\python.exe scripts\\sondear_ocds_masivo.py
    .\\.venv\\Scripts\\python.exe scripts\\sondear_ocds_masivo.py --anio 2026 --mes 9
    .\\.venv\\Scripts\\python.exe scripts\\sondear_ocds_masivo.py --fichero C:\\ruta\\ocds.zip

POR QUÉ EXISTE. La ingesta normal lee el listado paginado del portal: 10 filas por petición, 10.363
peticiones para el año 2026, y la fuente responde 429 cada cinco o seis. El portal publica además
los mismos procedimientos **en bloque**, por año y mes, en un ZIP (`/PLATAFORMA/download`).
Si el fichero trae lo mismo que el listado —o más—, el año entero son 12 peticiones en lugar de
10.363, y la pregunta deja de ser «cuántas horas» para ser «cuántos minutos».

Esta sonda responde a esa pregunta con medidas, no con impresiones:

1. **Cuántos procedimientos trae el fichero**, contrastado con `get-totals` del portal.
2. **Qué campos vienen con dato**, para saber si el fichero es el listado plano o el OCDS estándar.
3. **Si trae ítems con clasificación CPC**, que es lo que hoy obliga a una petición por necesidad en
   las ínfimas y que OCDS no daba por el listado.

No escribe en la base ni toca la ingesta: descarga (o usa un fichero local) y cuenta.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import httpx

BASE = "https://datosabiertos.compraspublicas.gob.ec/PLATAFORMA"
MESES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


def _descargar(anio: int, mes: int, destino: Path) -> Path:
    """Trae el ZIP del mes. `month=0` significa «todos los meses del año»."""
    url = f"{BASE}/download?type=json&year={anio}&month={mes}&method=all"
    print(f"Descargando {url}")
    with httpx.stream("GET", url, timeout=600.0, follow_redirects=True) as respuesta:
        respuesta.raise_for_status()
        with destino.open("wb") as salida:
            for bloque in respuesta.iter_bytes():
                salida.write(bloque)
    return destino


def _totales(anio: int, mes: int) -> int | None:
    """Cuántos procedimientos dice el portal que hay. Es el contraste del recuento del fichero."""
    try:
        respuesta = httpx.get(
            f"{BASE}/get-totals",
            params={"year": anio, "month": mes, "method": "all"},
            timeout=60.0,
            follow_redirects=True,
        )
        respuesta.raise_for_status()
        return int(respuesta.json().get("count"))
    except Exception as exc:  # noqa: BLE001 - la sonda no debe caerse por el contraste
        print(f"  (no se pudo preguntar los totales: {type(exc).__name__})")
        return None


def _campos_con_dato(registro: dict[str, Any]) -> set[str]:
    """Nombres de primer nivel que traen algo: dice si el fichero es el listado o el OCDS."""
    return {clave for clave, valor in registro.items() if valor not in (None, "", [], {})}


def _informe(anio: int, mes: int, ruta: Path, esperado: int | None) -> int:
    with ZipFile(ruta) as zipped:
        print("Contenido del ZIP:")
        for entrada in zipped.infolist():
            print(f"  {entrada.filename}  {entrada.file_size / 1024 / 1024:.1f} MB descomprimido")
        nombre = next(e.filename for e in zipped.infolist() if e.filename.endswith(".json"))
        crudo = zipped.read(nombre).decode("utf-8")

    inicio = time.monotonic()
    paquetes = json.loads(crudo)
    print(f"\nJSON leído en {time.monotonic() - inicio:.1f} s")

    publicaciones: list[dict[str, Any]] = []
    for paquete in paquetes:
        publicaciones.extend(paquete.get("releases") or [])

    ocids = {str(publicacion.get("ocid")) for publicacion in publicaciones}
    print(f"\nPublicaciones (releases): {len(publicaciones)} · procedimientos (ocid): {len(ocids)}")
    if esperado is not None:
        cuadra = "cuadra" if len(ocids) == esperado else "NO cuadra"
        print(f"  el portal dice {esperado} procedimientos para {anio}-{mes:02d}: {cuadra}")

    campos: Counter[str] = Counter()
    for publicacion in publicaciones:
        campos.update(_campos_con_dato(publicacion))
    print("\nCampos de primer nivel, por frecuencia:")
    for clave, veces in campos.most_common():
        print(f"  {clave:<28} {veces:>7}  ({veces * 100 // max(1, len(publicaciones))} %)")

    # Los itens de las adjudicaciones son lo que no da el listado: clasificación CPC, cantidad y
    # precios. Se cuentan por procedimiento, que es lo que decide si merece la pena.
    con_adjudicacion = 0
    con_items = 0
    con_cpc = 0
    items_totales = 0
    ejemplos_cpc: list[str] = []
    for publicacion in publicaciones:
        adjudicaciones = publicacion.get("awards") or []
        if adjudicaciones:
            con_adjudicacion += 1
        for adjudicacion in adjudicaciones:
            for item in adjudicacion.get("items") or []:
                items_totales += 1
                clasificacion = item.get("classification") or {}
                esquema = str(clasificacion.get("scheme", "")).upper()
                if esquema == "CPC" and clasificacion.get("id"):
                    con_cpc += 1
                    if len(ejemplos_cpc) < 5:
                        ejemplos_cpc.append(
                            f"{clasificacion.get('id')} {clasificacion.get('description', '')}"
                        )
            if adjudicacion.get("items"):
                con_items += 1

    print("\nÍtems y clasificación (lo que el listado paginado no trae):")
    print(f"  procedimientos con adjudicación: {con_adjudicacion}")
    print(f"  adjudicaciones con ítems:        {con_items}")
    print(f"  ítems en total:                  {items_totales}")
    print(f"  ítems con clasificación CPC:     {con_cpc}")
    for ejemplo in ejemplos_cpc:
        print(f"    p. ej. {ejemplo}")
    return 0


def main() -> int:
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument("--anio", type=int, default=2026)
    analizador.add_argument(
        "--mes", type=int, default=1, help="1-12, o 0 para el año entero en un solo fichero."
    )
    analizador.add_argument(
        "--fichero",
        type=Path,
        default=None,
        help="Usar un ZIP ya descargado en lugar de volver a pedirlo al portal.",
    )
    opciones = analizador.parse_args()

    ruta = opciones.fichero
    if ruta is None:
        etiqueta = MESES[opciones.mes - 1] if opciones.mes else "anio-completo"
        ruta = Path(__file__).resolve().parents[1] / "tmp" / f"ocds_{opciones.anio}_{etiqueta}.zip"
        ruta.parent.mkdir(exist_ok=True)
        descargado = _descargar(opciones.anio, opciones.mes, ruta)
        print(f"  {descargado.stat().st_size / 1024 / 1024:.2f} MB comprimidos en {descargado}")

    return _informe(opciones.anio, opciones.mes, ruta, _totales(opciones.anio, opciones.mes))


if __name__ == "__main__":
    sys.exit(main())
