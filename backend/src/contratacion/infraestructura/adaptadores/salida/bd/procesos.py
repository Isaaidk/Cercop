"""Lectura de un registro ingestado para los anexos de un proceso: su fuente, su clave y sus datos.

Implementa `aplicacion.puertos.anexos.RegistrosDeProceso`. El histórico es del plano compartido
(sin `negocio_id`), igual que en `bd/tdr.py`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from contratacion.infraestructura.adaptadores.salida.bd.contexto import sin_contexto


class RepositorioProcesos:
    def __init__(self, motor: AsyncEngine) -> None:
        self._motor = motor

    async def leer(self, registro_id: UUID) -> Mapping[str, Any] | None:
        async with sin_contexto(self._motor) as conexion:
            fila = (
                (
                    await conexion.execute(
                        text(
                            """
                            SELECT r.id, f.codigo AS fuente, r.clave_natural, r.datos
                            FROM registro r
                            JOIN fuente f ON f.id = r.fuente_id
                            WHERE r.id = :id
                            """
                        ),
                        {"id": registro_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if fila is None:
            return None
        resultado = dict(fila)
        if isinstance(resultado.get("datos"), str):
            resultado["datos"] = json.loads(resultado["datos"])
        return resultado
