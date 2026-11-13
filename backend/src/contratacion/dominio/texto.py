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
