"""Aislamiento entre negocios mediante Row Level Security.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-27

Por qué existe esta migración
-----------------------------
El aislamiento multi-tenant **no puede depender de que el código recuerde añadir un `WHERE`**: un
solo descuido expone los datos de un cliente a otro. Aquí lo garantiza el motor de base de datos.

Tres condiciones son imprescindibles y las tres se cumplen aquí:

1. `ENABLE ROW LEVEL SECURITY` — activa las políticas.
2. `FORCE ROW LEVEL SECURITY` — las aplica **también al propietario** de la tabla.
3. La aplicación debe conectarse con un rol **no superusuario** y **sin `BYPASSRLS`**. Los superusuarios
   ignoran RLS por completo, así que conectarse como `postgres` anularía todo esto.

El contexto se establece por transacción con `SET LOCAL app.negocio_id`, y el identificador sale
siempre del token del usuario, nunca de un parámetro que el cliente pueda manipular. Si el contexto
no está definido, `current_setting(..., true)` devuelve `NULL`, las comparaciones resultan `NULL` y
**no se devuelve ninguna fila**: el comportamiento por defecto es denegar.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tablas que llevan negocio_id directamente.
TABLAS_CON_NEGOCIO = (
    "usuario",
    "sesion",
    "suscripcion_termino",
    "conjunto_terminos",
    "filtro_guardado",
    "exportacion",
    "consentimiento",
    "solicitud_arco",
    "auditoria",
)

CONTEXTO = "current_setting('app.negocio_id', true)::uuid"


def _ejecutar(sql: str) -> None:
    """Ejecuta un bloque SQL sentencia a sentencia (asyncpg no admite varias por consulta)."""
    for sentencia in sql.split(";"):
        limpia = sentencia.strip()
        if limpia:
            op.execute(limpia)


def upgrade() -> None:
    # `negocio` se filtra por su propia clave primaria.
    _ejecutar(
        f"""
        ALTER TABLE negocio ENABLE ROW LEVEL SECURITY;
        ALTER TABLE negocio FORCE ROW LEVEL SECURITY;
        CREATE POLICY aislamiento_negocio ON negocio
            USING (id = {CONTEXTO})
            WITH CHECK (id = {CONTEXTO});
        """
    )

    for tabla in TABLAS_CON_NEGOCIO:
        _ejecutar(
            f"""
            ALTER TABLE {tabla} ENABLE ROW LEVEL SECURITY;
            ALTER TABLE {tabla} FORCE ROW LEVEL SECURITY;
            CREATE POLICY aislamiento_{tabla} ON {tabla}
                USING (negocio_id = {CONTEXTO})
                WITH CHECK (negocio_id = {CONTEXTO});
            """
        )

    # `conjunto_termino` no lleva negocio_id: hereda el aislamiento de su conjunto.
    _ejecutar(
        f"""
        ALTER TABLE conjunto_termino ENABLE ROW LEVEL SECURITY;
        ALTER TABLE conjunto_termino FORCE ROW LEVEL SECURITY;
        CREATE POLICY aislamiento_conjunto_termino ON conjunto_termino
            USING (EXISTS (
                SELECT 1 FROM conjunto_terminos c
                WHERE c.id = conjunto_termino.conjunto_id AND c.negocio_id = {CONTEXTO}
            ))
            WITH CHECK (EXISTS (
                SELECT 1 FROM conjunto_terminos c
                WHERE c.id = conjunto_termino.conjunto_id AND c.negocio_id = {CONTEXTO}
            ));
        """
    )


def downgrade() -> None:
    for tabla in (*TABLAS_CON_NEGOCIO, "conjunto_termino", "negocio"):
        _ejecutar(
            f"""
            DROP POLICY IF EXISTS aislamiento_{tabla} ON {tabla};
            ALTER TABLE {tabla} NO FORCE ROW LEVEL SECURITY;
            ALTER TABLE {tabla} DISABLE ROW LEVEL SECURITY;
            """
        )
