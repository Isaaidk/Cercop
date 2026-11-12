"""Los ítems de un proceso que alguien está armando se leen primero.

Revision ID: 0036
Revises: 0035
Create Date: 2026-11-10

Las fichas con los ítems (CPC, unidad, cantidad) se leen por tandas, de la más reciente a la más
antigua. Quien arma una proforma necesita esos ítems **ahora**, no en el ciclo siguiente. Pedir el
TDR de un proceso marca su ficha con `items_prioridad_en`, y el worker lee primero las marcadas.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE registro ADD COLUMN IF NOT EXISTS items_prioridad_en timestamptz")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_registro_items_prioridad "
        "ON registro (items_prioridad_en DESC) "
        "WHERE items_recogidos_en IS NULL AND items_prioridad_en IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_registro_items_prioridad")
    op.execute("ALTER TABLE registro DROP COLUMN IF EXISTS items_prioridad_en")
