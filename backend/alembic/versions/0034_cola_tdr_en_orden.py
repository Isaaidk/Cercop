"""La cola de TDR se atiende en el orden en que se pidió.

Revision ID: 0034
Revises: 0033
Create Date: 2026-11-10

`documento_tdr` no guardaba cuándo se pidió cada archivo, y el worker tomaba `ORDER BY id`: un uuid
al azar. Con pocas personas da igual; con cientos pidiendo a la vez, quien pidió primero podía
esperar detrás de quien pidió último. La columna y el índice parcial dejan la cola en orden de
llegada y la consulta del worker en una lectura de índice.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE documento_tdr ADD COLUMN IF NOT EXISTS pedido_en timestamptz "
        "NOT NULL DEFAULT now()"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_documento_tdr_pendientes "
        "ON documento_tdr (pedido_en) WHERE estado = 'pendiente'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_documento_tdr_pendientes")
    op.execute("ALTER TABLE documento_tdr DROP COLUMN IF EXISTS pedido_en")
