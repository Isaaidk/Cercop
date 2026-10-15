"""Índices de los filtros del listado de ofertas: entidad, tipo de compra y estado.

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-15

Qué se midió, y con qué resultado
---------------------------------
Los tres filtros del listado de ofertas que compara contra el `jsonb` recorrían la tabla entera
leyendo y descomprimiendo `datos` —unos 2 KB por fila, 108.518 filas—. Medido el 2026-10-15 contra
la base real, contando como lo hace la pantalla:

    tipo_necesidad = 'Bien'   -> 113.817 ms  (0 filas)
    entidad        = 'UNIVERSIDAD' -> 104.140 ms  (3.264 filas)
    entidad        = 'municipio'   ->  99.797 ms  (1.243 filas)
    estado         = 'En Curso'    ->   4.201 ms  (3.368 filas)

Y después de esta migración:

    tipo_necesidad = 'Bien'   ->     906 ms
    entidad        = 'UNIVERSIDAD' ->   ~1.300 ms
    estado         = 'En Curso'    ->   3.002 ms

Por qué un índice de trigramas para la entidad y no de texto completo
--------------------------------------------------------------------
Es la misma decisión —y el mismo índice— que la migración 0015 usó para el fragmento del código
(`ix_registro_codigo_trgm`), donde la medición fue 3.385 ms → 116 ms. `pg_trgm` ya está instalado
desde entonces.

El filtro compara con `LIKE '%…%'`, y eso **solo** lo resuelve un índice de trigramas: un índice
btree no puede con un comodín al principio, y un índice de texto completo habría cambiado la
búsqueda —de «contiene» a «empieza por palabra»—. Para un nombre de entidad, que se escribe a
trozos («municipio», «quito», «epmaps»), la coincidencia por subcadena es la que se espera, así que
se conserva tal cual. Es el mismo comportamiento de antes, solo que con índice.

Por qué el tipo de compra y el estado llevan un índice sobre la expresión
------------------------------------------------------------------------
Los dos comparan por **igualdad** (`datos ->> 'tipo_necesidad' = …`), así que basta un btree sobre
la misma expresión: la igualdad deja de ser un recorrido y pasa a ser una búsqueda. No se sacan a
columnas propias —que es lo que se hizo con `provincia` y `tipo_proceso`— porque eso obliga a
reescribir las 108.000 filas y deja cientos de megas de espacio muerto (medido al rellenar esas dos
columnas, ~230 MB), y aquí no hace falta: para **filtrar** la expresión indexada sirve igual.

Por qué la extensión se crea aquí también
----------------------------------------
Por la 0015 ya está. Se repite con `IF NOT EXISTS` para que la migración exprese su propia
dependencia: sin `pg_trgm` no hay `gin_trgm_ops` y el `CREATE INDEX` fallaría con un error que
apunta a la extensión y no a esta migración. Es idempotente y no cuesta nada.

Por qué el `ANALYZE` y el `IF NOT EXISTS`
-----------------------------------------
`CREATE INDEX` no analiza la tabla, y sin estadísticas de la expresión el planificador puede seguir
eligiendo el recorrido de siempre: ya pasó con el índice de la descripción (0020), donde el plan no
cambió hasta actualizar las estadísticas.

`IF NOT EXISTS` porque estos índices se pueden haber creado a mano para medir la mejora antes de
desplegar —así se hicieron las mediciones de arriba—, y sin la guarda el despliegue fallaría al
encontrarse hecho algo que ya está.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Las dos listas de `translate` de `PROVINCIA_NORMALIZADA` (`bd/claves.py`). Se repiten aquí, sin
# importarlas, por la razón de siempre en estas migraciones: tienen que seguir produciendo el mismo
# resultado dentro de dos años, cuando el código vivo haya cambiado.
TILDES = "'áéíóúüñÁÉÍÓÚÜÑ', 'aeiouunAEIOUUN'"

# El texto tiene que coincidir **exactamente** con el que compone la consulta. Si se separan,
# PostgreSQL deja de usar el índice y la búsqueda vuelve a los cien segundos medidos, sin que falle
# nada: ni un error, ni un aviso, solo lentitud. Hay una prueba que compara las dos expresiones.
INDICE_ENTIDAD = f"""USING gin (
    lower(translate(COALESCE(datos ->> 'entidad', ''), {TILDES})) gin_trgm_ops
)"""

INDICE_TIPO_NECESIDAD = "USING btree ((datos ->> 'tipo_necesidad'))"
INDICE_ESTADO = "USING btree ((datos ->> 'estado'))"

INDICES: tuple[tuple[str, str], ...] = (
    ("ix_registro_entidad", INDICE_ENTIDAD),
    ("ix_registro_tipo_necesidad", INDICE_TIPO_NECESIDAD),
    ("ix_registro_estado", INDICE_ESTADO),
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for nombre, expresion in INDICES:
        op.execute(f"CREATE INDEX IF NOT EXISTS {nombre} ON registro {expresion}")
    op.execute("ANALYZE registro")


def downgrade() -> None:
    for nombre, _ in INDICES:
        op.execute(f"DROP INDEX IF EXISTS {nombre}")
    # La extensión `pg_trgm` **no** se retira: la creó la 0015, la usa su índice
    # (`ix_registro_codigo_trgm`) y quitarla es una operación del servidor, no de esta migración.
