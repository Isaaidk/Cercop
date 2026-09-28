"""Resolución de la cuenta a partir del correo, para poder iniciar sesión.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-27

El problema que resuelve
------------------------
Para iniciar sesión hay que leer `usuario`, y `usuario` está protegido por RLS. Las políticas comparan
`negocio_id` con el negocio del contexto, y en el momento del inicio de sesión **todavía no se sabe a
qué negocio pertenece quien llama**: es exactamente lo que se está averiguando. Sin contexto, la
consulta no devuelve ninguna fila y el inicio de sesión sería imposible.

Las salidas malas eran dos y conviene descartarlas de forma explícita:

- **Quitar RLS de `usuario`.** Anularía el aislamiento de la tabla más sensible del sistema para
  arreglar un solo caso.
- **Conectar la aplicación con un rol que se salte RLS.** Anularía el aislamiento de *todas* las
  tablas, no solo de esta.

La salida buena es una función `SECURITY DEFINER` que devuelve **dos identificadores y nada más**.
Desde fuera, lo único que se puede obtener de más es el par correo → identificadores. Ni contraseñas,
ni correo, ni nombre, ni rol, ni estado. Con esos dos identificadores la aplicación fija el contexto de
negocio y lee la fila completa por la vía normal, con RLS aplicándose como en cualquier otra consulta.

Sobre enumerar usuarios
-----------------------
La función responde a cualquier correo, así que por sí sola permitiría averiguar qué correos tienen
cuenta. Eso se contiene en el caso de uso, no aquí: el mismo mensaje y el mismo tiempo de respuesta
para «no existe» y para «contraseña incorrecta». Es la única forma de que la comprobación sea honesta:
si la función mintiera, el caso de uso no podría distinguir los dos casos que sí necesita distinguir.

`SET search_path` explícito es obligatorio en una función `SECURITY DEFINER`: sin él, un esquema
colocado antes en la ruta podría suplantar las tablas que la función consulta.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Los nombres de salida son distintos de los de las columnas a propósito: si coincidieran, en
    # PostgreSQL quedarían ambiguos dentro del cuerpo de la función.
    op.execute(
        """
        CREATE FUNCTION resolver_cuenta(p_email text)
            RETURNS TABLE (id_usuario uuid, id_negocio uuid)
            LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp
            AS $cuerpo$
                SELECT u.id, u.negocio_id
                FROM usuario u
                WHERE lower(u.email) = lower(btrim(p_email))
                ORDER BY u.creado_en
                LIMIT 1;
            $cuerpo$
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS resolver_cuenta(text)")
