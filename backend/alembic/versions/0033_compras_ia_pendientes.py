"""Lista de compras de créditos pendientes para la plataforma.

Revision ID: 0033
Revises: 0032
Create Date: 2026-11-09

`compra_ia` tiene RLS forzado, así que sin contexto no se ve ninguna fila. La plataforma necesita
la cola de pendientes de todas las empresas para confirmar pagos; la función devuelve solo esas
columnas y nada más. La confirmación entra por la puerta, con el contexto de cada empresa.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION compras_ia_pendientes()
        RETURNS TABLE (
            id_compra uuid, id_negocio uuid, nombre_empresa text, paquete_compra text,
            creditos_compra integer, precio_compra numeric, creada_en timestamptz
        )
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
            SELECT c.id, c.negocio_id, n.nombre, c.paquete, c.creditos, c.precio_usd, c.creado_en
            FROM compra_ia c JOIN negocio n ON n.id = c.negocio_id
            WHERE c.estado = 'pendiente'
            ORDER BY c.creado_en
            LIMIT 500
        $$
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS compras_ia_pendientes()")
