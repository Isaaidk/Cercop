"""Créditos de IA: cada empresa empieza con 100 (antes 30).

El regalo de bienvenida pasó de 30 a 100 (`dominio/creditos.py::REGALO_INICIAL`). Las empresas que
ya existían (todas nacieron con 30) reciben la diferencia, una sola vez, con su movimiento a la
vista en «Créditos».

Las tablas tienen RLS forzado, que también aplica al dueño de la tabla cuando no es superusuario
(así corren las migraciones con el rol propietario, ver docs/38 §3). Sin contexto de empresa la
actualización no vería ninguna fila: el forzado se suspende solo durante el ajuste y se repone en la
misma transacción.

Revision ID: 0041
Revises: 0040
"""

from __future__ import annotations

from alembic import op

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels = None
depends_on = None

_MOTIVO = "Ajuste: bienvenida de 100 créditos"


def upgrade() -> None:
    op.execute("ALTER TABLE saldo_ia NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE movimiento_ia NO FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        WITH elegibles AS (
            -- Todo saldo que ya existía nació con el regalo viejo de 30 (algunas empresas no tienen
            -- su movimiento de bienvenida: se abrió antes de registrar movimientos). Una sola vez.
            SELECT s.negocio_id
            FROM saldo_ia s
            WHERE NOT EXISTS (
                SELECT 1 FROM movimiento_ia y
                WHERE y.negocio_id = s.negocio_id AND y.motivo = '{_MOTIVO}'
            )
        ),
        sumados AS (
            UPDATE saldo_ia s SET disponibles = s.disponibles + 70
            FROM elegibles e WHERE s.negocio_id = e.negocio_id
            RETURNING s.negocio_id
        )
        INSERT INTO movimiento_ia (negocio_id, tipo, cantidad, motivo)
        SELECT negocio_id, 'regalo', 70, '{_MOTIVO}' FROM sumados
        """
    )
    op.execute("ALTER TABLE movimiento_ia FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE saldo_ia FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    # Los créditos regalados pudieron gastarse ya: no se quitan. Solo se deja de marcar el ajuste.
    return None
