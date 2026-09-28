"""Listado de empresas para el superadministrador de la plataforma.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-27

El problema que resuelve
------------------------
El dueño de la plataforma tiene que poder **ver todas las empresas** para darles acceso o
suspenderlas. Pero `negocio` está protegida por RLS con `FORCE`, y su política es `id = contexto`:
sin un negocio en el contexto no devuelve ninguna fila. Y aquí el problema es justo el contrario del
de `resolver_cuenta`: no es que no sepamos a qué negocio pertenece quien llama, es que queremos ver
**todos** a la vez.

Las salidas malas vuelven a ser las mismas dos, y por las mismas razones:

- **Quitar RLS de `negocio`.** Dejaría a cualquier empresa leer los datos de contacto y el estado de
  las demás con una consulta normal.
- **Conectar la aplicación con un rol que se salte RLS.** Anularía el aislamiento de todas las
  tablas. Es exactamente el riesgo R-05 que sigue abierto: el rol actual tiene `rolbypassrls`, así
  que **hoy esta función no es la que protege nada** —lo hace el rol— y el día que se cree el rol
  de aplicación sin privilegios, será esta función la que sostenga el aislamiento. Escribirla ahora
  es lo que permite cerrar R-05 sin romper la administración.

La función es `SECURITY DEFINER` y devuelve solo lo que el panel de plataforma necesita: identidad y
estado de la empresa, y **cuántas cuentas tiene**, nunca quiénes son ni sus correos. Aun así, quien
puede llamarla ve todas las empresas, así que la comprobación de rol vive en el caso de uso, que es
el único sitio desde el que se llama.

`SET search_path` explícito es obligatorio en una función `SECURITY DEFINER`: sin él, un esquema
colocado antes en la ruta podría suplantar las tablas que la función consulta.

Por qué los nombres de salida van prefijados
--------------------------------------------
Los parámetros de salida de `RETURNS TABLE` son variables dentro del cuerpo de la función. Si se
llamaran igual que las columnas, cualquier referencia quedaría ambigua y PostgreSQL rechaza la
función al crearla —o, peor, resuelve a la variable y devuelve siempre lo mismo—.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCION = """
    CREATE FUNCTION listar_negocios()
        RETURNS TABLE (
            id_negocio          uuid,
            nombre_empresa      text,
            ruc_empresa         text,
            estado_empresa      text,
            plan_empresa        text,
            limite_cuentas      integer,
            correo_contacto     text,
            telefono_contacto   text,
            direccion_empresa   text,
            ciudad_empresa      text,
            creada_en           timestamptz,
            cuentas             integer,
            cuentas_activas     integer
        )
        LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp
        AS $cuerpo$
            SELECT n.id,
                   n.nombre,
                   n.ruc,
                   n.estado,
                   n.plan,
                   n.limite_usuarios,
                   n.email_contacto,
                   n.telefono,
                   n.direccion,
                   n.ciudad,
                   n.creado_en,
                   count(u.id)::integer,
                   count(u.id) FILTER (WHERE u.estado = 'activo')::integer
            FROM negocio n
            LEFT JOIN usuario u ON u.negocio_id = n.id
            GROUP BY n.id
            ORDER BY n.creado_en DESC
        $cuerpo$;
"""


def upgrade() -> None:
    op.execute(FUNCION)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS listar_negocios();")
