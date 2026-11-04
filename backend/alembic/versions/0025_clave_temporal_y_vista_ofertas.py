"""Contraseña temporal y vista de ofertas con datos.

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-04

Dos cambios que vienen del mismo problema: el panel prometía cosas que el servidor no cumplía.

1. **`usuario.debe_cambiar_contrasena`.** Cuando un administrador asigna una contraseña a otra
   persona, esa contraseña la conocen dos. Hasta ahora nada obligaba a cambiarla, así que la
   contraseña «temporal» lo era solo de nombre. Con esta columna el servidor cierra el paso a los
   datos hasta que la persona elige una suya.

2. **Las concesiones de «contrataciones» pasan a «ofertas».** La pestaña Ofertas del panel lee la
   fuente OCDS, pero esa fuente la concedía la vista «contrataciones», que no tiene pestaña propia;
   «ofertas» no concedía nada. Conceder Ofertas no tenía ningún efecto y quitarla tampoco. Ahora
   «ofertas» concede OCDS, y para que nadie pierda lo que ya tenía se copia cada concesión vigente
   de «contrataciones» a «ofertas» con **el mismo vencimiento**: ni un día más ni uno menos.

La copia atraviesa todos los negocios, y `acceso_vista` tiene RLS forzada. Se levanta el `FORCE`
solo durante la copia —el propietario de la tabla vuelve a estar sujeto a las políticas en
cuanto termina— en lugar de abrir la política, que afectaría también a la aplicación.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COPIA_OFERTAS = """
    INSERT INTO acceso_vista (negocio_id, usuario_id, vista, plazo_codigo, otorgado_en, vence_en,
                              otorgado_por, motivo)
    SELECT c.negocio_id, c.usuario_id, 'ofertas', c.plazo_codigo, c.otorgado_en, c.vence_en,
           c.otorgado_por, 'copiada de contrataciones (0025)'
    FROM acceso_vista c
    WHERE c.vista = 'contrataciones'
      AND c.revocado_en IS NULL
      AND c.vence_en > now()
      AND NOT EXISTS (
          SELECT 1 FROM acceso_vista o
          WHERE o.usuario_id = c.usuario_id
            AND o.vista = 'ofertas'
            AND o.revocado_en IS NULL
            AND o.vence_en >= c.vence_en
      )
"""


def upgrade() -> None:
    op.execute(
        "ALTER TABLE usuario ADD COLUMN IF NOT EXISTS debe_cambiar_contrasena boolean "
        "NOT NULL DEFAULT false"
    )
    op.execute("ALTER TABLE acceso_vista NO FORCE ROW LEVEL SECURITY")
    op.execute(COPIA_OFERTAS)
    op.execute("ALTER TABLE acceso_vista FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE acceso_vista NO FORCE ROW LEVEL SECURITY")
    op.execute("DELETE FROM acceso_vista WHERE motivo = 'copiada de contrataciones (0025)'")
    op.execute("ALTER TABLE acceso_vista FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE usuario DROP COLUMN IF EXISTS debe_cambiar_contrasena")
