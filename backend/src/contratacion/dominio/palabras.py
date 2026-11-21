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


# Lo que separa palabras al buscar: todo lo que no sea letra ASCII o dígito una vez quitadas las
# tildes. Es la misma regla con la que el índice de texto parte el contenido (migración 0049):
# «llantas/neumaticos», «equipos.computo» o «“adquisicion» eran **un solo** token para PostgreSQL y
# ninguna palabra clave los alcanzaba.
NO_PALABRA = re.compile(r"[^a-z0-9]+")

# Una raíz más corta que esto ya no dice qué se busca («mes» encontraría «mesa» y «meseta»): por
# debajo se busca la palabra tal cual.
LARGO_MINIMO_RAIZ = 4
# Consonantes tras las que el plural en español añade «-es»: «motor-es», «reparacion-es»,
# «util-es», «pan-es», «red-es», «reloj-es», «ley-es».
_PLURAL_EN_ES = frozenset("rlndjy")


def texto_indexable(texto: str | None) -> str:
    """El texto como lo parte el índice: normalizado y con cualquier signo convertido en espacio."""
    return NO_PALABRA.sub(" ", normalizar(texto)).strip()


def raices(palabra: str) -> tuple[str, ...]:
    """Prefijos con los que una palabra (ya normalizada) encuentra su singular y su plural.

    La búsqueda es por **prefijo** (`servicio:*`), así que el singular ya encontraba el plural; lo
    que fallaba era al revés: quien vigila «servicios» o «mantenimientos» no veía «servicio de…» ni
    «mantenimiento preventivo». Se quita la marca de plural más simple del español, sin diccionario
    ni dependencias:

    - «servicios» → «servicio», «computadoras» → «computadora» (vocal + s);
    - «motores» → «motor», «reparaciones» → «reparacion» (consonante + es);
    - «luces» ↔ «luz» (z → ces), con las dos formas.

    Si la raíz quedara por debajo de `LARGO_MINIMO_RAIZ` se deja la palabra tal cual: ensanchar
    «mes» a «me» traería medio diccionario. Los números no se tocan.
    """
    if not palabra or palabra.isdigit() or len(palabra) <= LARGO_MINIMO_RAIZ - 1:
        return (palabra,)
    if palabra.endswith("ces") and len(palabra) - 3 >= LARGO_MINIMO_RAIZ - 1:
        return (palabra[:-3] + "z", palabra)
    if palabra.endswith("z"):
        return (palabra, palabra[:-1] + "ces")
    if (
        palabra.endswith("es")
        and len(palabra) - 2 >= LARGO_MINIMO_RAIZ
        and palabra[-3] in _PLURAL_EN_ES
    ):
        return (palabra[:-2],)
    if palabra.endswith("s") and palabra[-2] in "aeiou" and len(palabra) - 1 >= LARGO_MINIMO_RAIZ:
        return (palabra[:-1],)
    return (palabra,)


def coincide_raiz(palabra_texto: str, palabra_buscada: str) -> bool:
    """¿La palabra del texto empieza por alguna raíz de la buscada?"""
    return any(palabra_texto.startswith(raiz) for raiz in raices(palabra_buscada))


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
