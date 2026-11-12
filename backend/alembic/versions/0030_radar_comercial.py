"""Perfil comercial, radar, alertas y búsquedas guardadas.

Revision ID: 0030
Revises: 0029
Create Date: 2026-11-09

El presupuesto y la capacidad viven en la empresa. Los productos y las palabras clave comerciales
son filas, igual que la cobertura. Las alertas y los avisos son de cada usuario. Las búsquedas
guardadas conservan los filtros tal como los manda el panel.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
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
        ALTER TABLE negocio ADD COLUMN IF NOT EXISTS presupuesto_min numeric;
        ALTER TABLE negocio ADD COLUMN IF NOT EXISTS presupuesto_max numeric;
        ALTER TABLE negocio ADD COLUMN IF NOT EXISTS capacidad_ejecucion text;

        CREATE TABLE negocio_oferta (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            negocio_id uuid NOT NULL REFERENCES negocio(id) ON DELETE CASCADE,
            tipo text NOT NULL,
            nombre text NOT NULL,
            descripcion text NOT NULL DEFAULT '',
            CONSTRAINT negocio_oferta_tipo CHECK (tipo IN ('producto', 'servicio'))
        );
        {_aislar("negocio_oferta")}

        CREATE TABLE negocio_palabra (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            negocio_id uuid NOT NULL REFERENCES negocio(id) ON DELETE CASCADE,
            texto text NOT NULL
        );
        {_aislar("negocio_palabra")}

        CREATE TABLE busqueda_guardada (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            negocio_id uuid NOT NULL REFERENCES negocio(id) ON DELETE CASCADE,
            usuario_id uuid NOT NULL REFERENCES usuario(id) ON DELETE CASCADE,
            nombre text NOT NULL,
            parametros jsonb NOT NULL DEFAULT '{{}}',
            creado_en timestamptz NOT NULL DEFAULT now()
        );
        {_aislar("busqueda_guardada")}

        CREATE TABLE alerta (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            negocio_id uuid NOT NULL REFERENCES negocio(id) ON DELETE CASCADE,
            usuario_id uuid NOT NULL REFERENCES usuario(id) ON DELETE CASCADE,
            nombre text NOT NULL,
            cpc text[] NOT NULL DEFAULT '{{}}',
            palabras text[] NOT NULL DEFAULT '{{}}',
            provincia text NOT NULL DEFAULT '',
            canton text NOT NULL DEFAULT '',
            presupuesto_min numeric,
            presupuesto_max numeric,
            frecuencia text NOT NULL DEFAULT 'diaria',
            avisar_correo boolean NOT NULL DEFAULT false,
            activa boolean NOT NULL DEFAULT true,
            revisada_en timestamptz,
            creado_en timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT alerta_frecuencia CHECK (frecuencia IN ('inmediata', 'diaria', 'semanal'))
        );
        {_aislar("alerta")}

        CREATE TABLE aviso (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            negocio_id uuid NOT NULL REFERENCES negocio(id) ON DELETE CASCADE,
            usuario_id uuid NOT NULL REFERENCES usuario(id) ON DELETE CASCADE,
            alerta_id uuid REFERENCES alerta(id) ON DELETE CASCADE,
            registro_id uuid,
            titulo text NOT NULL,
            detalle text NOT NULL DEFAULT '',
            puntuacion integer,
            leido_en timestamptz,
            creado_en timestamptz NOT NULL DEFAULT now()
        );
        {_aislar("aviso")}
        CREATE INDEX ix_aviso_usuario ON aviso (usuario_id, creado_en DESC);
        """
    )


def downgrade() -> None:
    _ejecutar(
        """
        DROP TABLE IF EXISTS aviso;
        DROP TABLE IF EXISTS alerta;
        DROP TABLE IF EXISTS busqueda_guardada;
        DROP TABLE IF EXISTS negocio_palabra;
        DROP TABLE IF EXISTS negocio_oferta;
        ALTER TABLE negocio DROP COLUMN IF EXISTS capacidad_ejecucion;
        ALTER TABLE negocio DROP COLUMN IF EXISTS presupuesto_max;
        ALTER TABLE negocio DROP COLUMN IF EXISTS presupuesto_min;
        """
    )
