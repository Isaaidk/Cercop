"""Adaptador de salida: concesiones de acceso a vistas.

Todas las operaciones se ejecutan dentro del contexto del negocio, así que las políticas de RLS son
las que deciden qué filas existen. Es la razón por la que este adaptador no filtra por `negocio_id`
en las lecturas «para asegurarse»: el filtro está en la base y repetirlo daría la falsa impresión de
que el aislamiento depende del código de aquí.

Las filas se traducen a objetos del dominio en el borde. Si un código de vista o de plazo no
correspondiera a ningún valor conocido —algo que la restricción `CHECK` impide—, la fila se descarta
y se registra: descartar equivale a **no conceder**, que es el lado seguro del error.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from contratacion.dominio.acceso import AccesoVista, Plazo, Vista
from contratacion.infraestructura.adaptadores.salida.bd.contexto import contexto_negocio

registro = logging.getLogger(__name__)

CAMPOS_ACCESO = """
    id, negocio_id, usuario_id, vista, plazo_codigo,
    otorgado_en, vence_en, otorgado_por, revocado_en, revocado_por, motivo
"""


def _a_acceso(fila: Mapping[Any, Any]) -> AccesoVista | None:
    """Convierte una fila en una concesión del dominio, o `None` si no es interpretable."""
    try:
        return AccesoVista(
            vista=Vista(str(fila["vista"])),
            otorgado_en=fila["otorgado_en"],
            vence_en=fila["vence_en"],
            plazo=Plazo(str(fila["plazo_codigo"])),
            revocado_en=fila["revocado_en"],
        )
    except (ValueError, KeyError):
        registro.warning("Concesión ilegible descartada: vista o plazo desconocido", exc_info=False)
        return None


class RepositorioAccesosBd:
    """Implementación sobre PostgreSQL."""

    def __init__(self, motor: AsyncEngine) -> None:
        self._motor = motor

    async def conceder(
        self,
        *,
        negocio_id: UUID,
        usuario_id: UUID,
        vista: Vista,
        plazo: Plazo,
        otorgado_en: datetime,
        vence_en: datetime,
        otorgado_por: UUID,
    ) -> UUID:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            valor: Any = (
                await conexion.execute(
                    text(
                        """
                        INSERT INTO acceso_vista (
                            negocio_id, usuario_id, vista, plazo_codigo,
                            otorgado_en, vence_en, otorgado_por
                        )
                        VALUES (
                            :negocio_id, :usuario_id, :vista, :plazo_codigo,
                            :otorgado_en, :vence_en, :otorgado_por
                        )
                        RETURNING id
                        """
                    ),
                    {
                        "negocio_id": negocio_id,
                        "usuario_id": usuario_id,
                        "vista": str(vista),
                        "plazo_codigo": str(plazo),
                        "otorgado_en": otorgado_en,
                        "vence_en": vence_en,
                        "otorgado_por": otorgado_por,
                    },
                )
            ).scalar_one()
        return valor if isinstance(valor, UUID) else UUID(str(valor))

    async def retirar(
        self,
        *,
        negocio_id: UUID,
        usuario_id: UUID,
        vista: Vista,
        momento: datetime,
        retirado_por: UUID,
    ) -> int:
        """Marca como retiradas todas las concesiones activas de ese par.

        Se retiran **todas** y no solo la última: si se concedió dos veces (una prórroga), dejar una
        viva mantendría el acceso abierto y la retirada no se notaría. Devolver cuántas se tocaron
        es lo que permite distinguir «no se pudo retirar» de «no había nada que retirar».
        """
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            resultado = await conexion.execute(
                text(
                    """
                    UPDATE acceso_vista
                    SET revocado_en = :momento, revocado_por = :retirado_por
                    WHERE negocio_id = :negocio_id
                      AND usuario_id = :usuario_id
                      AND vista = :vista
                      AND revocado_en IS NULL
                    """
                ),
                {
                    "negocio_id": negocio_id,
                    "usuario_id": usuario_id,
                    "vista": str(vista),
                    "momento": momento,
                    "retirado_por": retirado_por,
                },
            )
            return int(resultado.rowcount or 0)

    async def obtener(self, *, negocio_id: UUID, usuario_id: UUID) -> Sequence[AccesoVista]:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            filas = (
                (
                    await conexion.execute(
                        text(
                            f"""
                            SELECT {CAMPOS_ACCESO}
                            FROM acceso_vista
                            WHERE usuario_id = :usuario_id
                            ORDER BY otorgado_en DESC
                            """
                        ),
                        {"usuario_id": usuario_id},
                    )
                )
                .mappings()
                .all()
            )

        accesos: list[AccesoVista] = []
        for fila in filas:
            acceso = _a_acceso(fila)
            if acceso is not None:
                accesos.append(acceso)
        return tuple(accesos)

    async def historial(
        self, *, negocio_id: UUID, usuario_id: UUID, limite: int = 100
    ) -> Sequence[Mapping[str, Any]]:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            filas = (
                (
                    await conexion.execute(
                        text(
                            f"""
                            SELECT {CAMPOS_ACCESO}
                            FROM acceso_vista
                            WHERE usuario_id = :usuario_id
                            ORDER BY otorgado_en DESC
                            LIMIT :limite
                            """
                        ),
                        {"usuario_id": usuario_id, "limite": limite},
                    )
                )
                .mappings()
                .all()
            )
        return tuple(dict(fila) for fila in filas)

    async def usuarios(self, *, negocio_id: UUID, limite: int = 200) -> Sequence[Mapping[str, Any]]:
        """Usuarios **registrados** del negocio. La presencia no se consulta aquí."""
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            filas = (
                (
                    await conexion.execute(
                        text(
                            """
                            SELECT id AS usuario_id, email, nombre, rol, estado, ultimo_acceso
                            FROM usuario
                            ORDER BY nombre, email
                            LIMIT :limite
                            """
                        ),
                        {"limite": limite},
                    )
                )
                .mappings()
                .all()
            )
        return tuple(dict(fila) for fila in filas)

    async def usuario(self, *, negocio_id: UUID, usuario_id: UUID) -> Mapping[str, Any] | None:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            fila = (
                (
                    await conexion.execute(
                        text(
                            """
                            SELECT id AS usuario_id, email, nombre, rol, estado
                            FROM usuario WHERE id = :usuario_id
                            """
                        ),
                        {"usuario_id": usuario_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return dict(fila) if fila else None
