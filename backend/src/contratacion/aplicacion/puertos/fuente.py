"""Contrato de una fuente externa de datos de contratación.

La aplicación ingesta a través de este puerto, nunca hablando con HTTP directamente. Eso permite
probar toda la cadena con una fuente falsa, sin tocar la red ni gastar cuota, que es justo lo que
exige el requisito de que **ninguna petición de usuario llegue a la fuente oficial**.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from contratacion.dominio.ingesta import Presupuesto


@dataclass
class ResultadoExtraccion:
    """Lo que devuelve una fuente en un ciclo."""

    registros: list[dict[str, Any]] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    peticiones: int = 0
    agoto_presupuesto: bool = False
    parcial: bool = False


class FuenteExterna(Protocol):
    """Puerto que implementa cada fuente de datos."""

    codigo: str

    async def extraer(self, desde: datetime, presupuesto: Presupuesto) -> ResultadoExtraccion:
        """Trae los registros publicados desde `desde`.

        Debe respetar el presupuesto: cuando se agota, deja de pedir y marca `agoto_presupuesto`
        en lugar de seguir intentándolo.
        """
        ...

    def clave_natural(self, crudo: Mapping[str, Any]) -> str | None:
        """Identificador estable del registro, o `None` si no sirve y hay que descartarlo."""
        ...

    def terminos(self, crudo: Mapping[str, Any]) -> Sequence[str]:
        """Identificadores de los términos que motivaron la ingesta de este registro."""
        ...
