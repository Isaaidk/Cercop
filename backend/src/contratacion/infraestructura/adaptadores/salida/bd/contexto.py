"""Contexto de negocio por transacción.

Las políticas de RLS comparan `negocio_id` con `current_setting('app.negocio_id', true)::uuid`. Si
el contexto no está definido, esa expresión devuelve `NULL`, la comparación resulta `NULL` y **no se
devuelve ninguna fila**: denegar es el comportamiento por defecto, que es la postura correcta para
un sistema multi-inquilino.

Dos detalles que hay que respetar o el aislamiento deja de funcionar sin que nada falle:

1. **`SET LOCAL` solo vive dentro de una transacción.** Fuera de ella, la orden se aplica y se
   revierte de inmediato, con lo que las consultas siguientes se ejecutarían **sin contexto** y
   devolverían cero filas. Por eso el contexto se establece siempre a través de `contexto_negocio`,
   que abre una transacción explícita y la mantiene abierta mientras dure el bloque.
2. **`SET LOCAL` no admite parámetros.** Hay que usar `set_config('app.negocio_id', $1, true)`, que
   sí los admite y hace exactamente lo mismo.

El identificador del negocio llega desde el token verificado, nunca desde la petición (R-04).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

registro = logging.getLogger(__name__)

PARAMETRO = "app.negocio_id"


async def establecer_contexto(conexion: AsyncConnection, negocio_id: UUID) -> None:
    """Fija el negocio activo dentro de la transacción en curso."""
    await conexion.execute(
        text("SELECT set_config(:parametro, :valor, true)"),
        {"parametro": PARAMETRO, "valor": str(negocio_id)},
    )


@asynccontextmanager
async def contexto_negocio(motor: AsyncEngine, negocio_id: UUID) -> AsyncIterator[AsyncConnection]:
    """Abre una transacción con el negocio activo y la cierra al salir.

    Se usa como bloque, no como función suelta, precisamente para que la transacción envuelva todo
    lo que hay dentro: si el contexto se estableciera en una conexión y las consultas se lanzaran en
    otra, el aislamiento no se aplicaría y las lecturas devolverían cero filas sin dar ningún error.
    """
    async with motor.connect() as conexion, conexion.begin():
        await establecer_contexto(conexion, negocio_id)
        yield conexion


@asynccontextmanager
async def sin_contexto(motor: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """Transacción para las tablas del plano compartido, que no llevan `negocio_id`.

    El catálogo de términos y el histórico de contrataciones son **públicos y compartidos**: se
    ingestan una sola vez para todos los negocios. Se abre transacción igualmente, para que el
    comportamiento sea el mismo que con contexto y no haya sorpresas al mover una consulta.
    """
    async with motor.connect() as conexion, conexion.begin():
        yield conexion
