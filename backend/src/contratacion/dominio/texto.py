"""Quitar tildes rápido, con el mismo resultado que el filtro carácter a carácter.

El patrón de siempre en este repositorio es::

    base = unicodedata.normalize("NFKD", texto)
    "".join(c for c in base if not unicodedata.combining(c))

Correcto, pero recorre el texto **en Python**, un carácter cada vez. Medido en «Propuestas para ti»
(79 ínfimas con su `texto_busqueda` y un perfil con decenas de palabras): 7.500 llamadas a `plegar`
y 550.000 caracteres por petición, unos 100 ms de CPU **dentro del bucle de eventos**. Mientras
tanto el proceso no atiende a nadie más: con 500 personas, ese es el techo de la pantalla.

`str.translate` hace lo mismo en C. La tabla es un `dict` que se rellena sola la primera vez que ve
cada carácter (`__missing__`), así que no hay que recorrer los 1,1 millones de puntos de Unicode al
importar el módulo y el resultado es **idéntico** al del filtro: se pregunta a la misma función,
`unicodedata.combining`, una vez por carácter distinto en vez de una vez por carácter leído.
"""

from __future__ import annotations

import re
import unicodedata


class _SinMarcas(dict[int, int | None]):
    """Tabla de `str.translate`: las marcas combinantes se borran, lo demás queda igual."""

    def __missing__(self, punto: int) -> int | None:
        valor = None if unicodedata.combining(chr(punto)) else punto
        self[punto] = valor
        return valor


_TABLA = _SinMarcas()


def sin_marcas(texto: str) -> str:
    """`texto` (ya en NFKD) sin marcas combinantes; igual que filtrar con `combining`."""
    if texto.isascii():
        # Ningún carácter ASCII es una marca combinante: no hay nada que quitar.
        return texto
    return texto.translate(_TABLA)


# --- Texto «doblemente codificado» ----------------------------------------- #
#
# Algunas entidades pegan en el portal texto UTF-8 que acaba leído como Latin-1/Windows-1252:
# «CONTRATACIÓN» llega como «CONTRATACIÃ\x93N» y «DÍA» como «DÃ\x8dA». Se repara por tramos: cada
# racha de caracteres de ese rango se vuelve a sus bytes y se lee como UTF-8; si no da UTF-8 válido,
# el tramo se deja como estaba (es un acento legítimo, no un error).

_CP1252_ALTOS = (
    "\u0152\u0153\u0160\u0161\u0178\u017d\u017e\u0192\u02c6\u02dc\u2013-\u203a\u20ac\u2122"
)
_SOSPECHOSO = re.compile(f"[\u00c2\u00c3\u00e2][\u0080-\u00bf{_CP1252_ALTOS}]")
_TRAMO = re.compile(f"[\u0080-\u00ff{_CP1252_ALTOS}]+")


def _a_bytes(tramo: str) -> bytes:
    salida = bytearray()
    for caracter in tramo:
        try:
            salida += caracter.encode("cp1252")
        except UnicodeEncodeError:
            if ord(caracter) > 0xFF:
                raise
            salida.append(ord(caracter))  # los huecos de cp1252 (0x81, 0x8d…) llegan tal cual
    return bytes(salida)


def _reparar_tramo(encontrado: re.Match[str]) -> str:
    tramo = encontrado.group(0)
    try:
        return _a_bytes(tramo).decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return tramo


def reparar_codificacion(texto: str) -> str:
    """«CONTRATACIÃ\x93N» → «CONTRATACIÓN». El texto sano sale igual (y sin coste: un `search`)."""
    if not texto or not _SOSPECHOSO.search(texto):
        return texto
    return _TRAMO.sub(_reparar_tramo, texto)
