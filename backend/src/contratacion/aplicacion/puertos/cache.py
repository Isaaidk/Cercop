"""Puerto de caché.

La aplicación depende de este contrato, no de Redis. Eso permite dos implementaciones: una real
(Redis) y una nula, que deja el sistema funcionando sin caché durante el desarrollo.

Todas las operaciones son asíncronas y no deben lanzar excepción por un fallo del caché: la caché es
una optimización, nunca una dependencia de la que dependa la corrección del sistema.
"""

from __future__ import annotations

from typing import Protocol


class Cache(Protocol):
    """Contrato mínimo que necesita la aplicación."""

    @property
    def habilitada(self) -> bool:
        """¿Hay un almacén de verdad detrás?

        Hace falta distinguirlo de «la clave no está», y la diferencia no es de matiz. Sin almacén,
        la ausencia de una clave significa que nadie la escribió; con almacén, significa que se
        escribió y ya no está. Lo primero obliga a preguntar a la base de datos; lo segundo es una
        respuesta. Confundirlas deja el sistema sin cerrar sesiones —siempre se pregunta— o lo deja
        fuera de servicio —se da por cerrada una sesión que nunca se registró allí—.
        """
        ...

    async def obtener(self, clave: str) -> str | None:
        """Devuelve el valor guardado o `None` si no existe o ya expiró."""
        ...

    async def obtener_renovando(self, clave: str, ttl_seg: int) -> str | None:
        """Lee un valor y, si existía, **reinicia** su tiempo de vida.

        Es una operación y no dos —leer y volver a escribir— por una razón que no tiene nada que ver
        con el rendimiento. Con dos operaciones, un cierre de sesión que ocurra justo entre la
        lectura y la escritura **vuelve a crear la clave que se acababa de borrar**, y la sesión
        revocada resucita: el usuario sale, y sigue dentro. Esta operación no crea la clave cuando
        no existe, así que ese hueco no existe.
        """
        ...

    async def guardar(self, clave: str, valor: str, ttl_seg: int) -> None:
        """Guarda un valor con tiempo de vida."""
        ...

    async def eliminar(self, clave: str) -> None:
        """Borra una clave."""
        ...

    async def incrementar(self, clave: str) -> int:
        """Incrementa un contador atómico y devuelve el valor resultante.

        Se usa para la *generación* de cada fuente: al cerrar un ciclo de ingesta se incrementa, y
        todas las claves de caché calculadas con la generación anterior quedan lógicamente
        invalidadas sin necesidad de borrarlas una a una.
        """
        ...

    async def ping(self) -> bool:
        """`True` si el almacén responde."""
        ...

    async def cerrar(self) -> None:
        """Libera recursos."""
        ...
