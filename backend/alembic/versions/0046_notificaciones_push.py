"""Notificaciones web (push) y avisos por perfil.

Hasta aquí un aviso solo se veía si la persona abría el panel. Ahora:

- `suscripcion_push`: cada navegador donde la persona pulsó «Activar notificaciones». Es de cada
  usuario y queda aislada por empresa como el resto (RLS).
- `aviso.notificado_en`: cuándo salió la notificación de ese aviso. Los avisos que ya existían se
  dan por notificados, para no mandar de golpe los de semanas atrás al activar esto.
- `aviso.origen = 'perfil'`: avisos que salen solos del perfil de la empresa (sus CPC y lo que
  ofrece), sin que la persona arme una alerta. Un índice único impide avisar dos veces del mismo
  proceso a la misma persona.
- Dos funciones `SECURITY DEFINER` para el worker, que trabaja sin contexto de empresa: con RLS
  forzada, una consulta suya no vería filas (mismo patrón que `alertas_activas()`, migración 0037).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0046"
down_revision: str | None = "0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONTEXTO = "NULLIF(current_setting('app.negocio_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("ALTER TABLE aviso ADD COLUMN IF NOT EXISTS notificado_en timestamptz")
    op.execute("ALTER TABLE aviso ADD COLUMN IF NOT EXISTS origen text")
    # Con RLS forzada y sin contexto, el UPDATE no vería filas: se suspende el forzado un momento,
    # igual que en la migración 0040.
    op.execute("ALTER TABLE aviso NO FORCE ROW LEVEL SECURITY")
    op.execute("UPDATE aviso SET notificado_en = creado_en WHERE notificado_en IS NULL")
    op.execute("ALTER TABLE aviso FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_aviso_perfil "
        "ON aviso (usuario_id, registro_id) WHERE origen = 'perfil'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_aviso_por_notificar "
        "ON aviso (creado_en) WHERE notificado_en IS NULL"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS suscripcion_push (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            negocio_id uuid NOT NULL REFERENCES negocio(id) ON DELETE CASCADE,
            usuario_id uuid NOT NULL REFERENCES usuario(id) ON DELETE CASCADE,
            endpoint text NOT NULL,
            p256dh text NOT NULL,
            auth text NOT NULL,
            avisar_perfil boolean NOT NULL DEFAULT true,
            perfil_revisado_en timestamptz,
            fallos integer NOT NULL DEFAULT 0,
            creado_en timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT suscripcion_push_endpoint_https CHECK (endpoint LIKE 'https://%'),
            CONSTRAINT suscripcion_push_largos CHECK (
                length(endpoint) <= 1000 AND length(p256dh) <= 200 AND length(auth) <= 100
            )
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_suscripcion_push_endpoint "
        "ON suscripcion_push (endpoint)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_suscripcion_push_usuario "
        "ON suscripcion_push (negocio_id, usuario_id)"
    )
    op.execute("ALTER TABLE suscripcion_push ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE suscripcion_push FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY aislamiento_suscripcion_push ON suscripcion_push
            USING (negocio_id = {CONTEXTO})
            WITH CHECK (negocio_id = {CONTEXTO})
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION suscripciones_push_activas()
            RETURNS SETOF suscripcion_push
            LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp
            AS $cuerpo$
                SELECT * FROM suscripcion_push ORDER BY creado_en
            $cuerpo$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION avisos_por_notificar(tope integer)
            RETURNS TABLE (
                id uuid, negocio_id uuid, usuario_id uuid, alerta_id uuid, registro_id uuid,
                titulo text, detalle text, origen text, creado_en timestamptz, alerta_nombre text
            )
            LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp
            AS $cuerpo$
                SELECT a.id, a.negocio_id, a.usuario_id, a.alerta_id, a.registro_id, a.titulo,
                       a.detalle, a.origen, a.creado_en, al.nombre
                FROM aviso a
                LEFT JOIN alerta al ON al.id = a.alerta_id
                WHERE a.notificado_en IS NULL
                  AND a.creado_en > now() - interval '1 day'
                  AND EXISTS (
                      SELECT 1 FROM suscripcion_push s
                      WHERE s.usuario_id = a.usuario_id AND s.negocio_id = a.negocio_id
                  )
                ORDER BY a.creado_en
                LIMIT tope
            $cuerpo$
        """
    )
    # Un navegador tiene una sola suscripción: si pasa a otra cuenta (dos personas en la misma
    # computadora), la fila de la cuenta anterior se borra, o le llegarían a esta persona las
    # oportunidades de la otra empresa. Esa fila es de otra empresa, así que hace falta saltar RLS.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION soltar_endpoint_ajeno(e text, negocio uuid, usuario uuid)
            RETURNS void
            LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp
            AS $cuerpo$
                DELETE FROM suscripcion_push
                WHERE endpoint = e AND (negocio_id <> negocio OR usuario_id <> usuario)
            $cuerpo$
        """
    )
    # Una función `SECURITY DEFINER` salta RLS: nadie más que el rol de la aplicación (migración
    # 0043) puede ejecutarla. Por defecto Postgres se la deja a PUBLIC.
    op.execute("REVOKE EXECUTE ON FUNCTION suscripciones_push_activas() FROM PUBLIC")
    op.execute("REVOKE EXECUTE ON FUNCTION avisos_por_notificar(integer) FROM PUBLIC")
    op.execute("REVOKE EXECUTE ON FUNCTION soltar_endpoint_ajeno(text, uuid, uuid) FROM PUBLIC")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'contratacion_app') THEN
                GRANT EXECUTE ON FUNCTION suscripciones_push_activas() TO contratacion_app;
                GRANT EXECUTE ON FUNCTION avisos_por_notificar(integer) TO contratacion_app;
                GRANT EXECUTE ON FUNCTION soltar_endpoint_ajeno(text, uuid, uuid)
                    TO contratacion_app;
                GRANT SELECT, INSERT, UPDATE, DELETE ON suscripcion_push TO contratacion_app;
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS soltar_endpoint_ajeno(text, uuid, uuid)")
    op.execute("DROP FUNCTION IF EXISTS avisos_por_notificar(integer)")
    op.execute("DROP FUNCTION IF EXISTS suscripciones_push_activas()")
    op.execute("DROP TABLE IF EXISTS suscripcion_push")
    op.execute("DROP INDEX IF EXISTS ix_aviso_por_notificar")
    op.execute("DROP INDEX IF EXISTS ux_aviso_perfil")
    op.execute("ALTER TABLE aviso DROP COLUMN IF EXISTS origen")
    op.execute("ALTER TABLE aviso DROP COLUMN IF EXISTS notificado_en")
