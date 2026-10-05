"""Compara el listado paginado de OCDS con la descarga masiva, registro a registro.

    .\\.venv\\Scripts\\python.exe scripts\\comparar_ocds_listado_masiva.py --fichero C:\\ocds.zip

POR QUÉ EXISTE. Las dos vías traen los mismos procedimientos con **formas distintas**: el listado
devuelve una fila plana con quince campos, y el fichero masivo devuelve el OCDS estándar, anidado
(`tender`, `awards`, `parties`, `planning`). Para sustituir una por otra hay que saber de dónde sale
cada columna del panel, y eso no se deduce leyendo la documentación del estándar: se comprueba
poniendo las dos filas del mismo procedimiento una al lado de la otra.

Además responde a la pregunta que decide si la sustitución es limpia: **¿están todos?** El fichero
de septiembre trae 4.634 procedimientos y el listado dice 4.798. Aquí se ve qué falta y de qué tipo
es, en lugar de dar por bueno un porcentaje.

No escribe nada: lee la base y el ZIP.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from zipfile import ZipFile

sys.path.insert(0, "src")

from sqlalchemy import text

from contratacion.infraestructura.adaptadores.salida.bd.sesion import cerrar_bd, obtener_motor

# Las claves que la tabla de mapeo de OCDS espera encontrar en el crudo: el contrato que tiene
# que cumplir la traducción del fichero masivo.
CLAVES_ESPERADAS = (
    "ocid",
    "date",
    "title",
    "internal_type",
    "description",
    "buyer",
    "region",
    "locality",
    "suppliers",
    "amount",
    "id",
    "year",
    "month",
    "method",
    "budget",
)

FILAS_DEL_LISTADO = """
    SELECT r.clave_natural, r.fecha_publicacion, r.crudo
    FROM registro r
    JOIN fuente f ON f.id = r.fuente_id
    WHERE f.codigo = 'OCDS' AND r.crudo ? 'ocid'
    ORDER BY r.fecha_publicacion DESC NULLS LAST
    LIMIT :limite
"""


def _leer_masiva(ruta: Path) -> dict[str, dict[str, Any]]:
    """Índice de la descarga masiva por `ocid`, que es la clave natural del proceso."""
    with ZipFile(ruta) as zipped:
        nombre = next(e.filename for e in zipped.infolist() if e.filename.endswith(".json"))
        paquetes = json.loads(zipped.read(nombre).decode("utf-8"))
    publicaciones = [r for paquete in paquetes for r in (paquete.get("releases") or [])]
    return {str(r.get("ocid")): r for r in publicaciones if r.get("ocid")}


def _direccion_del_comprador(publicacion: dict[str, Any]) -> dict[str, Any]:
    """La dirección de la entidad contratante, que es donde el listado saca provincia y cantón."""
    identificador = str((publicacion.get("buyer") or {}).get("id") or "")
    for parte in publicacion.get("parties") or []:
        if identificador and str(parte.get("id")) == identificador:
            return parte.get("address") or {}
    return {}


def _resumen_masiva(publicacion: dict[str, Any]) -> dict[str, Any]:
    """Los mismos conceptos que trae el listado, sacados de donde están en el estándar."""
    adjudicaciones = publicacion.get("awards") or []
    contrato = publicacion.get("tender") or {}
    planificacion = publicacion.get("planning") or {}
    proveedores = [
        str(proveedor.get("name"))
        for adjudicacion in adjudicaciones
        for proveedor in (adjudicacion.get("suppliers") or [])
        if proveedor.get("name")
    ]
    montos: list[float] = []
    for adjudicacion in adjudicaciones:
        valor = (adjudicacion.get("value") or {}).get("amount")
        if isinstance(valor, (int, float)) and not isinstance(valor, bool):
            montos.append(float(valor))
    fecha = str(publicacion.get("date") or "")
    return {
        "ocid": publicacion.get("ocid"),
        "id": publicacion.get("id"),
        "date": fecha,
        "title": contrato.get("title"),
        "internal_type": contrato.get("procurementMethodDetails"),
        "description": contrato.get("description"),
        "buyer": (publicacion.get("buyer") or {}).get("name"),
        "region": _direccion_del_comprador(publicacion).get("region"),
        "locality": _direccion_del_comprador(publicacion).get("locality"),
        "suppliers": ", ".join(proveedores),
        "amount": max((float(monto) for monto in montos), default=None),
        "method": contrato.get("procurementMethod"),
        "budget": (planificacion.get("budget") or {}).get("amount"),
        "year": fecha[:4],
        "month": fecha[5:7],
    }


async def main() -> int:
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument(
        "--fichero", type=Path, required=True, help="ZIP de la descarga masiva."
    )
    analizador.add_argument(
        "--limite", type=int, default=400, help="Filas del listado a contrastar."
    )
    analizador.add_argument("--muestras", type=int, default=4, help="Filas a imprimir en detalle.")
    opciones = analizador.parse_args()

    masiva = _leer_masiva(opciones.fichero)
    print(f"Descarga masiva: {len(masiva)} procedimientos en {opciones.fichero.name}")

    motor = obtener_motor()
    async with motor.connect() as conexion:
        filas = (
            (await conexion.execute(text(FILAS_DEL_LISTADO), {"limite": opciones.limite}))
            .mappings()
            .all()
        )
    await cerrar_bd()

    print(f"Listado (base de datos): {len(filas)} filas recientes con `ocid`")
    if not filas:
        print("  no hay filas de OCDS en la base; nada que comparar")
        return 1

    coinciden = [fila for fila in filas if str(fila["crudo"].get("ocid")) in masiva]
    faltan = [fila for fila in filas if str(fila["crudo"].get("ocid")) not in masiva]
    proporcion = len(coinciden) * 100 // len(filas)
    print(f"  presentes en la descarga masiva: {len(coinciden)} ({proporcion} %)")
    print(f"  no presentes:                    {len(faltan)}")
    for fila in faltan[:5]:
        crudo = fila["crudo"]
        print(
            f"    falta {crudo.get('ocid')} · tipo={crudo.get('internal_type')!r} · "
            f"fecha={fila['fecha_publicacion']:%Y-%m-%d}"
        )
    if faltan:
        tipos: dict[str, int] = {}
        for fila in faltan:
            clave = str(fila["crudo"].get("internal_type") or "(sin tipo)")
            tipos[clave] = tipos.get(clave, 0) + 1
        print("    por tipo de proceso:")
        for clave, veces in sorted(tipos.items(), key=lambda par: -par[1]):
            print(f"      {clave:<45} {veces}")

    print("\nComparación campo a campo (listado ← descarga masiva):")
    for fila in coinciden[: opciones.muestras]:
        listado = fila["crudo"]
        traducido = _resumen_masiva(masiva[str(listado.get("ocid"))])
        print(f"\n  ocid {listado.get('ocid')}")
        for clave in CLAVES_ESPERADAS:
            izq = listado.get(clave)
            der = traducido.get(clave)
            if isinstance(izq, str) and len(izq) > 70:
                izq = izq[:67] + "..."
            if isinstance(der, str) and len(der) > 70:
                der = der[:67] + "..."
            print(f"    {clave:<14} listado={izq!r:<74} masiva={der!r}")

    direcciones = [
        _direccion_del_comprador(publicacion) for publicacion in list(masiva.values())[:200]
    ]
    con_datos = next((d for d in direcciones if d), {})
    print(f"\nClaves de `parties[].address` en la muestra: {sorted(con_datos) or '(ninguna)'}")
    return 0


if __name__ == "__main__":
    sys.exit(__import__("asyncio").run(main()))
