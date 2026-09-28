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

    async def obtener(self, clave: str) -> str | None:
        """Devuelve el valor guardado o `None` si no existe o ya expiró."""
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
