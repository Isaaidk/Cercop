"""Índices de texto que parten las palabras por cualquier signo (cobertura de palabras clave).

QA del cliente, ciclo 3: nueve palabras clave que vigilan no daban resultados en CercoApp y el portal
sí tenía procesos. Una de las causas, medida en el histórico: el analizador `simple` de PostgreSQL
deja **juntas** las palabras unidas por un signo —«llantas/neumaticos» (lo toma por una ruta),
«equipos.computo» (un dominio), «“adquisicion» (con la base en `C`, la comilla tipográfica es
letra)— y ninguna búsqueda por prefijo las alcanzaba. Un 8 % de las filas tenía alguna así.

Estos índices parten el texto con la misma regla que la consulta (`[^a-z0-9]+` → espacio), así que
el índice y la búsqueda ven las mismas palabras. Son índices **sobre expresión**: no reescriben
ninguna fila del histórico (rellenar una columna de 110.000 filas deja ~230 MB de espacio muerto).
Los índices anteriores (`ix_registro_busqueda`, `ix_registro_cpc_busqueda`, `ix_registro_objeto`)
se dejan: si hubiera que volver a la versión anterior del código, sus consultas siguen teniendo
índice. Se pueden retirar en una migración posterior, cuando esta versión lleve un tiempo estable.

`CREATE INDEX IF NOT EXISTS` y **nunca** `CONCURRENTLY`: el arranque del API ejecuta las migraciones
y un índice concurrente se queda esperando a la transacción abierta del worker (lección de
2026-11-13). Las expresiones tienen que coincidir letra a letra con `INDICE_TEXTO`, `INDICE_CPC` e
`INDICE_OBJETO` de `bd/consultas.py`; hay una prueba que lo comprueba.

Revision ID: 0049
Revises: 0048
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0049"
down_revision: str | None = "0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDICES = {
    "ix_registro_texto_palabras": (
        "to_tsvector('simple', regexp_replace(lower(texto_busqueda), '[^a-z0-9]+', ' ', 'g'))"
    ),
    "ix_registro_cpc_palabras": (
        "to_tsvector('simple', regexp_replace(lower(cpc_busqueda), '[^a-z0-9]+', ' ', 'g'))"
    ),
    "ix_registro_objeto_palabras": (
        "to_tsvector('simple', regexp_replace(lower(translate(COALESCE(datos ->> "
        "'objeto_compra', ''), 'áéíóúüñÁÉÍÓÚÜÑ', 'aeiouunAEIOUUN')), '[^a-z0-9]+', ' ', 'g'))"
    ),
}


def upgrade() -> None:
    for nombre, expresion in INDICES.items():
        op.execute(f"CREATE INDEX IF NOT EXISTS {nombre} ON registro USING gin ({expresion})")


def downgrade() -> None:
    for nombre in INDICES:
        op.execute(f"DROP INDEX IF EXISTS {nombre}")
