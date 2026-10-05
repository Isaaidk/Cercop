"""Ítems del detalle de una necesidad: el CPC y lo que se compra.

El listado de necesidades publica el objeto de compra como **texto libre** —lo que escribió la
entidad— y nada más. El CPC, que es el vocabulario **normalizado** con el que el Estado clasifica lo
que compra, solo viaja en la ficha de la necesidad, y este módulo es donde se reduce a las dos
formas que el resto del sistema necesita: un texto para buscar y una lista de códigos.

La distinción no es cosmética, y es la razón de que esto exista. Buscar «lavado» en el objeto
encuentra cualquier necesidad que mencione la palabra, incluidas las que no tienen nada que ver con
lo que se busca; la misma búsqueda sobre la descripción del CPC encuentra solo lo que está
clasificado así. Por eso el texto de búsqueda de los ítems **no incluye** `descripcion`: esa es
precisamente la parte libre que el CPC viene a sustituir, y meterla aquí devolvería el problema que
se está resolviendo.

Un ítem tiene dos descripciones y conviene no confundirlas:

- `descripcion_cpc` — el nombre estándar del código («LAVADO Y ENGRASADO DE AUTOMOTORES»). Es
  vocabulario cerrado: la entidad lo elige de una lista.
- `descripcion` — lo que se compra, en palabras de la entidad («Lavado, engrasado y pulverizado de
  la Volqueta 5 kodiak chevrolet»). Es libre, no se indexa y sirve para que la persona reconozca el
  ítem cuando abre el detalle.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from contratacion.dominio.palabras import normalizar


@dataclass(frozen=True, slots=True)
class ItemCpc:
    """Una línea de la tabla «Detalle del objeto de compra» de la ficha de la necesidad.

    `cantidad` y `unidad` se guardan como texto y no como número a propósito: la fuente escribe
    «6.00» y «Global», y convertirlo aquí obligaría a decidir qué hacer con lo que no sea un número.
    El dato es informativo —el ítem no trae precio unitario, así que no hay importe que calcular— y
    guardarlo tal cual evita inventar.
    """

    codigo: str
    descripcion_cpc: str
    descripcion: str = ""
    unidad: str = ""
    cantidad: str = ""
    numero: int | None = None

    def como_diccionario(self) -> dict[str, Any]:
        """Forma serializable, que es la que se guarda en la base y la que ve el panel."""
        return {
            "numero": self.numero,
            "codigo": self.codigo,
            "descripcion_cpc": self.descripcion_cpc,
            "descripcion": self.descripcion,
            "unidad": self.unidad,
            "cantidad": self.cantidad,
        }


def items_desde_crudos(valores: Iterable[Any]) -> tuple[ItemCpc, ...]:
    """Reconstruye los ítems guardados, descartando lo que no tenga la forma esperada.

    Se lee de la base, así que puede venir de una versión anterior del formato. Un ítem ilegible se
    descarta en lugar de provocar un error: perder una línea del detalle es molesto, pero negarse a
    devolver la fila entera lo sería mucho más.
    """
    items: list[ItemCpc] = []
    for valor in valores:
        if not isinstance(valor, dict):
            continue
        codigo = str(valor.get("codigo") or "").strip()
        if not codigo:
            continue
        numero = valor.get("numero")
        items.append(
            ItemCpc(
                codigo=codigo,
                descripcion_cpc=str(valor.get("descripcion_cpc") or "").strip(),
                descripcion=str(valor.get("descripcion") or "").strip(),
                unidad=str(valor.get("unidad") or "").strip(),
                cantidad=str(valor.get("cantidad") or "").strip(),
                numero=numero if isinstance(numero, int) else None,
            )
        )
    return tuple(items)


def texto_de_cpc(items: Iterable[ItemCpc]) -> str:
    """Texto normalizado con el que se busca por CPC: los códigos y los nombres estándar.

    Va normalizado igual que `texto_busqueda` —minúsculas y sin acentos— porque el índice de texto
    completo usa la configuración `simple` de PostgreSQL: como el texto ya llega limpio, aplicar el
    analizador de un idioma solo añadiría sorpresas.

    Los valores **repetidos se descartan**: una necesidad con once líneas del mismo código repetiría
    el mismo par once veces, y el índice guarda lexemas, así que solo engordaría la columna.
    """
    partes: list[str] = []
    for item in items:
        for valor in (item.codigo, item.descripcion_cpc):
            limpio = normalizar(valor)
            if limpio:
                partes.append(limpio)
    return " ".join(dict.fromkeys(partes))


def codigos_de(items: Iterable[ItemCpc]) -> list[str]:
    """Códigos distintos, ordenados. Es lo que permite filtrar por igualdad exacta y contarlos."""
    return sorted({item.codigo for item in items if item.codigo})


def resumen_cpc(items: Iterable[ItemCpc]) -> str:
    """«871410032 LAVADO Y ENGRASADO DE AUTOMOTORES | 4911400111 PARTES, PIEZAS...».

    Es la forma legible que se muestra en la tabla y se escribe en la hoja de Excel. Un código
    repetido aparece **una sola vez**: once líneas de la misma volqueta comparten el mismo CPC, y
    repetirlo once veces no añade información y hace ilegible la celda.
    """
    vistos: dict[tuple[str, str], None] = {}
    for item in items:
        vistos.setdefault((item.codigo, item.descripcion_cpc), None)
    return " | ".join(f"{codigo} {nombre}".strip() for codigo, nombre in vistos)
