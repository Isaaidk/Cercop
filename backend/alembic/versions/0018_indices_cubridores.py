"""Los dos índices de clave tienen que incluir `fuente_id` para ser cubridores.

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-06

Por qué existe esta migración
-----------------------------
La 0017 sacó `provincia` y `tipo_proceso` a columnas propias e hizo dos índices
`(clave, fecha_publicacion DESC NULLS LAST, id)`. Con eso, el reparto **sin** tocar la tabla funciona:
medido, `Index Only Scan` y **686 ms** frente a los 21,4 s de antes. Pero las consultas reales no dan
un escaneo «solo índice», y por un motivo concreto que se mide en tres pasos:

| Consulta | Plan | Tiempo |
|---|---|---|
| `SELECT provincia, count(*) FROM registro GROUP BY 1` | `Index Only Scan using ix_registro_provincia` | **686 ms** |
| la misma, con `WHERE fuente_id = ANY(…)` | `Parallel Seq Scan` | 12,8 s |
| la real, uniendo con `fuente` para el permiso | `Index Scan using ix_registro_fecha` | 19,4 s |

La diferencia entre la primera y la segunda es una sola cosa: **`fuente_id`**. Un escaneo «solo
índice» exige que **todas** las columnas que la consulta necesita estén en el índice, y estas
consultas siempre necesitan `fuente_id`, porque el permiso de lectura por fuente se aplica uniendo con
`fuente` (`f.codigo = ANY(:fuentes_permitidas)`). Sin esa columna en el índice, el planificador no
puede evitar el montón y vuelve a leer —y descomprimir— el `jsonb` de cada fila, que es justo lo que
la 0017 venía a arreglar.

Y había un efecto peor que no se ve en el tiempo del reparto: **el índice nuevo empeoraba el clic del
mapa**. El `count(*)` de una provincia pasó de ~400 ms a **9,5 s**, porque el planificador lo resolvía
con un `Bitmap Heap Scan` sobre el índice nuevo —29.707 visitas al montón, cada una descomprimiendo un
`jsonb` de 2 KB— que antes no podía elegir. Un índice que no cubre todo lo que hace falta no es
neutro: es una trampa.

Qué se añade
------------
Los dos índices se reconstruyen con `fuente_id` **al final**, para no cambiar las columnas que van
delante:

- `ix_registro_provincia (provincia, fecha_publicacion DESC NULLS LAST, id, fuente_id)`
- `ix_registro_tipo_proceso (tipo_proceso, fecha_publicacion DESC NULLS LAST, id, fuente_id)`

El orden importa: `provincia` delante es lo que permite acotar por una provincia en un rango del
índice, y `fecha_publicacion`/`id` detrás son el orden en el que el panel pide la página, así que el
mismo índice sirve para el recuento, para el reparto y para la página —sin ordenar nada—. `fuente_id`
va al final porque solo hace falta para **descartar** filas de fuentes no permitidas, y al final no
rompe ni el rango ni el orden.

El coste es que los índices son algo más anchos (unos 16 B por fila: ~2 MB cada uno). Se paga con
gusto: sin esa columna el índice no se usa.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_registro_provincia")
    op.execute("DROP INDEX IF EXISTS ix_registro_tipo_proceso")
    op.execute(
        """
        CREATE INDEX ix_registro_provincia ON registro
            (provincia, fecha_publicacion DESC NULLS LAST, id, fuente_id)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_registro_tipo_proceso ON registro
            (tipo_proceso, fecha_publicacion DESC NULLS LAST, id, fuente_id)
        """
    )
    # `CREATE INDEX` no analiza la tabla, y sin estadísticas de las columnas nuevas el planificador
    # puede seguir eligiendo el plan de antes.
    op.execute("ANALYZE registro")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_registro_provincia")
    op.execute("DROP INDEX IF EXISTS ix_registro_tipo_proceso")
    op.execute(
        """
        CREATE INDEX ix_registro_provincia ON registro
            (provincia, fecha_publicacion DESC NULLS LAST, id)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_registro_tipo_proceso ON registro
            (tipo_proceso, fecha_publicacion DESC NULLS LAST, id)
        """
    )
