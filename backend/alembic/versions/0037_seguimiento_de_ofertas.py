"""Seguimiento de las proformas: etapa, resultado y recordatorio de cierre.

Revision ID: 0037
Revises: 0036
Create Date: 2026-11-11

La pantalla «Mis ofertas» es un tablero de las proformas ya hechas. Se guarda lo mínimo y en la
tabla que ya existe: la etapa (borrador → enviada → adjudicada / perdida / descartada), cuándo
cambió, el monto adjudicado, una nota corta y cuándo se avisó del cierre. Las estadísticas (tasa de
éxito, montos) se calculan al leer, no se guardan.

Las dos funciones son para el worker, que mira **todas** las empresas a la vez. Con RLS forzada, una
consulta sin contexto de empresa no devuelve filas; hoy funciona porque el rol tiene
`rolbypassrls` (riesgo R-05 abierto, ver 0008). Con estas funciones —`SECURITY DEFINER`, como
`listar_negocios`— el recordatorio y las alertas siguen funcionando el día que se cierre R-05, y
cada una devuelve solo las columnas que el worker necesita.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE proforma ADD COLUMN IF NOT EXISTS etapa text NOT NULL DEFAULT 'borrador'"
    )
    op.execute("ALTER TABLE proforma ADD COLUMN IF NOT EXISTS etapa_en timestamptz")
    op.execute("ALTER TABLE proforma ADD COLUMN IF NOT EXISTS monto_adjudicado numeric")
    op.execute("ALTER TABLE proforma ADD COLUMN IF NOT EXISTS nota text NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE proforma ADD COLUMN IF NOT EXISTS recordado_en timestamptz")
    op.execute("ALTER TABLE proforma DROP CONSTRAINT IF EXISTS proforma_etapa")
    op.execute(
        "ALTER TABLE proforma ADD CONSTRAINT proforma_etapa CHECK "
        "(etapa IN ('borrador', 'enviada', 'adjudicada', 'perdida', 'descartada'))"
    )
    op.execute("ALTER TABLE proforma DROP CONSTRAINT IF EXISTS proforma_nota_corta")
    op.execute(
        "ALTER TABLE proforma ADD CONSTRAINT proforma_nota_corta CHECK (length(nota) <= 500)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_proforma_seguimiento "
        "ON proforma (negocio_id, etapa, creado_en DESC)"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION proformas_por_cerrar(horas integer)
            RETURNS TABLE (
                id_proforma   uuid,
                id_negocio    uuid,
                id_usuario    uuid,
                id_registro   uuid,
                titulo_texto  text,
                objeto_texto  text,
                entidad_texto text,
                cierra_en     timestamptz
            )
            LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp
            AS $cuerpo$
                SELECT p.id, p.negocio_id, p.usuario_id, p.registro_id,
                       p.titulo, p.objeto, p.entidad, r.plazo_proformas_en
                FROM proforma p
                JOIN registro r ON r.id = p.registro_id
                WHERE p.etapa = 'borrador'
                  AND p.recordado_en IS NULL
                  AND r.plazo_proformas_en > now()
                  AND r.plazo_proformas_en <= now() + make_interval(hours => horas)
                ORDER BY r.plazo_proformas_en
                LIMIT 500
            $cuerpo$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION alertas_activas()
            RETURNS SETOF alerta
            LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp
            AS $cuerpo$
                SELECT * FROM alerta WHERE activa ORDER BY creado_en
            $cuerpo$
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS alertas_activas()")
    op.execute("DROP FUNCTION IF EXISTS proformas_por_cerrar(integer)")
    op.execute("DROP INDEX IF EXISTS ix_proforma_seguimiento")
    op.execute("ALTER TABLE proforma DROP CONSTRAINT IF EXISTS proforma_nota_corta")
    op.execute("ALTER TABLE proforma DROP CONSTRAINT IF EXISTS proforma_etapa")
    for columna in ("recordado_en", "nota", "monto_adjudicado", "etapa_en", "etapa"):
        op.execute(f"ALTER TABLE proforma DROP COLUMN IF EXISTS {columna}")
