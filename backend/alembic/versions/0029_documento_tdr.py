"""Metadatos del TDR. El archivo no entra en la base.

Revision ID: 0029
Revises: 0028
Create Date: 2026-11-09

`registro.documentos` guarda el nombre y el enlace que ya venían en la ficha (unos cientos de
bytes). `documento_tdr` apunta al archivo temporal en disco: estado, hash y cuándo vence. El
binario vive fuera de PostgreSQL y se borra al día.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ejecutar(sql: str) -> None:
    for sentencia in sql.split(";"):
        limpia = sentencia.strip()
        if limpia:
            op.execute(limpia)


def upgrade() -> None:
    _ejecutar(
        """
        ALTER TABLE registro ADD COLUMN IF NOT EXISTS documentos jsonb NOT NULL DEFAULT '[]';

        CREATE TABLE documento_tdr (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            registro_id uuid NOT NULL REFERENCES registro(id) ON DELETE CASCADE,
            nombre text NOT NULL,
            url_origen text NOT NULL DEFAULT '',
            mime text,
            tamano_bytes bigint,
            sha256 text,
            ruta text,
            estado text NOT NULL DEFAULT 'pendiente',
            campos_pedido jsonb NOT NULL DEFAULT '[]',
            descargado_en timestamptz,
            expira_en timestamptz,
            error text,
            CONSTRAINT documento_tdr_estado CHECK (estado IN ('pendiente', 'listo', 'error')),
            CONSTRAINT documento_tdr_unico UNIQUE (registro_id, nombre)
        );

        CREATE INDEX ix_documento_tdr_pendiente ON documento_tdr (estado) WHERE estado = 'pendiente';
        """
    )


def downgrade() -> None:
    _ejecutar(
        """
        DROP TABLE IF EXISTS documento_tdr;
        ALTER TABLE registro DROP COLUMN IF EXISTS documentos;
        """
    )
