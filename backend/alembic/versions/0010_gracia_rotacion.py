"""Ventana de gracia en la rotación del token de renovación.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-29

El problema que resuelve, con el dato delante
---------------------------------------------
La rotación con detección de reutilización cierra **todas** las sesiones de una cuenta en cuanto ve
el mismo token de renovación dos veces. Es la respuesta correcta ante un robo, y era la respuesta
equivocada ante una **respuesta perdida**: si el servidor rota el token y la respuesta no llega al
navegador —corta el wifi, se duerme el portátil, el proxy corta la conexión—, el cliente se queda
con el token viejo y lo reintenta. El servidor ve el token viejo, lo interpreta como «hay dos copias
en circulación» y echa a la persona de la cuenta.

No es una hipótesis: en la tabla de sesiones hay tres cierres con motivo `reuso_detectado` en un día,
en la cuenta de una sola persona que estaba usando el panel. Desde fuera se ve como «de vez en cuando
me saca y me dice algo de tokens», que es exactamente lo que no se puede explicar a un usuario.

Qué añade esta migración
------------------------
Dos columnas en `sesion` que permiten **recordar la huella anterior y cuándo dejó de ser la actual**:

- `refresh_hash_anterior`: la huella que había justo antes de la última rotación.
- `refresh_anterior_desde`: el instante en que se rotó.

Con eso, la comprobación pasa a tener tres finales en lugar de dos:

1. La huella presentada es la actual → rotación normal.
2. La huella presentada es **la anterior y dentro de la ventana** → se acepta. Es un reintento, o la
   segunda pestaña del mismo navegador, no un robo.
3. Cualquier otra cosa → reutilización: se cierran todas las sesiones de la cuenta.

Por qué una ventana corta no debilita la detección
--------------------------------------------------
Lo que se pierde es la capacidad de detectar la reutilización **solo durante esos segundos** después
de una rotación, que es justo el tiempo en que un reintento legítimo es indistinguible de un robo. Un
token robado que se use un minuto después sigue disparando el cierre de todo, porque la columna
guarda **una sola** generación hacia atrás: no es una lista de tokens válidos que se va acumulando,
son dos huecos que se desplazan.

Por qué la ventana vive en la base y no en la memoria intermedia
---------------------------------------------------------------
Porque es una decisión de seguridad. Si dependiera de Redis, una caída del almacén cambiaría el
comportamiento —volvería a cerrar sesiones por reintentos— y el fallo aparecería justo cuando el
sistema ya está teniendo problemas. La comprobación tiene que dar la misma respuesta con el almacén
encendido y apagado.

Por qué las columnas admiten nulos
----------------------------------
Una sesión recién creada no tiene rotación anterior, y las sesiones que ya existen cuando se aplica
esta migración tampoco. Con `NULL` en las dos, la comprobación cae en el caso 3 para cualquier huella
que no sea la actual, que es el comportamiento de antes: no hay ninguna sesión que quede en un estado
ambiguo.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ejecutar(sql: str) -> None:
    """Ejecuta un bloque SQL sentencia a sentencia (asyncpg no admite varias por consulta)."""
    for sentencia in sql.split(";"):
        limpia = sentencia.strip()
        if limpia:
            op.execute(limpia)


def upgrade() -> None:
    # Sin `;` dentro de los literales de `COMMENT`: el ejecutor parte el bloque por punto y coma y un
    # punto y coma suelto dentro de una comilla corta la sentencia por la mitad.
    _ejecutar(
        """
        ALTER TABLE sesion ADD COLUMN IF NOT EXISTS refresh_hash_anterior text;
        ALTER TABLE sesion ADD COLUMN IF NOT EXISTS refresh_anterior_desde timestamptz;

        COMMENT ON COLUMN sesion.refresh_hash_anterior IS
            'Huella del token de renovacion justo antes de la ultima rotacion, para admitir reintentos';
        COMMENT ON COLUMN sesion.refresh_anterior_desde IS
            'Instante de la ultima rotacion, que acota la ventana en la que la huella anterior vale';
        """
    )


def downgrade() -> None:
    _ejecutar(
        """
        ALTER TABLE sesion DROP COLUMN IF EXISTS refresh_anterior_desde;
        ALTER TABLE sesion DROP COLUMN IF EXISTS refresh_hash_anterior;
        """
    )
