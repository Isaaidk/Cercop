"""Títulos de proforma únicos dentro de la empresa.

El cliente lo pidió así: cada proforma lleva un título referente a su ínfima y no puede repetirse,
porque en «Mis ofertas» y en los PDF enviados el título es lo que distingue una de otra. Dos títulos
se consideran el mismo si solo cambian mayúsculas, tildes o espacios: «Proforma — Impresoras» y
«proforma - impresoras» se confundirían igual a la vista.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

TOPE_TITULO = 300
_GUIONES = re.compile(r"[\u2010-\u2015\u2212]")
_SUFIJO = re.compile(r"\s*\((\d{1,4})\)\s*$")


def normalizar_titulo(titulo: str) -> str:
    """La forma con la que se comparan dos títulos: sin tildes, en minúsculas, un espacio."""
    base = unicodedata.normalize("NFKD", _GUIONES.sub("-", str(titulo or "")))
    sin_tilde = "".join(c for c in base if not unicodedata.combining(c))
    return " ".join(sin_tilde.lower().split()).strip(" .")


def titulo_repetido(titulo: str, existentes: Iterable[str]) -> bool:
    clave = normalizar_titulo(titulo)
    return bool(clave) and any(normalizar_titulo(otro) == clave for otro in existentes)


def titulo_libre(titulo: str, existentes: Iterable[str]) -> str:
    """El mismo título si nadie lo usa; si no, con «(2)», «(3)»… al final, el primero libre."""
    usados = {normalizar_titulo(otro) for otro in existentes}
    limpio = " ".join(str(titulo or "").split())[:TOPE_TITULO]
    if normalizar_titulo(limpio) not in usados:
        return limpio
    raiz = _SUFIJO.sub("", limpio)
    for numero in range(2, 10_000):
        sufijo = f" ({numero})"
        candidato = f"{raiz[: TOPE_TITULO - len(sufijo)]}{sufijo}"
        if normalizar_titulo(candidato) not in usados:
            return candidato
    return limpio
