"""Políticas de aislamiento tolerantes al contexto vacío.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-27

El problema que corrige esta migración
--------------------------------------
Las políticas de la migración 0002 comparaban `negocio_id` con

    current_setting('app.negocio_id', true)::uuid

y asumían que, cuando el contexto no está definido, la expresión devuelve `NULL` y la comparación
deniega. **Eso no es cierto en cuanto la variable se ha fijado una vez en la sesión.**

Una variable de configuración propia, una vez establecida, deja un marcador en la sesión. Al revertirse
el `SET LOCAL` (que es lo correcto: el valor solo debe durar la transacción), el marcador se queda con
valor **vacío**, no inexistente. A partir de ahí:

- `current_setting('app.negocio_id', true)` devuelve `''`, no `NULL`;
- `''::uuid` **no** es `NULL`, es un error de conversión.

El efecto real, con un grupo de conexiones reutilizándolas, es que la segunda petición que llega por
una conexión ya usada **falla con un error de servidor** en lugar de denegar el acceso. Es decir: en
lugar de un sistema seguro, había un sistema que se rompía — y que además fallaba del lado ruidoso,
que a largo plazo esconde el verdadero problema.

La corrección
-------------
`NULLIF(current_setting('app.negocio_id', true), '')::uuid` convierte el valor vacío en `NULL`. Ahora
sí: sin contexto, la comparación es nula y **no se devuelve ninguna fila**. Denegar por defecto, como
decía la documentación, y esta vez de verdad.

No se edita la migración 0002 aunque fuera la que introdujo la expresión: una migración ya aplicada no
se reescribe, porque en otro entorno ya se ejecutó y no volvería a hacerlo. El cambio se hace aquí.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Expresión tolerante: el contexto ausente o vacío equivale a «sin negocio», que deniega.
CONTEXTO = "NULLIF(current_setting('app.negocio_id', true), '')::uuid"

# Expresión original, solo para poder revertir la migración.
CONTEXTO_ANTERIOR = "current_setting('app.negocio_id', true)::uuid"

# Tablas cuyo filtro es directamente `negocio_id`.
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
    "acceso_vista",
)


def _ejecutar(sql: str) -> None:
    """Ejecuta un bloque SQL sentencia a sentencia (asyncpg no admite varias por consulta)."""
    for sentencia in sql.split(";"):
        limpia = sentencia.strip()
        if limpia:
            op.execute(limpia)


def _reemplazar(contexto: str) -> None:
    """Recrea todas las políticas con la expresión indicada."""
    _ejecutar(
        f"""
        DROP POLICY IF EXISTS aislamiento_negocio ON negocio;
        CREATE POLICY aislamiento_negocio ON negocio
            USING (id = {contexto})
            WITH CHECK (id = {contexto});
        """
    )

    for tabla in TABLAS_CON_NEGOCIO:
        _ejecutar(
            f"""
            DROP POLICY IF EXISTS aislamiento_{tabla} ON {tabla};
            CREATE POLICY aislamiento_{tabla} ON {tabla}
                USING (negocio_id = {contexto})
                WITH CHECK (negocio_id = {contexto});
            """
        )

    _ejecutar(
        f"""
        DROP POLICY IF EXISTS aislamiento_conjunto_termino ON conjunto_termino;
        CREATE POLICY aislamiento_conjunto_termino ON conjunto_termino
            USING (EXISTS (
                SELECT 1 FROM conjunto_terminos c
                WHERE c.id = conjunto_termino.conjunto_id AND c.negocio_id = {contexto}
            ))
            WITH CHECK (EXISTS (
                SELECT 1 FROM conjunto_terminos c
                WHERE c.id = conjunto_termino.conjunto_id AND c.negocio_id = {contexto}
            ));
        """
    )


def upgrade() -> None:
    _reemplazar(CONTEXTO)


def downgrade() -> None:
    _reemplazar(CONTEXTO_ANTERIOR)
