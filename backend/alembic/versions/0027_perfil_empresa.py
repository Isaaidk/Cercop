"""Perfil de la empresa, pensado para rellenar TDR.

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-09

Cada tabla guarda un grupo de datos que después entra en un anexo del pliego: a qué licitaciones
se dedica la empresa, quién la representa, dónde oferta, qué experiencia y qué equipo tiene. El
archivo de un habilitante no vive aquí: solo su metadato y la ruta en el almacén.

Todas llevan `negocio_id`, RLS forzada con `NULLIF` y un índice por empresa.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
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
        ALTER TABLE negocio ADD COLUMN IF NOT EXISTS razon_social text;
        ALTER TABLE negocio ADD COLUMN IF NOT EXISTS nombre_comercial text;
        ALTER TABLE negocio ADD COLUMN IF NOT EXISTS tipo_persona text;
        ALTER TABLE negocio ADD COLUMN IF NOT EXISTS sitio_web text;
        ALTER TABLE negocio ADD COLUMN IF NOT EXISTS logo_ruta text;
        ALTER TABLE negocio ADD COLUMN IF NOT EXISTS estado_rup text;
        ALTER TABLE negocio ADD COLUMN IF NOT EXISTS fecha_inicio_actividades date;
        ALTER TABLE negocio ADD COLUMN IF NOT EXISTS obligado_contabilidad boolean;
        ALTER TABLE negocio ADD COLUMN IF NOT EXISTS regimen_tributario text;

        ALTER TABLE negocio DROP CONSTRAINT IF EXISTS negocio_tipo_persona_check;
        ALTER TABLE negocio ADD CONSTRAINT negocio_tipo_persona_check
            CHECK (tipo_persona IS NULL OR tipo_persona IN ('natural', 'juridica'));
        ALTER TABLE negocio DROP CONSTRAINT IF EXISTS negocio_ruc_13;
        ALTER TABLE negocio ADD CONSTRAINT negocio_ruc_13
            CHECK (ruc IS NULL OR btrim(ruc) = '' OR ruc ~ '^[0-9]{{13}}$') NOT VALID;
        CREATE UNIQUE INDEX IF NOT EXISTS ux_negocio_ruc
            ON negocio (ruc) WHERE ruc IS NOT NULL AND btrim(ruc) <> '';

        CREATE TABLE negocio_dedicacion (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            negocio_id uuid NOT NULL REFERENCES negocio(id) ON DELETE CASCADE,
            tipo_contratacion text NOT NULL,
            tipo_procedimiento text NOT NULL,
            monto_min numeric,
            monto_max numeric,
            principal boolean NOT NULL DEFAULT false,
            CONSTRAINT negocio_dedicacion_tipo
                CHECK (tipo_contratacion IN ('bienes', 'servicios', 'obras', 'consultoria')),
            CONSTRAINT negocio_dedicacion_procedimiento
                CHECK (tipo_procedimiento IN ('infima', 'subasta_inversa', 'catalogo', 'licitacion'))
        );
        {_aislar("negocio_dedicacion")}

        CREATE TABLE negocio_contacto (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            negocio_id uuid NOT NULL REFERENCES negocio(id) ON DELETE CASCADE,
            tipo text NOT NULL,
            nombre text NOT NULL,
            cedula text,
            cargo text,
            email text,
            telefono text,
            principal boolean NOT NULL DEFAULT false,
            CONSTRAINT negocio_contacto_tipo
                CHECK (tipo IN ('representante_legal', 'comercial', 'tecnico'))
        );
        {_aislar("negocio_contacto")}

        CREATE TABLE negocio_actividad (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            negocio_id uuid NOT NULL REFERENCES negocio(id) ON DELETE CASCADE,
            ciiu text NOT NULL,
            descripcion text NOT NULL DEFAULT '',
            principal boolean NOT NULL DEFAULT false
        );
        {_aislar("negocio_actividad")}

        CREATE TABLE negocio_cobertura (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            negocio_id uuid NOT NULL REFERENCES negocio(id) ON DELETE CASCADE,
            provincia text NOT NULL,
            canton text NOT NULL DEFAULT ''
        );
        {_aislar("negocio_cobertura")}

        CREATE TABLE negocio_documento (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            negocio_id uuid NOT NULL REFERENCES negocio(id) ON DELETE CASCADE,
            tipo text NOT NULL,
            nombre text NOT NULL,
            ruta_almacen text,
            sha256 text,
            emitido_en date,
            vence_en date
        );
        {_aislar("negocio_documento")}

        CREATE TABLE negocio_experiencia (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            negocio_id uuid NOT NULL REFERENCES negocio(id) ON DELETE CASCADE,
            entidad text NOT NULL,
            objeto text NOT NULL DEFAULT '',
            monto numeric,
            anio integer,
            cpc text,
            tipo_contratacion text,
            CONSTRAINT negocio_experiencia_tipo
                CHECK (
                    tipo_contratacion IS NULL
                    OR tipo_contratacion IN ('bienes', 'servicios', 'obras', 'consultoria')
                )
        );
        {_aislar("negocio_experiencia")}

        CREATE TABLE negocio_personal (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            negocio_id uuid NOT NULL REFERENCES negocio(id) ON DELETE CASCADE,
            perfil text NOT NULL,
            titulo text NOT NULL DEFAULT '',
            anios integer
        );
        {_aislar("negocio_personal")}

        CREATE TABLE negocio_equipo (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            negocio_id uuid NOT NULL REFERENCES negocio(id) ON DELETE CASCADE,
            nombre text NOT NULL,
            cantidad integer NOT NULL DEFAULT 1,
            estado text NOT NULL DEFAULT 'disponible'
        );
        {_aislar("negocio_equipo")}
        """
    )


def downgrade() -> None:
    for tabla in (
        "negocio_equipo",
        "negocio_personal",
        "negocio_experiencia",
        "negocio_documento",
        "negocio_cobertura",
        "negocio_actividad",
        "negocio_contacto",
        "negocio_dedicacion",
    ):
        op.execute(f"DROP TABLE IF EXISTS {tabla}")
    _ejecutar(
        """
        DROP INDEX IF EXISTS ux_negocio_ruc;
        ALTER TABLE negocio DROP CONSTRAINT IF EXISTS negocio_ruc_13;
        ALTER TABLE negocio DROP CONSTRAINT IF EXISTS negocio_tipo_persona_check;
        ALTER TABLE negocio DROP COLUMN IF EXISTS regimen_tributario;
        ALTER TABLE negocio DROP COLUMN IF EXISTS obligado_contabilidad;
        ALTER TABLE negocio DROP COLUMN IF EXISTS fecha_inicio_actividades;
        ALTER TABLE negocio DROP COLUMN IF EXISTS estado_rup;
        ALTER TABLE negocio DROP COLUMN IF EXISTS logo_ruta;
        ALTER TABLE negocio DROP COLUMN IF EXISTS sitio_web;
        ALTER TABLE negocio DROP COLUMN IF EXISTS tipo_persona;
        ALTER TABLE negocio DROP COLUMN IF EXISTS nombre_comercial;
        ALTER TABLE negocio DROP COLUMN IF EXISTS razon_social;
        """
    )
