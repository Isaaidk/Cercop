"""Se retiran los dos índices de reparto de la 0015: no servían y además engañaban al planificador.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-06

Por qué existe esta migración
-----------------------------
La 0015 añadió tres ideas y **una de ellas era falsa**. Esta migración la deshace, con la medición
delante. Los otros dos índices de la 0015 —el del orden y el del código por fragmento— sí
funcionaron y se quedan.

El razonamiento de la 0015 era: los repartos de las estadísticas tardan 18,9 s y 17,9 s porque hay
que leer `datos` —un `jsonb` de 2 KB por fila que se descomprime fila a fila—, así que si la
expresión que se agrupa está en un índice, el recuento se resolverá con un `Index Only Scan` y no
descomprimirá nada. **La primera mitad es cierta y la segunda no.**

Lo que se midió después
-----------------------
Con los dos índices creados y las estadísticas al día (`ANALYZE registro`, que `CREATE INDEX` no
hace y sin el cual el planificador ni siquiera sabe que existen):

- `ix_registro_provincia_agrupada` no da un escaneo «solo índice», da un `Index Scan`
  acompañado de una visita al montón por fila: 29,8 s, **once segundos peor** que antes de crearlo.
- `ix_registro_tipo_agrupado`: 14,2 s, también peor.

Y no es un problema de coste. Forzando `enable_seqscan = off` y `enable_bitmapscan = off`, el plan
sigue siendo `Index Scan` con visitas al montón, nunca `Index Only Scan`; con `enable_indexscan =
off` —que lo penaliza con 10^10— el planificador **lo sigue eligiendo**, con lo que ese otro camino
no existe. La comprobación que lo cierra es el control: agrupando por una columna normal,
`registro_fuente_id_clave_natural_key` da `Index Only Scan` con un coste de 3.238 frente a los
30.000 del recorrido, y tarda décimas. Es decir: **el escaneo «solo índice» funciona de sobra en
esta tabla; lo que no funciona es sobre una expresión que cuelga de `datos`.**

Lo que queda en su lugar
------------------------
El plan que elige el motor después de un `VACUUM (ANALYZE) registro` es un `Parallel Seq Scan`, y
tarda 7,4 s y 7,8 s —la mitad que al principio, sin ningún índice nuevo—. El `VACUUM` importa y está
documentado en `docs/07-capacidad-y-concurrencia.md`: el mapa de visibilidad estaba al 94,8 % y con
las estadísticas viejas el planificador elegía un `Nested Loop` con `Index Scan` que costaba 18,9 s.
Con las estadísticas al día prefiere el recorrido en paralelo. Mantener la tabla recién analizada es,
por sí solo, la mitad del arreglo de estos dos repartos.

Los 7,4 s que quedan son el suelo de leer 110.678 filas de un `jsonb` gordo, y no se bajan con
índices: la salida es que `provincia` y `tipo_proceso` sean columnas propias —como ya lo son
`cpc_busqueda`, `cpc_codigos` o `fecha_publicacion`—, y eso exige rellenar 110.678 filas y tocar la
ingesta. Se deja para una decisión aparte, con estas cifras delante.

Qué NO se toca
--------------
- `ix_registro_provincia_norm` e `ix_registro_provincia_split` (de la 0014) **se quedan**: esas sí
  se usan. El filtro del mapa se resuelve con un `BitmapOr` sobre las dos, comprobado en el plan.
  Son para filtrar, no para agrupar, y el filtro sí aprovecha un índice sobre el `jsonb`.
- El orden por defecto y el código por fragmento, que ya están arreglados.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
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
        DROP INDEX IF EXISTS ix_registro_provincia_agrupada;

        DROP INDEX IF EXISTS ix_registro_tipo_agrupado;
        """
    )


def downgrade() -> None:
    _ejecutar(
        """
        CREATE INDEX IF NOT EXISTS ix_registro_provincia_agrupada ON registro
            (COALESCE(NULLIF(lower(translate(
                COALESCE(btrim(split_part(datos ->> 'provincia', '-', 1)), ''),
                'áéíóúüñÁÉÍÓÚÜÑ', 'aeiouunAEIOUUN')),
                ''), 'sin provincia'));

        CREATE INDEX IF NOT EXISTS ix_registro_tipo_agrupado ON registro
            (COALESCE(NULLIF(btrim(datos ->> 'tipo_proceso'), ''), 'sin clasificar'));
        """
    )
