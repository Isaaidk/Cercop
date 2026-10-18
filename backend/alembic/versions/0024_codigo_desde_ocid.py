"""Rellena el código del proceso en las filas que el listado guardó sin él.

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-18

El problema
-----------
El código canónico sale del campo `title` del payload. El listado paginado del worker no siempre lo
trae —en las publicaciones más recientes llega vacío, o con el propio `ocid`—, así que la fila se
guardó **sin `codigo`**. Medido sobre el histórico el 2026-10-18: **198 filas** de OCDS.

El efecto visible era el peor de los posibles: en la tabla de ofertas esas filas salían con «—» en
la columna del código y sin Código CercoApp, y además no se podían encontrar pegando su
identificador, porque el buscador compara contra ese mismo campo.

Las filas están así desde que se guardaron, no se corrompieron después: se comprobó el `crudo` de
una de ellas y el payload original ya venía sin `description` ni `budget`. Por eso esto es un
relleno y no una reparación de algo perdido.

De dónde sale el valor
----------------------
Del `ocid`, que la propia fuente publica y que **contiene** el código:
`ocds-5wno2w-SIE-UC-2026-059-30951`. No se inventa nada, y la forma es la misma que la del código de
las demás filas, que es lo que mantiene coherentes la columna, el buscador y el Excel.

Por qué solo esas 198
---------------------
La condición es exactamente el hueco: sin `codigo` y con `ocid`. Las demás filas no se tocan, ni
siquiera las que llevan el prefijo `ocds-…` en el código: ese prefijo lo quita el «Código CercoApp»
al mostrarlo, y reescribirlo aquí obligaría a recalcular su texto de búsqueda sin ganar nada.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Solo las filas del hueco: sin código y con un `ocid` del que sacarlo.
RELLENO = """
    UPDATE registro
    SET datos = datos || jsonb_build_object('codigo', datos ->> 'ocid')
    WHERE coalesce(datos ->> 'codigo', '') = ''
      AND coalesce(datos ->> 'ocid', '') <> ''
"""


def upgrade() -> None:
    op.execute(RELLENO)


def downgrade() -> None:
    """Devuelve las filas a como estaban: quita el código cuando es igual al `ocid`.

    Es reversible sin ambigüedad: solo se retira el campo de las filas donde el valor es
    exactamente el `ocid`, que es la marca de que lo puso esta migración. Una fila cuyo código
    coincida con su `ocid` por casualidad —porque la fuente lo publicó así— se quedaría sin código,
    y por eso se avisa: es preferible a dejar un `downgrade` que no deshace nada.
    """
    op.execute(
        sa.text(
            """
            UPDATE registro
            SET datos = datos - 'codigo'
            WHERE datos ->> 'codigo' = datos ->> 'ocid'
            """
        )
    )
