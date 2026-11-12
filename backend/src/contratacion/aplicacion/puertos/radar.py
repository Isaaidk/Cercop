"""Puertos del radar de oportunidades y de las alertas.

Recogen solo lo que usan los casos de uso `ver_radar` y `revisar_alertas`: leer candidatos ya
ingestados, recorrer las alertas activas, dejar un aviso y marcar la alerta como revisada. Las
búsquedas guardadas, los avisos leídos y el resto del repositorio los usan directamente los
enrutadores y no forman parte de este contrato: un puerto más ancho que su uso obliga a cualquier
implementación —una de pruebas, por ejemplo— a fingir métodos que nadie llama (segregación de
interfaces).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID


class CandidatosRadar(Protocol):
    """Lo vigente que el radar compara con el perfil. Lee del histórico; no llama al portal."""

    async def candidatos(
        self,
        *,
        fuentes: tuple[str, ...],
        provincias: tuple[str, ...],
        desde: datetime | None,
        limite: int,
    ) -> list[dict[str, Any]]: ...


class RepositorioAlertas(CandidatosRadar, Protocol):
    """Lo que necesita la revisión periódica de alertas del worker."""

    async def listar_alertas(self, *, negocio_id: UUID | None = None) -> list[dict[str, Any]]: ...

    async def marcar_revisada(
        self, alerta_id: UUID, momento: datetime, *, negocio_id: UUID | None = None
    ) -> None: ...

    async def crear_aviso(self, campos: dict[str, Any]) -> None: ...

    async def crear_avisos(self, avisos: list[dict[str, Any]]) -> int:
        """Varios avisos en una escritura; los repetidos (misma alerta y proceso) no se crean."""
        ...


class InfimasAbiertas(Protocol):
    """Las ínfimas (NCO) vigentes que aún reciben proformas, ya acotadas por CPC o palabras.

    Es un puerto aparte de `CandidatosRadar` porque el contrato es otro: aquí no hay tope oculto ni
    mezcla de fuentes. «Propuestas para ti» promete **todas** las ínfimas que la empresa puede
    ofertar, así que la consulta filtra en la base de datos lo que no encaja en lugar de traer las
    más recientes y cortar.
    """

    async def infimas_abiertas(
        self,
        *,
        provincias: tuple[str, ...],
        cpc: tuple[str, ...],
        palabras: tuple[str, ...],
        incluir_sin_plazo: bool,
        limite: int,
    ) -> list[dict[str, Any]]: ...
