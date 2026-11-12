"""Créditos de IA por empresa y datos completos de la oferta.

Revision ID: 0032
Revises: 0031
Create Date: 2026-11-09

Cada generación con IA consume créditos del saldo de la empresa. El saldo solo sube con un
movimiento: regalo inicial, compra confirmada o ajuste de plataforma. La compra queda pendiente
hasta que alguien confirma el pago; no hay pasarela todavía.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONTEXTO = "NULLIF(current_setting('app.negocio_id', true), '')::uuid"
REGALO_INICIAL = 30


def _ejecutar(sql: str) -> None:
    for sentencia in sql.split(";"):
        limpia = sentencia.strip()
        if limpia:
            op.execute(limpia)


def _aislar(tabla: str) -> str:
    return f"""
        ALTER TABLE {tabla} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {tabla} FORCE ROW LEVEL SECURITY;
        CREATE POLICY aislamiento_{tabla} ON {tabla}
            USING (negocio_id = {CONTEXTO})
            WITH CHECK (negocio_id = {CONTEXTO});
    """


def upgrade() -> None:
    _ejecutar(
        f"""
        ALTER TABLE proforma ADD COLUMN IF NOT EXISTS extras jsonb NOT NULL DEFAULT '{{}}';

        CREATE TABLE saldo_ia (
            negocio_id uuid PRIMARY KEY REFERENCES negocio(id) ON DELETE CASCADE,
            disponibles integer NOT NULL DEFAULT 0 CHECK (disponibles >= 0),
            usados integer NOT NULL DEFAULT 0 CHECK (usados >= 0),
            actualizado_en timestamptz NOT NULL DEFAULT now()
        );
        {_aislar("saldo_ia")}

        CREATE TABLE movimiento_ia (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            negocio_id uuid NOT NULL REFERENCES negocio(id) ON DELETE CASCADE,
            usuario_id uuid REFERENCES usuario(id) ON DELETE SET NULL,
            tipo text NOT NULL,
            cantidad integer NOT NULL,
            motivo text NOT NULL DEFAULT '',
            creado_en timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT movimiento_ia_tipo CHECK (tipo IN ('regalo', 'compra', 'consumo', 'ajuste'))
        );
        {_aislar("movimiento_ia")}
        CREATE INDEX ix_movimiento_ia_negocio ON movimiento_ia (negocio_id, creado_en DESC);

        CREATE TABLE compra_ia (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            negocio_id uuid NOT NULL REFERENCES negocio(id) ON DELETE CASCADE,
            usuario_id uuid REFERENCES usuario(id) ON DELETE SET NULL,
            paquete text NOT NULL,
            creditos integer NOT NULL CHECK (creditos > 0),
            precio_usd numeric NOT NULL CHECK (precio_usd >= 0),
            estado text NOT NULL DEFAULT 'pendiente',
            creado_en timestamptz NOT NULL DEFAULT now(),
            resuelto_en timestamptz,
            resuelto_por uuid REFERENCES usuario(id) ON DELETE SET NULL,
            CONSTRAINT compra_ia_estado CHECK (estado IN ('pendiente', 'pagada', 'anulada'))
        );
        {_aislar("compra_ia")}
        CREATE INDEX ix_compra_ia_estado ON compra_ia (estado, creado_en DESC);

        INSERT INTO saldo_ia (negocio_id, disponibles)
        SELECT id, {REGALO_INICIAL} FROM negocio
        ON CONFLICT (negocio_id) DO NOTHING;

        INSERT INTO movimiento_ia (negocio_id, tipo, cantidad, motivo)
        SELECT id, 'regalo', {REGALO_INICIAL}, 'Créditos de bienvenida' FROM negocio
        """
    )


def downgrade() -> None:
    _ejecutar(
        """
        DROP TABLE IF EXISTS compra_ia;
        DROP TABLE IF EXISTS movimiento_ia;
        DROP TABLE IF EXISTS saldo_ia;
        ALTER TABLE proforma DROP COLUMN IF EXISTS extras
        """
    )
