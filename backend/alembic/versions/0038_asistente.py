"""Asistente (chat): conversaciones y mensajes de cada usuario.

Revision ID: 0038
Revises: 0037
Create Date: 2026-11-12

Dos tablas de la empresa, con RLS forzada como todas las del plano de negocio. Además del negocio,
las conversaciones son **de una persona**: el adaptador filtra siempre por `usuario_id`, porque un
compañero de la misma empresa no tiene por qué leer lo que otro le preguntó al asistente.

Se guarda poco a propósito. Los mensajes llevan el texto y las tarjetas que ya se mostraron (el
resultado de las herramientas, recortado), no el historial interno del modelo ni las llamadas a
herramientas. Los topes —200 mensajes por conversación y 50 conversaciones por persona— los aplica
el adaptador al escribir, en la misma transacción, así que la tabla no crece sin límite aunque nadie
borre nada.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0038"
down_revision: str | None = "0037"
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
        CREATE TABLE asistente_conversaciones (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            negocio_id uuid NOT NULL REFERENCES negocio(id) ON DELETE CASCADE,
            usuario_id uuid NOT NULL REFERENCES usuario(id) ON DELETE CASCADE,
            titulo text NOT NULL DEFAULT '',
            creada_en timestamptz NOT NULL DEFAULT now(),
            actualizada_en timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT asistente_conversaciones_titulo_corto CHECK (length(titulo) <= 120)
        );
        {_aislar("asistente_conversaciones")}
        CREATE INDEX ix_asistente_conversaciones_usuario
            ON asistente_conversaciones (usuario_id, actualizada_en DESC);

        CREATE TABLE asistente_mensajes (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            conversacion_id uuid NOT NULL
                REFERENCES asistente_conversaciones(id) ON DELETE CASCADE,
            negocio_id uuid NOT NULL REFERENCES negocio(id) ON DELETE CASCADE,
            rol text NOT NULL,
            texto text NOT NULL DEFAULT '',
            tarjetas jsonb NOT NULL DEFAULT '[]',
            sugerencias jsonb NOT NULL DEFAULT '[]',
            creado_en timestamptz NOT NULL DEFAULT clock_timestamp(),
            CONSTRAINT asistente_mensajes_rol CHECK (rol IN ('usuario', 'asistente'))
        );
        {_aislar("asistente_mensajes")}
        CREATE INDEX ix_asistente_mensajes_conversacion
            ON asistente_mensajes (conversacion_id, creado_en);
        """
    )


def downgrade() -> None:
    _ejecutar(
        """
        DROP TABLE IF EXISTS asistente_mensajes;
        DROP TABLE IF EXISTS asistente_conversaciones;
        """
    )
