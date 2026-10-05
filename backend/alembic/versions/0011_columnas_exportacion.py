"""Columnas que lleva el Excel de cada empresa.

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-29

Para qué sirve esta tabla
-------------------------
Cada empresa puede elegir qué columnas salen en sus exportaciones —la del objeto de compra sí, la
del funcionario no— y esa decisión tiene que valer para **todas** las descargas y para todos sus
usuarios, no solo para quien la tomó. Sin esta tabla, la elección viviría en el navegador de una
persona y el compañero de al lado seguiría descargando el archivo entero.

Por qué va aparte de `plantilla_excel`
--------------------------------------
Son dos decisiones independientes y la pantalla lo demuestra: una empresa sin plantilla —que exporta
el libro genérico— también quiere poder acortar sus columnas. Si la selección viviera en la fila de
la plantilla, no se podría elegir nada hasta subir un `.xlsx`, y eso mezclaría dos cosas que no
tienen relación: cómo se ve el archivo y qué datos lleva.

Por qué se guardan claves y no posiciones ni etiquetas
------------------------------------------------------
Las etiquetas son del idioma de la interfaz y las posiciones son de cada plantilla. Guardar
cualquiera de las dos ataría la selección al archivo del día que se hizo: al reordenar una columna
en la plantilla, el archivo saldría con otras columnas y nadie habría tocado la selección. Una clave
como `objeto_compra` significa lo mismo hoy y dentro de un año.

Por qué la clave primaria es `negocio_id`
-----------------------------------------
La misma decisión que en `plantilla_excel`: **una selección por empresa**, garantizada por la base y
no por el código. Con `negocio_id` como clave, un `INSERT ... ON CONFLICT` reemplaza, y no existe la
posibilidad de que un descuido deje dos selecciones y la exportación use la que nadie espera.

Qué significa una lista vacía
-----------------------------
«Todas las columnas». No es lo mismo que no tener fila —que es «no se ha elegido nunca»— pero el
resultado al exportar sí lo es, y por eso la distinción no se pierde: la pantalla puede decir «no
has elegido columnas, salen todas» sin inventarse un estado.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
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
        CREATE TABLE exportacion_columnas (
            negocio_id      uuid PRIMARY KEY REFERENCES negocio(id) ON DELETE CASCADE,
            columnas        text[] NOT NULL,
            actualizado_por uuid REFERENCES usuario(id) ON DELETE SET NULL,
            actualizado_en  timestamptz NOT NULL DEFAULT now()
        );

        COMMENT ON TABLE exportacion_columnas IS
            'Columnas que cada empresa quiere en sus exportaciones. Vacio significa todas';
        """
    )

    # El aislamiento, con la misma forma que en el resto del plano de negocio: `FORCE` para que
    # valga también para el propietario de la tabla y `WITH CHECK` para que nadie pueda escribir una
    # fila a nombre de otra empresa, no solo leerla.
    _ejecutar(
        f"""
        ALTER TABLE exportacion_columnas ENABLE ROW LEVEL SECURITY;
        ALTER TABLE exportacion_columnas FORCE ROW LEVEL SECURITY;
        CREATE POLICY aislamiento_exportacion_columnas ON exportacion_columnas
            USING (negocio_id = {CONTEXTO})
            WITH CHECK (negocio_id = {CONTEXTO});
        """
    )


def downgrade() -> None:
    _ejecutar(
        """
        DROP POLICY IF EXISTS aislamiento_exportacion_columnas ON exportacion_columnas;
        ALTER TABLE exportacion_columnas NO FORCE ROW LEVEL SECURITY;
        ALTER TABLE exportacion_columnas DISABLE ROW LEVEL SECURITY;
        DROP TABLE IF EXISTS exportacion_columnas;
        """
    )
