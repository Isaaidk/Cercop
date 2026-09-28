"""Serialización segura a JSON.

RNF-13: ninguna respuesta puede contener `NaN` ni `Infinity`. No es un capricho de estilo: ninguno
de los dos existe en el estándar JSON, así que un cliente estricto falla al interpretar la respuesta
y el navegador la acepta pero la convierte de forma distinta según la biblioteca.

La solución no es «no generar valores no finitos» —una media de una lista vacía los produce sola—
sino convertirlos a `None`, que sí es un «no hay dato» honesto, en un único punto por el que pasa
todo lo que se envía o se guarda.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

# `float` tiene que estar aquí. Si falta, un número decimal no coincide con ningún tipo escalar y
# cae en la conversión final a texto: todos los montos de la API viajarían entre comillas y el
# frontend tendría que convertirlos de vuelta. Es exactamente el fallo que encontró la prueba
# `test_conserva_los_numeros_normales`.
TIPOS_ESCALARES = (str, int, float, bool, type(None))


def es_no_finito(valor: object) -> bool:
    """¿Es un número real no representable en JSON (`NaN`, `Infinity`, `-Infinity`)?"""
    return isinstance(valor, float) and not math.isfinite(valor)


def sanear(valor: Any) -> Any:
    """Devuelve el valor listo para JSON, sin valores no finitos y con los tipos convertibles.

    Es recursiva porque los datos de la fuente son JSON anidado: una lista de valores dentro de un
    objeto dentro de una lista.
    """
    if es_no_finito(valor):
        return None
    if isinstance(valor, TIPOS_ESCALARES):
        return valor
    if isinstance(valor, Decimal):
        return float(valor)
    if isinstance(valor, datetime | date):
        return valor.isoformat()
    if isinstance(valor, UUID):
        return str(valor)
    if isinstance(valor, Mapping):
        return {str(clave): sanear(contenido) for clave, contenido in valor.items()}
    if isinstance(valor, Sequence | set | frozenset):
        return [sanear(elemento) for elemento in valor]
    return str(valor)


def a_json(valor: Any) -> str:
    """Serializa sin permitir valores no finitos.

    `allow_nan=False` actúa de red de seguridad: si algo se escapara de `sanear`, aquí se convierte
    en un error visible en lugar de viajar en silencio hasta el cliente.
    """
    return json.dumps(
        sanear(valor),
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def de_json(texto: str) -> Any:
    """Reconstruye un valor guardado previamente con `a_json`."""
    return json.loads(texto)


def cuerpo_json(valor: Any) -> dict[str, Any]:
    """Prepara el diccionario de una respuesta HTTP.

    Existe porque `sanear` acepta cualquier estructura y por tanto devuelve `Any`, y devolver `Any`
    desde una función declarada `dict[str, Any]` obligaría a repetir la anotación en cada endpoint.
    Aquí se anota una vez.
    """
    resultado: dict[str, Any] = sanear(valor)
    return resultado
