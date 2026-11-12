"""Los anexos (TDR, pliegos) también se guardan en la base, por su huella.

En Railway el API y el worker son servicios distintos y no comparten disco: el worker bajaba el
archivo a su carpeta y el API, al buscarlo en la suya, no lo encontraba, lo reabría y el worker lo
volvía a bajar sin fin. La proforma se quedaba en «preparando».

Ahora el worker deja una copia en `archivo_tdr` (clave: sha256, un archivo repetido se guarda una
vez) y el API la escribe en su disco la primera vez que la necesita. Son datos públicos del portal,
sin empresa: no llevan RLS, igual que `documento_tdr`. Se borran a los dos días (`purgar_archivos`).

Revision ID: 0042
Revises: 0041
"""

from __future__ import annotations

from alembic import op

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE archivo_tdr (
            sha256       text PRIMARY KEY,
            contenido    bytea NOT NULL,
            tamano_bytes integer NOT NULL,
            guardado_en  timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    # PDF, DOCX y ZIP ya vienen comprimidos: comprimirlos otra vez solo gasta CPU.
    op.execute("ALTER TABLE archivo_tdr ALTER COLUMN contenido SET STORAGE EXTERNAL")
    op.execute("CREATE INDEX ix_archivo_tdr_guardado ON archivo_tdr (guardado_en)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS archivo_tdr")
