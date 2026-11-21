"""Qué límite tiene una descarga del histórico en un archivo.

La descarga es la operación más cara del sistema y la única que **no se pagina**: lee todo lo que
cumpla los filtros y arma el libro en memoria. Hasta noviembre de 2026 eso se acotaba exigiendo una
fecha de publicación inicial dentro de los últimos tres meses, y el panel la ponía sola con el botón
«Excel de los últimos 3 meses».

El cliente lo reportó como fallo (QA ciclo 3) y tenía razón: el panel mostraba 281 ínfimas sin
filtro de fecha, el botón aplicaba un rango de publicación por su cuenta y el archivo traía 275. Las
seis que faltaban eran ínfimas publicadas antes del rango **que seguían abiertas** (su fecha límite
de proforma no había pasado). Un archivo que no coincide con la pantalla es peor que no tenerlo.

La regla ahora
--------------
- **La fecha de publicación es un filtro opcional** y nunca se pone sola. La descarga lleva
  exactamente los filtros de la pantalla, con la misma función de filtrado (`bd/consultas.py`).
- El coste se acota por **número de filas** (`TOPE_FILAS_PREDETERMINADO`, configurable con
  `EXPORT_ASYNC_UMBRAL_FILAS`): la consulta pide una fila de más y, si llega, se **rechaza** con el
  motivo. Nunca se recorta en silencio. Leer el tope de filas cuesta lo mismo con o sin fecha
  —la consulta va ordenada por el índice de fecha y con `LIMIT`—, así que la fecha obligatoria no
  protegía nada que el tope no proteja ya.
"""

from __future__ import annotations

from contratacion.dominio.errores import DatoInvalido

TOPE_FILAS_PREDETERMINADO = 20_000


def revisar_tope(filas: int, *, limite: int) -> None:
    """Rechaza la descarga si hay más filas que el tope. Nunca se entrega un archivo recortado."""
    if filas > limite:
        raise DatoInvalido(
            f"Con estos filtros hay más de {limite:,} contrataciones y el archivo se generaría "
            "demasiado grande. Acota con palabras clave, CPC, provincia o un rango de fechas y "
            "vuelve a intentarlo."
        )
