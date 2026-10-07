"""Las claves que se extraen de `datos` para poder filtrar y agrupar sin leerlo.

Por qué existe este módulo
--------------------------
Hay **dos** sitios que tienen que decir exactamente lo mismo: la ingesta, que escribe la clave en su
columna al guardar cada registro, y las consultas, que comparan contra esa columna al filtrar y
agrupan por ella al dibujar las gráficas. Si las dos reglas se separan —una que quita tildes y otra
que se olvida, una que recorta los espacios y otra que no— el síntoma es de los peores: unas filas
se encuentran y otras no, sin ningún error y sin ninguna fila de más. Por eso la regla vive aquí,
una sola vez, y se llama desde los dos lados.

Antes esto se resolvía normalizando **en cada consulta** (`lower(translate(...))` sobre `datos`). Y
funcionaba, pero costaba dos cosas:

- Obligaba a leer y descomprimir el `jsonb` de cada fila. Son unos 2 KB por fila, así que recorrer
  las 110.000 del histórico es descomprimir 180 MB de `TOAST`: medido, **20 s por reparto**.
- Hacía imposible que el planificador usara un índice: la expresión cuelga de `datos`, que no está
  en ningún índice, y un índice sobre la expresión no sirve para un recuento —el planificador lo usa
  visitando el montón fila a fila, que es exactamente el trabajo que se quería evitar—.

La decisión, entonces: la normalización se hace **una vez, al escribir**, y lo que se guarda es la
clave ya lista para comparar. Es la misma que ya se había tomado con `texto_busqueda` y
`cpc_busqueda`, que también se calculan al guardar y no al consultar.

Qué se guarda
-------------
- **`provincia`**: la provincia, sin el cantón, en minúsculas y sin tildes. El cantón se descarta
  —«pichincha»— porque es lo que el mapa y el desplegable eligen, y agrupar por «provincia - cantón»
  partiría una provincia en decenas de barras.
- **`tipo_proceso`**: el texto tal y como lo publica la fuente, sin espacios de sobra, y
  «sin clasificar» cuando la fuente no lo trae. Aquí **no** se normalizan tildes ni mayúsculas: el
  filtro compara contra el texto publicado y la clave que devuelve un reparto tiene que poder
  devolverse tal cual al filtro al pulsar una barra.

Cuando el dato no viene, las dos claves tienen un valor —«sin provincia» y «sin clasificar»— en
lugar de quedar en nulo. No es un detalle: así la columna puede ser `NOT NULL`, el reparto tiene su
barra para lo que no se sabe ubicar, y esa barra **encuentra** sus filas al pulsarla. Antes, pulsar
«sin clasificar» en el reparto devolvía cero: el reparto lo contaba con `COALESCE`, pero el filtro
comparaba contra el texto crudo de `datos`, que en esas filas está vacío.
"""

from __future__ import annotations

# Tabla de tildes a quitar. Se escribe entera y no con `unicodedata` porque los caracteres que
# aparecen en nombres de lugares del Ecuador son pocos y conocidos, y una tabla explícita se puede
# comparar a simple vista con la del SQL de abajo.
_TILDES = str.maketrans("áéíóúüñÁÉÍÓÚÜÑ", "aeiouunAEIOUUN")

# La misma tabla, en la forma que necesita `translate` en SQL. Las dos tienen que coincidir carácter
# a carácter: si la de Python quitara algo que la de SQL no quita, la misma provincia se guardaría
# con dos claves distintas y solo una de las dos formas se encontraría.
PROVINCIA_NORMALIZADA = (
    "lower(translate(COALESCE({columna}, ''), 'áéíóúüñÁÉÍÓÚÜÑ', 'aeiouunAEIOUUN'))"
)

# La misma expresión, aplicada a cualquier columna de texto. Se reutiliza en lugar de escribir otra
# igual a propósito: dos expresiones que **deben** coincidir acaban separándose en el primer
# arreglo, y el síntoma sería un filtro que encuentra unas filas con tilde y otras no.
NORMALIZADO = PROVINCIA_NORMALIZADA

# Las claves que se usan cuando la fuente no publica el dato.
SIN_PROVINCIA = "sin provincia"
SIN_CLASIFICAR = "sin clasificar"


def normalizar_ubicacion(valor: str | None) -> str:
    """Minúsculas y sin tildes, igual que la expresión SQL de `PROVINCIA_NORMALIZADA`.

    Las dos formas tienen que coincidir carácter a carácter: si la de aquí quitara algo que la de
    SQL no quita, el filtro dejaría de encontrar resultados y el fallo aparecería solo con las
    provincias cuyo nombre lleva tilde, que son siete de veinticuatro.
    """
    return (valor or "").translate(_TILDES).strip().lower()


def clave_provincia(valor: str | None) -> str:
    """La clave de una provincia, venga del dato que se guarda o del filtro que se escribe.

    Se llama desde los dos lados **a propósito**, y esa es toda la garantía de que coincidan.

    Se queda con la parte de antes del guion porque la fuente publica el valor como «PROVINCIA -
    CANTÓN» y lo que se elige en el panel es la provincia: agrupar por el valor completo partiría
    Pichincha en una barra por cantón. Un valor que ya venga sin guion —que es como lo manda el
    mapa— pasa intacto.
    """
    sin_canton = (valor or "").split("-")[0]
    return normalizar_ubicacion(sin_canton) or SIN_PROVINCIA


def clave_tipo_proceso(valor: str | None) -> str:
    """La clave de un tipo de proceso: el texto publicado, sin espacios de sobra.

    No se normalizan tildes ni mayúsculas porque esta clave viaja **de vuelta**: el reparto
    devuelve «Subasta Inversa Electrónica» y al pulsar esa barra ese mismo texto se envía como
    filtro. Si aquí se normalizara, habría que normalizar también en la consulta y en el panel, y
    tres normalizaciones distintas acabarían en barras que no encuentran nada al pulsarlas.
    """
    return (valor or "").strip() or SIN_CLASIFICAR
