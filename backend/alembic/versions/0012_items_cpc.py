"""Ítems de la necesidad con su CPC, para poder buscar por clasificación.

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-29

Por qué existe esta migración
-----------------------------
El listado de necesidades publica el objeto de compra como **texto libre** —lo que escribió la
entidad— y nada más. Buscar una palabra en ese texto devuelve todo lo que la menciona, tenga o no
que ver con lo que se busca: quien vigila «lavado» recibe desde un servicio de lavado de vehículos
hasta una capacitación sobre prevención de lavado de activos. El CPC es la clasificación
**normalizada** del Estado y solo viaja en la ficha de cada necesidad, así que hay que ir a buscarlo
y guardarlo.

Sus cuatro columnas nuevas, y por qué cada una
----------------------------------------------
- **`items`** — la tabla de la ficha tal cual: código, nombre del CPC, descripción del producto,
  unidad y cantidad. Se guarda entera porque es lo que la persona necesita ver al abrir el detalle:
  saber que una necesidad coincide por CPC sin poder leer *qué* se compra obliga a salir al portal.
- **`cpc_busqueda`** — el texto normalizado con el que se busca: códigos y nombres estándar, sin
  acentos y en minúsculas, igual que `texto_busqueda`. Se guarda en su propia columna y **no** se
  añade a `texto_busqueda` a propósito: si compartieran columna, el filtro de palabras clave
  volvería a encontrar el objeto de compra y el problema que esto resuelve seguiría ahí.
- **`cpc_codigos`** — los códigos distintos. Es lo que permite contar y agrupar por clasificación
  sin recorrer el `jsonb` fila a fila.
- **`items_recogidos_en`** — cuándo se leyó la ficha. Es la pieza del relleno reanudable y **es
  nula** mientras no se haya intentado. No se puede deducir de `items = '[]'`: hay necesidades
  publicadas sin detalle, y confundir «no tiene ítems» con «no se ha pedido todavía» dejaría a esas
  filas reintentándose para siempre, una petición por ciclo, contra una fuente que limita la tasa.

Sobre los índices
-----------------
Los mismos que ya usa la búsqueda y por el mismo motivo: GIN sobre `to_tsvector('simple', ...)` con
la configuración `simple` porque el texto se guarda ya normalizado, y GIN sobre el arreglo de
códigos para poder filtrar por igualdad. Los índices GIN de `tsvector` **no** aceleran `LIKE`, así
que la búsqueda va con `@@` y prefijos, que sí aprovecha el índice.

El índice parcial de pendientes existe porque el relleno pide «lo que falta» en cada ciclo y esa
consulta se hace contra la tabla entera: sin él, cada ciclo recorrería el histórico completo para
encontrar unas pocas filas.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ejecutar(sql: str) -> None:
    """Ejecuta un bloque SQL sentencia a sentencia (asyncpg no admite varias por consulta)."""
    for sentencia in sql.split(";"):
        limpia = sentencia.strip()
        if limpia:
            op.execute(limpia)


def upgrade() -> None:
    _ejecutar(
        """
        ALTER TABLE registro
            ADD COLUMN items jsonb NOT NULL DEFAULT '[]'::jsonb,
            ADD COLUMN cpc_busqueda text NOT NULL DEFAULT '',
            ADD COLUMN cpc_codigos text[] NOT NULL DEFAULT '{}',
            ADD COLUMN items_recogidos_en timestamptz;

        CREATE INDEX ix_registro_cpc_busqueda ON registro
            USING gin (to_tsvector('simple', cpc_busqueda));

        CREATE INDEX ix_registro_cpc_codigos ON registro
            USING gin (cpc_codigos);

        CREATE INDEX ix_registro_items_pendientes ON registro (id)
            WHERE items_recogidos_en IS NULL;

        COMMENT ON COLUMN registro.items IS
            'Tabla del detalle de la necesidad: codigo, nombre y descripcion del CPC, unidad y cantidad';
        COMMENT ON COLUMN registro.cpc_busqueda IS
            'Codigos y nombres de CPC normalizados. No incluye la descripcion libre a proposito';
        COMMENT ON COLUMN registro.items_recogidos_en IS
            'Cuando se leyo la ficha. Nulo significa pendiente, aunque la necesidad no tenga items';
        """
    )


def downgrade() -> None:
    _ejecutar(
        """
        DROP INDEX IF EXISTS ix_registro_items_pendientes;
        DROP INDEX IF EXISTS ix_registro_cpc_codigos;
        DROP INDEX IF EXISTS ix_registro_cpc_busqueda;

        ALTER TABLE registro
            DROP COLUMN IF EXISTS items_recogidos_en,
            DROP COLUMN IF EXISTS cpc_codigos,
            DROP COLUMN IF EXISTS cpc_busqueda,
            DROP COLUMN IF EXISTS items;
        """
    )
