"""Una sola consulta para muchas peticiones idénticas que llegan a la vez («single flight»).

El caché de resultados, estadísticas y catálogos tiene la generación en la clave. Cuando un ciclo
de ingesta la sube, **todas** las claves dejan de encontrarse a la vez, y las primeras personas que
abren el panel después piden exactamente lo mismo: el catálogo de los desplegables y las gráficas
sin filtros. Sin esto, cada una lanzaba su propia consulta a la base. Con 500 personas conectadas,
un cambio de generación ponía decenas de recuentos idénticos sobre el histórico a competir por las
20 conexiones del proceso, justo cuando el caché no puede ayudar.

Aquí la primera petición calcula y las que llegan mientras tanto con **la misma clave** esperan su
resultado. Nada se recuerda después: en cuanto termina, la clave se olvida y lo siguiente va al
caché de siempre. Por eso no puede servir datos viejos.

**Aislamiento**: solo se usa con claves de caché que ya incluyen todo lo que decide la respuesta
—la generación y los filtros, con las fuentes que la persona puede ver— y para datos del plano
compartido (el histórico público), nunca para datos de una empresa. Dos peticiones con la misma
clave reciben, por construcción, la misma respuesta que habrían recibido por separado.

El cálculo corre en su propia tarea: si quien lo empezó se va (cierra la pestaña), los demás siguen
esperando el resultado en lugar de recibir una cancelación que no es suya.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

_EN_CURSO: dict[tuple[int, str], asyncio.Future[Any]] = {}


def _olvidar(llave: tuple[int, str], tarea: asyncio.Future[Any]) -> None:
    if _EN_CURSO.get(llave) is tarea:
        del _EN_CURSO[llave]
    # Se lee el resultado para que una excepción que nadie esperó no acabe en el registro como
    # «Task exception was never retrieved».
    if not tarea.cancelled():
        tarea.exception()


async def una_vez[T](clave: str, calcular: Callable[[], Awaitable[T]]) -> T:
    """El resultado de `calcular()`, compartido con quien pida la misma `clave` a la vez."""
    bucle = asyncio.get_running_loop()
    llave = (id(bucle), clave)
    tarea = _EN_CURSO.get(llave)
    if tarea is None:
        tarea = asyncio.ensure_future(calcular())
        _EN_CURSO[llave] = tarea
        tarea.add_done_callback(lambda hecha: _olvidar(llave, hecha))
    resultado: T = await asyncio.shield(tarea)
    return resultado


def en_curso() -> int:
    """Cuántos cálculos compartidos hay ahora mismo (para pruebas y diagnóstico)."""
    return len(_EN_CURSO)
