"""Puerto de «Mis ofertas»: las proformas hechas, su etapa y los recordatorios de cierre."""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID


class RepositorioSeguimiento(Protocol):
    async def listar(self, *, negocio_id: UUID, limite: int = 500) -> list[dict[str, Any]]: ...

    async def actualizar(
        self, *, negocio_id: UUID, proforma_id: UUID, campos: dict[str, Any]
    ) -> bool: ...

    async def por_cerrar(self, *, horas: int) -> list[dict[str, Any]]: ...

    async def recordar(self, fila: dict[str, Any], *, titulo: str, detalle: str) -> None: ...
