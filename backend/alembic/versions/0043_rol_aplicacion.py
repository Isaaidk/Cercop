"""Rol de aplicación sin superusuario: el aislamiento entre empresas lo garantiza la base (S-01).

Con el usuario administrador, PostgreSQL **no aplica** las políticas de RLS: que una empresa no vea
lo de otra dependía solo de que cada consulta llevara su `WHERE negocio_id`. Con este rol
(`NOSUPERUSER NOBYPASSRLS`) la base filtra por `app.negocio_id` aunque una consulta lo olvide.

La migración corre con el administrador (`DATABASE_URL_MIGRACIONES`, ver `alembic/env.py`). La clave
del rol llega por `CLAVE_ROL_APP` y no se escribe en el repositorio. Sin esa variable (desarrollo)
solo se ajustan las funciones; el rol se puede crear después con docs/38 §3.

Además:

- `asegurar_particiones()` crea particiones, y eso solo lo puede hacer el dueño de la tabla: pasa a
  `SECURITY DEFINER` (corre con los permisos de quien la creó) con `search_path` fijo.
- S-19: las funciones `SECURITY DEFINER` dejan de ser ejecutables por cualquier rol (`PUBLIC`) y
  solo las ejecuta el rol de aplicación (y el administrador, que es su dueño).

Revision ID: 0043
Revises: 0042
"""

from __future__ import annotations

import os
import re

from alembic import op

revision: str = "0043"
down_revision: str | None = "0042"
branch_labels = None
depends_on = None

ROL = "contratacion_app"


def upgrade() -> None:
    op.execute("ALTER FUNCTION asegurar_particiones() SECURITY DEFINER")
    op.execute("ALTER FUNCTION asegurar_particiones() SET search_path = public, pg_temp")

    clave = os.environ.get("CLAVE_ROL_APP", "").strip()
    if not clave:
        return
    # Solo caracteres que no necesitan escaparse dentro del literal SQL.
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", clave):
        raise ValueError("CLAVE_ROL_APP: 32 a 128 caracteres de [A-Za-z0-9_-].")

    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROL}') THEN
                ALTER ROLE {ROL} LOGIN PASSWORD '{clave}'
                    NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
            ELSE
                CREATE ROLE {ROL} LOGIN PASSWORD '{clave}'
                    NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
            END IF;
            EXECUTE format('GRANT CONNECT ON DATABASE %I TO {ROL}', current_database());
        END $$
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {ROL}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {ROL}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {ROL}")
    # Lo que creen las migraciones futuras (y las particiones nuevas), con el mismo administrador.
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {ROL}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {ROL}"
    )
    op.execute(
        f"""
        DO $$
        DECLARE f regprocedure;
        BEGIN
            FOR f IN SELECT p.oid::regprocedure FROM pg_proc p
                     JOIN pg_namespace n ON n.oid = p.pronamespace
                     WHERE n.nspname = 'public' AND p.prosecdef
            LOOP
                EXECUTE format('REVOKE EXECUTE ON FUNCTION %s FROM PUBLIC', f);
                EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO {ROL}', f);
            END LOOP;
        END $$
        """
    )


def downgrade() -> None:
    # El rol no se borra: la API puede estar conectada con él. Se devuelve la función a su estado.
    op.execute("ALTER FUNCTION asegurar_particiones() SECURITY INVOKER")
    op.execute("ALTER FUNCTION asegurar_particiones() RESET search_path")
