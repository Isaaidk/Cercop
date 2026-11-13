"""Índices que faltaban en dos lecturas de cada empresa (docs/41).

- `usuario (negocio_id)`: la lista de cuentas de la empresa, sus dos recuentos (margen del plan) y
  la de accesos filtran por `negocio_id`, y la tabla solo tenía índices por `id` y por correo. Cada
  vez que un administrador abría «Usuarios» se recorría la tabla de **todas** las empresas.
- `compra_ia (negocio_id, creado_en DESC)`: las últimas compras de la empresa salen en cada lectura
  del saldo de IA (inicio del asistente, pantalla de créditos), con `ORDER BY creado_en DESC LIMIT
  10`. Solo había un índice por `(estado, creado_en)`, el de la cola de la plataforma.

`CREATE INDEX` normal y **no** `CONCURRENTLY`: en este proyecto el concurrente se queda esperando a
la transacción larga del worker y cuelga el despliegue. Las dos tablas son pequeñas (una fila por
persona y una por compra), así que el bloqueo de escritura dura milisegundos. `IF NOT EXISTS` deja
volver a lanzar la migración sin error.

Revision ID: 0045
Revises: 0044
"""

from __future__ import annotations

from alembic import op

revision: str = "0045"
down_revision: str | None = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_usuario_negocio ON usuario (negocio_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_compra_ia_negocio_creado "
        "ON compra_ia (negocio_id, creado_en DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_compra_ia_negocio_creado")
    op.execute("DROP INDEX IF EXISTS ix_usuario_negocio")
