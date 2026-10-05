"""Lectura de la ficha de una necesidad NCO: la tabla de ítems con su CPC.

La fuente publica el detalle como **HTML de servidor**, no como JSON, así que aquí se extrae la
tabla «Detalle del objeto de compra» y se convierte en ítems. Comprobado contra el portal: la
estructura es estable (encabezado con `CPC`, una fila por ítem y seis celdas), y la descripción del
producto viene en una sola celda con saltos de línea dentro.

Se analiza con `html.parser` de la biblioteca estándar y no con una biblioteca de terceros: el
formato es rígido, esto se ejecuta en el servidor de producción y una dependencia más de análisis de
HTML no aporta nada que compense tenerla que mantener.

El analizador no busca «la primera tabla»: recoge **todas** y se queda con la que tiene un
encabezado `CPC`. La ficha lleva más tablas alrededor, y anclarse a la posición —una constante de
caracteres o un índice— se rompería el día que la fuente añadiera una sección arriba, sin ningún
error visible: la tabla correcta seguiría estando, solo que en otro sitio.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

from contratacion.dominio.cpc import ItemCpc

# Celdas mínimas de una fila de ítem: número, código, nombre del CPC, descripción, unidad y
# cantidad.
CELDAS_MINIMAS = 6

# Encabezado que identifica la tabla que interesa, normalizado como se compara.
ENCABEZADO_CPC = "cpc"

ESPACIOS = re.compile(r"\s+")

# El enlace de la ficha viene incrustado en el listado y sin comillas: `href=../NCO/NCORegistro-
# Detalle.cpe?&id=XXXX,&op=0`. Se busca `id=` precedido de `?` o `&` y se corta en la coma, que es
# donde la fuente termina el valor antes de añadir `&op=0`.
PATRON_TOKEN = re.compile(r"[?&]id=([^&,\s]+)")


class _Tablas(HTMLParser):
    """Recoge las tablas de una página como listas de filas de celdas de texto.

    Las tablas anidadas se ignoran: una celda puede contener una tabla propia y sus filas no son
    filas de ítem. Por eso solo se registran `tr` y `td` en el primer nivel.

    Un `<br/>` se convierte en un espacio y no en un salto: el resto del sistema guarda los textos
    con los espacios colapsados (es lo que hace `html_a_texto` con el objeto de compra), y aquí
    interesa lo mismo — que dos trozos de texto no queden pegados.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._nivel_tabla = 0
        self._celda: list[str] | None = None
        self._fila: list[str] | None = None
        self.tablas: list[list[list[str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag == "table":
            self._nivel_tabla += 1
            if self._nivel_tabla == 1:
                self.tablas.append([])
            return
        if self._nivel_tabla != 1:
            return
        if tag == "tr":
            self._cerrar_fila()
            self._fila = []
        elif tag in ("td", "th"):
            self._cerrar_celda()
            self._celda = []
        elif tag == "br" and self._celda is not None:
            self._celda.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag == "table":
            self._nivel_tabla = max(0, self._nivel_tabla - 1)
            return
        if self._nivel_tabla != 1:
            return
        if tag in ("td", "th"):
            self._cerrar_celda()
        elif tag == "tr":
            self._cerrar_fila()

    def handle_data(self, data: str) -> None:
        if self._celda is not None and self._nivel_tabla == 1:
            self._celda.append(data)

    def _cerrar_celda(self) -> None:
        """Añade la celda abierta a la fila.

        Se cierra también al empezar la siguiente: el HTML del portal es correcto hoy, pero una
        celda sin cerrar no puede llevarse por delante las filas siguientes.
        """
        if self._celda is None:
            return
        texto = ESPACIOS.sub(" ", "".join(self._celda)).strip()
        self._celda = None
        if self._fila is not None:
            self._fila.append(texto)

    def _cerrar_fila(self) -> None:
        self._cerrar_celda()
        if self._fila is None:
            return
        fila = self._fila
        self._fila = None
        if fila and self.tablas:
            self.tablas[-1].append(fila)


def _es_encabezado(fila: list[str]) -> bool:
    """¿Esta fila es el encabezado de la tabla de ítems?"""
    return any(celda.strip().lower() == ENCABEZADO_CPC for celda in fila)


def _item_de_fila(fila: list[str]) -> ItemCpc | None:
    """Convierte una fila en un ítem, o `None` si no tiene la forma de una.

    La descripción del producto ocupa de la cuarta celda hasta la antepenúltima: se toman así y no
    por posición fija porque es el único campo que puede partirse en varias celdas, y las dos
    últimas —unidad y cantidad— están ancladas al final.
    """
    if len(fila) < CELDAS_MINIMAS:
        return None
    numero, codigo, descripcion_cpc = fila[0].strip(), fila[1].strip(), fila[2].strip()
    if not codigo or not numero.isdigit():
        return None
    return ItemCpc(
        numero=int(numero),
        codigo=codigo,
        descripcion_cpc=descripcion_cpc,
        descripcion=" ".join(parte for parte in fila[3:-2] if parte).strip(),
        unidad=fila[-2].strip(),
        cantidad=fila[-1].strip(),
    )


def parsear_items(html: str) -> tuple[ItemCpc, ...]:
    """Ítems de la tabla «Detalle del objeto de compra».

    Devuelve una tupla vacía —y no un error— si no hay tabla o si ninguna fila es válida: hay
    necesidades que se publican sin detalle, y eso no puede impedir guardar la necesidad.
    """
    analizador = _Tablas()
    analizador.feed(html)
    analizador.close()

    for tabla in analizador.tablas:
        if not tabla or not _es_encabezado(tabla[0]):
            continue
        items = [item for fila in tabla[1:] if (item := _item_de_fila(fila)) is not None]
        return tuple(items)
    return ()


def token_de_enlace(enlace: str | None) -> str | None:
    """Identificador con el que la fuente abre la ficha de una necesidad.

    El listado publica el enlace al detalle dentro del campo `url`, y el mapeo lo guarda en
    `enlace`. De ahí sale el token que pide `NCORegistroDetalle.cpe`; no hay que inventar nada ni
    volver a pedir el listado.
    """
    if not enlace:
        return None
    coincidencia = PATRON_TOKEN.search(str(enlace))
    return coincidencia.group(1) if coincidencia else None
