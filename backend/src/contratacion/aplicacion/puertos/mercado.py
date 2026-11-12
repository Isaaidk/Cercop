"""Puerto de las consultas de mercado: adjudicaciones, precios, proveedores, entidades y demanda.

Todas leen el histórico ya ingestado y ninguna llama al portal. Que el caso de uso dependa de este
contrato, y no de la clase de PostgreSQL, es lo que permitiría mañana servir estas lecturas desde
una réplica de solo lectura o desde una vista materializada sin tocar las reglas.
"""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID


class RepositorioMercado(Protocol):
    async def adjudicaciones(
        self,
        *,
        fuentes: tuple[str, ...],
        q: str = "",
        cpc: str = "",
        entidad: str = "",
        proveedor: str = "",
        anio: str = "",
        limite: int = 60,
    ) -> list[dict[str, Any]]: ...

    async def montos(
        self,
        *,
        fuentes: tuple[str, ...],
        q: str = "",
        cpc: str = "",
        anio: str = "",
        limite: int = 400,
    ) -> list[dict[str, Any]]: ...

    async def proveedores(
        self,
        *,
        fuentes: tuple[str, ...],
        q: str = "",
        cpc: str = "",
        anio: str = "",
        limite: int = 30,
    ) -> list[dict[str, Any]]: ...

    async def entidades(
        self,
        *,
        fuentes: tuple[str, ...],
        q: str = "",
        cpc: str = "",
        anio: str = "",
        limite: int = 30,
    ) -> list[dict[str, Any]]: ...

    async def demanda(
        self,
        *,
        fuentes: tuple[str, ...],
        q: str = "",
        cpc: str = "",
        anio: str = "",
    ) -> dict[str, Any]: ...

    async def comparar(
        self, *, fuentes: tuple[str, ...], ids: list[UUID]
    ) -> list[dict[str, Any]]: ...
