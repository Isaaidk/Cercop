"""Puerto de escritura de los ítems con CPC.

El caso de uso que rellena los ítems necesita dos cosas del almacén: qué registros faltan y dónde
escribir lo que se leyó. Se declara aquí, y no se usa directamente `RepositorioIngesta`, para que la
lógica se pueda probar sin base de datos —que es la misma razón por la que existen los demás
puertos— y para que quede escrito qué necesita exactamente.

Es un puerto **apartado** del de la ingesta, aunque hoy lo implemente el mismo repositorio. Lo que
hace este caso de uso no es ingestar: no pide el listado, no decide claves naturales ni huellas, y
no toca el crudo. Comparte el almacén porque es donde viven los registros, no porque sea la misma
tarea.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol
from uuid import UUID


class RepositorioItems(Protocol):
    """Lectura de pendientes y escritura de ítems."""

    async def registros_sin_items(
        self, fuentes: Sequence[str], limite: int
    ) -> list[dict[str, Any]]:
        """Registros a los que todavía no se les ha leído la ficha, de esas fuentes.

        Cada fila trae al menos `id`, `fuente` y `enlace`. Las fuentes se reciben para no devolver
        nunca registros que no se puedan completar: uno de esos ocuparía un hueco de la tanda y
        gastaría la misma consulta en cada ciclo, sin llegar a resolverse.
        """
        ...

    async def contar_sin_items(self, fuentes: Sequence[str]) -> int:
        """Cuántos registros de esas fuentes siguen sin ficha leída.

        Es lo que permite decir cuánto **falta** de verdad. Sin esta cuenta, quien mira el registro
        del worker solo ve cómo se consumen las fichas de la tanda —«300 leídas, 0 pendientes»— y no
        puede saber si el relleno va por la mitad o acaba de empezar; y un aviso que no informa es
        un aviso que nadie mira.
        """
        ...

    async def guardar_items(
        self,
        registro_id: UUID,
        *,
        items: Sequence[Mapping[str, Any]],
        cpc_busqueda: str,
        cpc_codigos: Sequence[str],
    ) -> None:
        """Guarda los ítems ya normalizados y marca la ficha como leída.

        Marcar como leída una lista vacía es parte del contrato: «esta necesidad no publica detalle»
        y «todavía no se ha pedido» no pueden confundirse, o las necesidades sin detalle se
        reintentarían en cada tanda para siempre.
        """
        ...
