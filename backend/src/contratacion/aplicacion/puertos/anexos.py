"""Puertos de los anexos de un proceso con oferta (OCDS).

Dos contratos estrechos: leer el registro ya ingestado (para saber de qué fuente es y cuál es su
`ocid`) y pedir la ficha del proceso a los datos abiertos. El caso de uso `anexos_ocds` depende de
ellos y no de PostgreSQL ni de `httpx`, así que se prueba con dobles.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol
from uuid import UUID


class RegistrosDeProceso(Protocol):
    """El registro ingestado: `id`, `fuente` (código), `clave_natural` y `datos`, o `None`."""

    async def leer(self, registro_id: UUID) -> Mapping[str, Any] | None: ...


class FichasDeProceso(Protocol):
    """La ficha de un proceso de OCDS por su `ocid`.

    Devuelve `documentos` (cada uno con `nombre`, `enlace`, `fecha`, `tipo_fuente`, `formato`),
    `presupuesto` (`monto`, `moneda`, `fuente`, `etiqueta_fuente`, o `None`), `adjudicado`,
    `aclaraciones`, `codigo` y `estado`. Lanza `NoEncontrado` si la fuente no tiene el proceso y
    `EstadoInvalido` (o `ServicioNoDisponible`) si no se pudo consultar.
    """

    async def leer(self, ocid: str) -> Mapping[str, Any]: ...
