"""Normalización de palabras clave.

Se hace en Python y no en la base de datos a propósito: la F1 decidió **no depender de extensiones**
de PostgreSQL, así que `unaccent` no está disponible. Como el vocabulario de términos lo escribe una
persona y es corto, normalizarlo en memoria es más simple y no ata el esquema a un proveedor.
"""

from __future__ import annotations

import re
import unicodedata

SEPARADOR_TERMINOS = re.compile(r"[,\n;]")
ESPACIOS = re.compile(r"\s+")

# La fuente oficial rechaza búsquedas de menos de tres caracteres y cada intento consumiría cuota
# del presupuesto, así que el mínimo se aplica antes de encolar cualquier término.
LONGITUD_MINIMA_TERMINO = 3


def sin_acentos(texto: str) -> str:
    """Quita los diacríticos conservando las letras base."""
    descompuesto = unicodedata.normalize("NFD", texto)
    return "".join(caracter for caracter in descompuesto if unicodedata.category(caracter) != "Mn")


def normalizar(texto: str | None) -> str:
    """Forma canónica de un texto para comparar: minúsculas, sin acentos, sin espacios sobrantes."""
    if not texto:
        return ""
    return ESPACIOS.sub(" ", sin_acentos(texto).lower()).strip()


def normalizar_termino(texto: str) -> str:
    """Clave única de un término del catálogo global.

    Garantiza que «Gestión», «gestion» y «GESTIÓN  » sean el mismo término y se ingestan una sola
    vez para todos los negocios.
    """
    return normalizar(texto)


def dividir_terminos(entrada: str | None) -> list[str]:
    """Divide una entrada de usuario en términos, descartando los que no aportan nada.

    Se exige un mínimo de tres caracteres porque la fuente oficial rechaza búsquedas más cortas y
    cada intento consumiría cuota del presupuesto.
    """
    if not entrada:
        return []
    vistos: dict[str, str] = {}
    for parte in SEPARADOR_TERMINOS.split(entrada):
        limpio = parte.strip()
        if len(limpio) < LONGITUD_MINIMA_TERMINO:
            continue
        vistos.setdefault(normalizar_termino(limpio), limpio)
    return list(vistos.values())
