"""Los índices que faltaban: el orden, los repartos y el código por fragmento.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-06

Por qué existe esta migración
-----------------------------
La 0014 añadió tres índices y **dos de sus tres ideas no funcionaron**. Esta los corrige con la
medición delante, que es lo que faltaba: los planes reales (`EXPLAIN (ANALYZE, BUFFERS)`) sobre las
110.678 filas del histórico, que ocupan 410 MB —230 MB de tabla y 180 MB de TOAST—.

1. **El orden por defecto seguía ordenando.** El índice se creó como `(fecha_publicacion DESC, id)`
   y la consulta pide `fecha_publicacion DESC NULLS LAST, id`. En PostgreSQL `DESC` implica
   `NULLS FIRST`, así que las dos cosas no son la misma y el planificador recurre al `Sort`:
   medido, 10,4 s por página, con el plan `Gather Merge → Sort → Parallel Seq Scan`. Reconstruido
   con `NULLS LAST` —el mismo orden que pide la consulta— la misma página tarda **3,4 ms**.
   Hoy no hay ninguna fila sin fecha, y por eso el desajuste no se veía en los datos: lo que no
   coincidía era la definición, y el planificador compara definiciones, no valores.
   El orden «más antiguos» se ajusta aquí también —el desempate al revés— para que sea exactamente
   la marcha atrás de este índice: así los dos órdenes caben en uno solo.

2. **Los dos repartos de las estadísticas recorrían la tabla entera**: 18,9 s el de provincia y
   17,9 s el de tipo de proceso. No era culpa del plan elegido —cualquier plan tiene que leer esas
   filas— sino de tener que leer `datos`: un `jsonb` de unos 2 KB por fila que vive comprimido en
   TOAST y se descomprime fila a fila. Medido en el plan: `Nested Loop → Index Scan … Buffers:
   shared hit=54065 read=16055`, más 1.175 bloques escritos a temporales.
   La salida no es un plan mejor, es **no leer la tabla**: si la expresión que se agrupa está en un
   índice, el recuento se resuelve con un `Index Only Scan`, que no descomprime nada.

3. **La búsqueda por código —el NIC de una ínfima— sigue siendo un recorrido**: 3,4 s. Un
   `ILIKE '%…%'` no lo aprovecha ningún btree, y por eso la 0014 lo dejó pendiente «si algún día
   molesta». Molesta, y ahora está medido: `pg_trgm` estaba disponible y sin instalar, así que el
   fragmento pasa por un índice GIN de trigramas.

Qué se añade
------------
- `ix_registro_fecha_id` **reconstruido** como `(fecha_publicacion DESC NULLS LAST, id)`.
- `ix_registro_provincia_agrupada` e `ix_registro_tipo_agrupado`: la expresión **literal** del
  `GROUP BY` de las estadísticas, carácter a carácter igual que la escribe la consulta.
- La extensión `pg_trgm` y `ix_registro_codigo_trgm`, un GIN sobre `COALESCE(datos ->> 'codigo','')`
  para que `ILIKE '%fragmento%'` deje de ser un recorrido.

Qué NO se añade, y por qué
--------------------------
- **Un índice para el tipo de proceso en el filtro.** El reparto sí lo necesita —de ahí el índice
  de agrupación—, pero el filtro compara por igualdad un valor que aparece en 18 de cada 110.000
  filas: para eso el planificador prefiere recorrer la tabla, como ya se razonó en la 0014.
- **Una columna `provincia` propia.** Sería la forma de quitar el `OR` de dos expresiones que hoy
  tiene el filtro del mapa (y con él, el `Sort` de 30.000 filas que cuesta 8,7 s en frío), pero eso
  es cambiar el esquema y rellenar 110.678 filas en caliente. Se mide primero si el orden
  arreglado —que ya permite recorrer el índice por fecha y descartar sin ordenar— basta.

Cuidado al tocar esto
---------------------
Los dos índices de reparto llevan la expresión **escrita a mano** aquí y la consulta la construye en
Python. Si una de las dos cambia, el índice deja de usarse y **no falla nada**: la consulta vuelve a
tardar 19 s y el único síntoma es que va lento. Por eso la expresión de la consulta vive en una
constante (`PROVINCIA_AGRUPADA` y `TIPO_PROCESO_AGRUPADO`, en `bd/consultas.py`) y hay una prueba
que la compara con el texto de este archivo, normalizando espacios. Esa prueba es lo que impide que
se separen.

Los `CREATE INDEX` no son concurrentes: toman un bloqueo de escritura sobre `registro` mientras se
construyen (minutos, porque hay que descomprimir `datos`). Conviene aplicarla con el worker de
ingesta parado, y así se hizo.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# La misma tabla de tildes que usan el filtro y el reparto, escrita entera para que se pueda
# comparar a simple vista con la de Python. Si una quitara una tilde que la otra no, la expresión
# del índice dejaría de coincidir con la de la consulta y el índice no se usaría: sin ningún error,
# solo más lento.
TILDES = "'áéíóúüñÁÉÍÓÚÜÑ', 'aeiouunAEIOUUN'"


def _ejecutar(sql: str) -> None:
    """Ejecuta un bloque SQL sentencia a sentencia (asyncpg no admite varias por consulta)."""
    for sentencia in sql.split(";"):
        limpia = sentencia.strip()
        if limpia:
            op.execute(limpia)


def upgrade() -> None:
    _ejecutar(
        f"""
        DROP INDEX IF EXISTS ix_registro_fecha_id;

        CREATE INDEX ix_registro_fecha_id ON registro
            (fecha_publicacion DESC NULLS LAST, id);

        CREATE INDEX ix_registro_provincia_agrupada ON registro
            (COALESCE(NULLIF(lower(translate(
                COALESCE(btrim(split_part(datos ->> 'provincia', '-', 1)), ''), {TILDES})),
                ''), 'sin provincia'));

        CREATE INDEX ix_registro_tipo_agrupado ON registro
            (COALESCE(NULLIF(btrim(datos ->> 'tipo_proceso'), ''), 'sin clasificar'));

        CREATE EXTENSION IF NOT EXISTS pg_trgm;

        CREATE INDEX ix_registro_codigo_trgm ON registro
            USING gin ((COALESCE(datos ->> 'codigo', '')) gin_trgm_ops);
        """
    )


def downgrade() -> None:
    _ejecutar(
        """
        DROP INDEX IF EXISTS ix_registro_codigo_trgm;

        DROP INDEX IF EXISTS ix_registro_tipo_agrupado;

        DROP INDEX IF EXISTS ix_registro_provincia_agrupada;

        DROP INDEX IF EXISTS ix_registro_fecha_id;

        CREATE INDEX ix_registro_fecha_id ON registro (fecha_publicacion DESC, id);
        """
    )
    # La extensión `pg_trgm` **no** se retira a propósito: quitarla es una operación del servidor,
    # no de esta tabla, y otras consultas podrían estar usándola. El índice que la necesita ya se
    # ha borrado arriba, así que sin él la extensión no cambia el comportamiento de nada.
