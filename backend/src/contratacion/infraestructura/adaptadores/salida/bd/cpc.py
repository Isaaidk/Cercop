"""Lista de términos de CPC de cada empresa sobre PostgreSQL.

El aislamiento va por `contexto_negocio`, igual que en la selección de columnas: la política de RLS
compara `negocio_id` con el contexto de la sesión, así que el repositorio no tiene que acordarse de
filtrar por empresa —y por tanto no puede olvidarse—. Las escrituras llevan además su propio
`negocio_id`, de modo que la política también comprueba el `WITH CHECK`.

Las tres escrituras devuelven `rowcount` en lugar de nada: quien llama necesita saber si el término
estaba o no, y averiguarlo con una lectura previa sería una carrera entre dos usuarios del mismo
negocio añadiendo lo mismo a la vez.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from contratacion.aplicacion.puertos.cpc import ClaveCpc
from contratacion.infraestructura.adaptadores.salida.bd.contexto import contexto_negocio

CAMPOS = "id, texto, creado_en"


def _a_clave(fila: Mapping[Any, Any]) -> ClaveCpc:
    return ClaveCpc(id=fila["id"], texto=fila["texto"], creado_en=fila["creado_en"])


class RepositorioCpcBd:
    """La lista de términos de CPC de cada empresa sobre PostgreSQL."""

    def __init__(self, motor: AsyncEngine) -> None:
        self._motor = motor

    async def listar(self, *, negocio_id: UUID) -> tuple[ClaveCpc, ...]:
        """Los términos de la empresa.

        Se filtra por `negocio_id` **además** de confiar en RLS, y no es redundancia: el rol de la
        aplicación en este despliegue se salta las políticas (`rolbypassrls`), así que un `SELECT`
        sin filtro devolvería la lista de todas las empresas. La política sigue ahí como segunda
        barrera —el día que se use un rol sin privilegios, filtra ella—, pero la primera tiene que
        estar escrita en la consulta.
        """
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            filas = (
                (
                    await conexion.execute(
                        text(
                            f"SELECT {CAMPOS} FROM cpc_clave"
                            " WHERE negocio_id = :negocio_id ORDER BY creado_en, texto"
                        ),
                        {"negocio_id": negocio_id},
                    )
                )
                .mappings()
                .all()
            )
        return tuple(_a_clave(fila) for fila in filas)

    async def agregar(
        self,
        *,
        negocio_id: UUID,
        texto: str,
        texto_normalizado: str,
        creado_por: UUID | None,
        momento: datetime,
    ) -> bool:
        """Inserta el término. `False` si ya estaba, sin lanzar error.

        `ON CONFLICT DO NOTHING` y no `DO UPDATE`: añadir algo que ya está no cambia nada, y
        sobrescribir el texto permitiría que «lavado» reemplazara a «LAVADO» —la grafía que alguien
        eligió a propósito— por pasar otra vez por el mismo sitio.
        """
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            resultado = await conexion.execute(
                text(
                    """
                    INSERT INTO cpc_clave (
                        negocio_id, texto, texto_normalizado, creado_por, creado_en
                    )
                    VALUES (:negocio_id, :texto, :normalizado, :creado_por, :momento)
                    ON CONFLICT (negocio_id, texto_normalizado) DO NOTHING
                    """
                ),
                {
                    "negocio_id": negocio_id,
                    "texto": texto,
                    "normalizado": texto_normalizado,
                    "creado_por": creado_por,
                    "momento": momento,
                },
            )
        return bool(resultado.rowcount)

    async def quitar(self, *, negocio_id: UUID, texto_normalizado: str) -> bool:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            resultado = await conexion.execute(
                text(
                    "DELETE FROM cpc_clave WHERE negocio_id = :negocio_id"
                    " AND texto_normalizado = :normalizado"
                ),
                {"negocio_id": negocio_id, "normalizado": texto_normalizado},
            )
        return bool(resultado.rowcount)

    async def limpiar(self, *, negocio_id: UUID) -> int:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            resultado = await conexion.execute(
                text("DELETE FROM cpc_clave WHERE negocio_id = :negocio_id"),
                {"negocio_id": negocio_id},
            )
        return int(resultado.rowcount or 0)
