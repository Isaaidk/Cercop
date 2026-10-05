"""Plantilla de Excel propia de cada empresa.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-28

Para qué sirve esta tabla
-------------------------
Cada empresa puede subir **su** plantilla de Excel —con su logo, sus hojas y sus estilos— y las
exportaciones se generan rellenando esa plantilla en lugar de un libro genérico. Sin esta tabla no
habría forma de saber qué plantilla es de quién.

Por qué la clave primaria es `negocio_id`
-----------------------------------------
Y no un identificador propio con un `UNIQUE`. Es la forma de que la regla «**una plantilla por
empresa, y volver a subir reemplaza la anterior**» la garantice la base de datos y no el código: con
`negocio_id` como clave, un `INSERT ... ON CONFLICT` reemplaza, y no existe la posibilidad de que un
descuido deje dos plantillas para la misma empresa y la exportación use la equivocada. Es la misma
decisión que en el resto del proyecto: lo que no puede pasar no se deja en manos de que alguien se
acuerde.

Por qué el archivo **no** se guarda aquí
----------------------------------------
La fila guarda la **ruta** del archivo, no su contenido. Un `.xlsx` con logo pesa cientos de
kilobytes, y meterlo en la base lo haría viajar entero en cada copia de seguridad diaria —todos los
días, para siempre— y engordaría cada restauración de prueba. El objeto vive en un directorio del
servidor y aquí queda solo la referencia y la huella, que es lo que permite detectar que el archivo
del disco no es el que la fila dice.

`hash_contenido` no es decorativo: si alguien mueve o edita el archivo por fuera de la aplicación, la
huella deja de coincidir y se puede avisar en vez de generar un Excel con una plantilla que ya no es
la que se subió.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONTEXTO = "current_setting('app.negocio_id', true)::uuid"


def _ejecutar(sql: str) -> None:
    """Ejecuta un bloque SQL sentencia a sentencia (asyncpg no admite varias por consulta)."""
    for sentencia in sql.split(";"):
        limpia = sentencia.strip()
        if limpia:
            op.execute(limpia)


def upgrade() -> None:
    _ejecutar(
        """
        CREATE TABLE plantilla_excel (
            negocio_id     uuid PRIMARY KEY REFERENCES negocio(id) ON DELETE CASCADE,
            nombre_archivo text NOT NULL,
            ruta           text NOT NULL,
            hash_contenido text NOT NULL,
            tamano_bytes   integer NOT NULL CHECK (tamano_bytes > 0),
            subida_por     uuid REFERENCES usuario(id) ON DELETE SET NULL,
            creado_en      timestamptz NOT NULL DEFAULT now(),
            actualizado_en timestamptz NOT NULL DEFAULT now()
        );

        COMMENT ON TABLE plantilla_excel IS
            'Plantilla de Excel de cada empresa. El archivo esta en disco, aqui solo la referencia';
        """
    )

    # El aislamiento se aplica en el mismo sitio y con la misma forma que en el resto del plano de
    # negocio: `FORCE` para que valga también para el propietario de la tabla, y `WITH CHECK` para que
    # nadie pueda **escribir** una fila a nombre de otra empresa, no solo leerla.
    _ejecutar(
        f"""
        ALTER TABLE plantilla_excel ENABLE ROW LEVEL SECURITY;
        ALTER TABLE plantilla_excel FORCE ROW LEVEL SECURITY;
        CREATE POLICY aislamiento_plantilla_excel ON plantilla_excel
            USING (negocio_id = {CONTEXTO})
            WITH CHECK (negocio_id = {CONTEXTO});
        """
    )


def downgrade() -> None:
    _ejecutar(
        """
        DROP POLICY IF EXISTS aislamiento_plantilla_excel ON plantilla_excel;
        ALTER TABLE plantilla_excel NO FORCE ROW LEVEL SECURITY;
        ALTER TABLE plantilla_excel DISABLE ROW LEVEL SECURITY;
        DROP TABLE IF EXISTS plantilla_excel;
        """
    )
