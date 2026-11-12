"""Lecturas de TDR, requisitos marcables y proformas confirmadas.

Revision ID: 0031
Revises: 0030
Create Date: 2026-11-09

El PDF no se guarda. Se guarda el texto de los apartados reconocidos, la lista para marcar y la
proforma con los precios que escribió el usuario.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONTEXTO = "NULLIF(current_setting('app.negocio_id', true), '')::uuid"


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
        CREATE INDEX ix_{tabla}_negocio ON {tabla} (negocio_id);
    """


def upgrade() -> None:
    _ejecutar(
        f"""
        CREATE TABLE lectura_documento (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            negocio_id uuid NOT NULL REFERENCES negocio(id) ON DELETE CASCADE,
            usuario_id uuid NOT NULL REFERENCES usuario(id) ON DELETE CASCADE,
            nombre text NOT NULL,
            registro_id uuid,
            secciones jsonb NOT NULL DEFAULT '{{}}',
            creado_en timestamptz NOT NULL DEFAULT now()
        );
        {_aislar("lectura_documento")}

        CREATE TABLE requisito_proceso (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            negocio_id uuid NOT NULL REFERENCES negocio(id) ON DELETE CASCADE,
            lectura_id uuid NOT NULL REFERENCES lectura_documento(id) ON DELETE CASCADE,
            texto text NOT NULL,
            estado text NOT NULL DEFAULT 'pendiente',
            orden integer NOT NULL DEFAULT 0,
            CONSTRAINT requisito_proceso_estado
                CHECK (estado IN ('pendiente', 'cumplido', 'no_aplica'))
        );
        {_aislar("requisito_proceso")}

        CREATE TABLE proforma (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            negocio_id uuid NOT NULL REFERENCES negocio(id) ON DELETE CASCADE,
            usuario_id uuid NOT NULL REFERENCES usuario(id) ON DELETE CASCADE,
            registro_id uuid,
            tipo text NOT NULL,
            titulo text NOT NULL DEFAULT '',
            entidad text NOT NULL DEFAULT '',
            objeto text NOT NULL DEFAULT '',
            contacto text NOT NULL DEFAULT '',
            impuesto_porcentaje numeric NOT NULL DEFAULT 0,
            lineas jsonb NOT NULL DEFAULT '[]',
            cifras jsonb NOT NULL DEFAULT '{{}}',
            creado_en timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT proforma_tipo CHECK (tipo IN ('proforma', 'cotizacion', 'ficha'))
        );
        {_aislar("proforma")}
        """
    )


def downgrade() -> None:
    _ejecutar(
        """
        DROP TABLE IF EXISTS proforma;
        DROP TABLE IF EXISTS requisito_proceso;
        DROP TABLE IF EXISTS lectura_documento;
        """
    )
