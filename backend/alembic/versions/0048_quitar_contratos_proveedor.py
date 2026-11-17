"""Quita las tablas de contratos importados (0047): se vuelve a consultar al SERCOP en vivo.

Decisión del 2026-11-17: «Buscar mis contratos» vuelve a la API de datos abiertos del SERCOP
cuando esta se habilite, en vez de importar los archivos anuales del registro de Open Contracting.

Revision ID: 0048
Revises: 0047
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0048"
down_revision: str | None = "0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS contrato_importacion")
    op.execute("DROP TABLE IF EXISTS contrato_entidad")
    op.execute("DROP TABLE IF EXISTS contrato_cpc")
    op.execute("DROP TABLE IF EXISTS contrato_proveedor")


def downgrade() -> None:
    # Vuelven vacías, como las dejó 0047.
    op.execute(
        "CREATE TABLE IF NOT EXISTS contrato_proveedor (ruc text PRIMARY KEY, datos text NOT NULL)"
    )
    op.execute(
        "CREATE TABLE IF NOT EXISTS contrato_cpc (codigo text PRIMARY KEY, descripcion text NOT NULL)"
    )
    op.execute(
        "CREATE TABLE IF NOT EXISTS contrato_entidad (id integer PRIMARY KEY, nombre text NOT NULL)"
    )
    op.execute(
        "CREATE TABLE IF NOT EXISTS contrato_importacion (id smallint PRIMARY KEY DEFAULT 1 "
        "CHECK (id = 1), terminado_en timestamptz NOT NULL, anios text NOT NULL, "
        "proveedores integer NOT NULL)"
    )
