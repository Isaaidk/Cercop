"""Seguimiento de las proformas de una empresa («Mis ofertas»)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from contratacion.infraestructura.adaptadores.salida.bd.contexto import (
    contexto_negocio,
    sin_contexto,
)

_LISTA = """
SELECT p.id, p.tipo, p.titulo, p.entidad, p.objeto, p.creado_en,
       p.etapa, p.etapa_en, p.monto_adjudicado, p.nota, p.registro_id,
       NULLIF(p.cifras ->> 'total', '')::numeric AS total,
       jsonb_array_length(p.lineas) AS lineas,
       r.datos ->> 'codigo' AS codigo,
       r.plazo_proformas_en AS plazo,
       r.provincia AS provincia
FROM proforma p
LEFT JOIN registro r ON r.id = p.registro_id
WHERE p.negocio_id = :negocio_id
ORDER BY p.creado_en DESC
LIMIT :limite
"""


class RepositorioSeguimiento:
    def __init__(self, motor: AsyncEngine) -> None:
        self._motor = motor

    async def listar(self, *, negocio_id: UUID, limite: int = 500) -> list[dict[str, Any]]:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            filas = (
                (await conexion.execute(text(_LISTA), {"negocio_id": negocio_id, "limite": limite}))
                .mappings()
                .all()
            )
        return [dict(fila) for fila in filas]

    async def actualizar(
        self, *, negocio_id: UUID, proforma_id: UUID, campos: dict[str, Any]
    ) -> bool:
        """Cambia etapa, monto o nota. La hora de la etapa solo se mueve si la etapa cambia."""
        asignables = {
            clave: valor
            for clave, valor in campos.items()
            if clave in {"etapa", "monto_adjudicado", "nota"}
        }
        if not asignables:
            return True
        conjuntos = [f"{clave} = :{clave}" for clave in asignables]
        if "etapa" in asignables:
            conjuntos.append(
                "etapa_en = CASE WHEN etapa IS DISTINCT FROM :etapa THEN now() ELSE etapa_en END"
            )
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            resultado = await conexion.execute(
                text(
                    f"UPDATE proforma SET {', '.join(conjuntos)} "
                    "WHERE id = :id AND negocio_id = :negocio_id"
                ),
                {**asignables, "id": proforma_id, "negocio_id": negocio_id},
            )
        return bool(getattr(resultado, "rowcount", 0))

    async def por_cerrar(self, *, horas: int) -> list[dict[str, Any]]:
        """Borradores cuyo proceso cierra dentro de `horas`, de todas las empresas (worker)."""
        async with sin_contexto(self._motor) as conexion:
            filas = (
                (
                    await conexion.execute(
                        text("SELECT * FROM proformas_por_cerrar(:horas)"), {"horas": horas}
                    )
                )
                .mappings()
                .all()
            )
        return [dict(fila) for fila in filas]

    async def recordar(self, fila: dict[str, Any], *, titulo: str, detalle: str) -> None:
        """Deja el aviso al autor de la proforma y la marca como recordada, en una transacción.

        La marca va **primero** y es condicional (`recordado_en IS NULL`): si dos réplicas del
        worker toman la misma proforma, solo la que gana el `UPDATE` deja el aviso; la otra no
        toca nada. Antes las dos insertaban y la persona recibía el recordatorio dos veces.
        """
        async with contexto_negocio(self._motor, fila["id_negocio"]) as conexion:
            marcada = (
                await conexion.execute(
                    text(
                        "UPDATE proforma SET recordado_en = now() "
                        "WHERE id = :id AND recordado_en IS NULL RETURNING id"
                    ),
                    {"id": fila["id_proforma"]},
                )
            ).scalar_one_or_none()
            if marcada is None:
                return
            await conexion.execute(
                text(
                    """
                    INSERT INTO aviso (negocio_id, usuario_id, registro_id, titulo, detalle)
                    VALUES (:negocio_id, :usuario_id, :registro_id, :titulo, :detalle)
                    """
                ),
                {
                    "negocio_id": fila["id_negocio"],
                    "usuario_id": fila["id_usuario"],
                    "registro_id": fila["id_registro"],
                    "titulo": titulo,
                    "detalle": detalle,
                },
            )
