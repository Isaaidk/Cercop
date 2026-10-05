"""Puerto de las palabras clave de CPC que vigila una empresa.

Se parece al puerto de las palabras clave —una lista que el negocio mantiene y que el panel usa como
filtro— y no se parece en lo esencial: **esto no dispara nada**. Un término de `termino` se guarda
en un catálogo global y hace que el `worker` vaya a consultar la fuente oficial; un término de CPC
solo acota un histórico que ya está ingestado. De ahí que aquí no haya catálogo compartido ni cola:
la lista es de cada negocio, y la clave única es por negocio.

El texto se guarda **como lo escribió la persona** y se compara por su forma normalizada. Es la
misma distinción que en la búsqueda: la pantalla enseña lo que se reconoce —«LAVADO»— y la consulta
compara lo que significa —«lavado»—. Guardar solo la forma normalizada ahorraría una columna y haría
que las fichas aparecieran en minúsculas y sin acentos, que es como no las escribió nadie.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ClaveCpc:
    """Un término de CPC guardado por una empresa."""

    id: UUID
    texto: str
    creado_en: datetime

    def como_diccionario(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "texto": self.texto,
            "creado_en": self.creado_en.isoformat(),
        }


class RepositorioCpc(Protocol):
    """La lista de términos de CPC de una empresa."""

    async def listar(self, *, negocio_id: UUID) -> tuple[ClaveCpc, ...]:
        """Los términos guardados, del más antiguo al más nuevo.

        El orden es el de alta y no el alfabético: la lista se lee como se fue construyendo, y
        reordenarla sola haría que una ficha «se moviera» después de añadir otra.
        """
        ...

    async def agregar(
        self,
        *,
        negocio_id: UUID,
        texto: str,
        texto_normalizado: str,
        creado_por: UUID | None,
        momento: datetime,
    ) -> bool:
        """Guarda el término y dice si lo insertó.

        Devuelve `False` cuando ya estaba —lo garantiza la clave única por negocio y forma
        normalizada—, y eso no es un error: es la respuesta a «añade esto», que a veces ya está. Se
        informa en lugar de callarlo porque el recuento que se le enseña a la persona tiene que
        coincidir con lo que se guardó.
        """
        ...

    async def quitar(self, *, negocio_id: UUID, texto_normalizado: str) -> bool:
        """Borra el término. `False` si no estaba: quitarlo dos veces no es un fallo."""
        ...

    async def limpiar(self, *, negocio_id: UUID) -> int:
        """Vacía la lista y devuelve cuántos había. Cero no es un error."""
        ...
