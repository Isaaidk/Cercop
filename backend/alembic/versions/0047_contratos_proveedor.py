"""Contratos adjudicados por RUC, importados del registro de Open Contracting.

«Buscar mis contratos» consultaba la API de datos abiertos del SERCOP, retirada en noviembre de
2026. Ahora el worker importa una vez al mes los archivos anuales del registro de Open Contracting
(ver `fuentes/contratos_ocp.py`) y deja aquí un **resumen corto por RUC**; la consulta del perfil
es una lectura por clave primaria.

Son datos públicos, iguales para todas las empresas: no llevan `negocio_id` ni RLS. Pensadas para
ocupar poco (~15 MB): el resumen va en texto JSON compacto y los nombres de CPC y de entidades van
una sola vez en sus tablas.

Revision ID: 0047
Revises: 0046
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0047"
down_revision: str | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS contrato_proveedor (
            ruc text PRIMARY KEY,
            datos text NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS contrato_cpc (
            codigo text PRIMARY KEY,
            descripcion text NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS contrato_entidad (
            id integer PRIMARY KEY,
            nombre text NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS contrato_importacion (
            id smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
            terminado_en timestamptz NOT NULL,
            anios text NOT NULL,
            proveedores integer NOT NULL
        )
        """
    )
    # La importación vacía las tablas con TRUNCATE (devuelve el espacio en el acto). El rol de la
    # aplicación (migración 0043) solo tiene SELECT/INSERT/UPDATE/DELETE: se le da TRUNCATE aquí.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'contratacion_app') THEN
                GRANT TRUNCATE ON contrato_proveedor, contrato_cpc, contrato_entidad
                    TO contratacion_app;
            END IF;
        END $$
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS contrato_importacion")
    op.execute("DROP TABLE IF EXISTS contrato_entidad")
    op.execute("DROP TABLE IF EXISTS contrato_cpc")
    op.execute("DROP TABLE IF EXISTS contrato_proveedor")
