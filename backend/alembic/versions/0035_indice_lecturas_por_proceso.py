"""Índices de la oferta: lecturas por proceso y búsqueda del proceso por su clave.

Revision ID: 0035
Revises: 0034
Create Date: 2026-11-10

Abrir un TDR ya leído por la empresa deja de insertar una lectura nueva: se busca la existente
por `(negocio_id, registro_id)`. Sin este índice esa búsqueda recorrería todas las lecturas de la
empresa.

Localizar un proceso por su código compara `datos->>'codigo'` **o** `clave_natural`. El primero
tenía índice trigram; el segundo no, y un `OR` con una mitad sin índice obliga a recorrer toda la
tabla `registro`. Con miles de personas sondeando la bajada de su TDR, eso era un recorrido completo
cada pocos segundos por cada una.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_registro_clave_natural_trgm "
        "ON registro USING gin (clave_natural gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_lectura_documento_proceso "
        "ON lectura_documento (negocio_id, registro_id, creado_en DESC) "
        "WHERE registro_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_registro_clave_natural_trgm")
    op.execute("DROP INDEX IF EXISTS ix_lectura_documento_proceso")
