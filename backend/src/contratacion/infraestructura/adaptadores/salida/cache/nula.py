"""Implementación nula del puerto de caché.

Se usa cuando no hay ningún almacén configurado —el caso del desarrollo local sin Redis—. Todas las
lecturas fallan (lo que obliga a ir a la base de datos) y todas las escrituras se ignoran.

Consecuencia esperada: el sistema funciona **completo**, solo más lento. Ninguna funcionalidad
depende de la caché para ser correcta.
"""

from __future__ import annotations

import logging

registro = logging.getLogger(__name__)


class CacheNula:
    """Caché deshabilitada: no guarda nada y nunca acierta."""

    def __init__(self) -> None:
        self.deshabilitada = True

    async def obtener(self, clave: str) -> str | None:
        return None

    async def guardar(self, clave: str, valor: str, ttl_seg: int) -> None:
        return None

    async def eliminar(self, clave: str) -> None:
        return None

    async def incrementar(self, clave: str) -> int:
        # Sin caché no hay nada que invalidar, así que la generación es irrelevante.
        return 0

    async def ping(self) -> bool:
        return False

    async def cerrar(self) -> None:
        return None
