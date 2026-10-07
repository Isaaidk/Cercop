"""Índice de texto completo para la descripción del producto (el objeto de compra).

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-06

Por qué existe esta migración
-----------------------------
Se añade un filtro que busca **solo en la descripción del producto** —el campo canónico
`objeto_compra`—, con la misma semántica que las palabras clave. Buscar ahí sin índice es un
recorrido de las 110.000 filas calculando un `tsvector` por fila: unos 10 s.

Por qué una expresión y no una columna propia
---------------------------------------------
`texto_busqueda` y `cpc_busqueda` son columnas; este es el mismo tipo de dato y lo natural habría sido
una tercera. No se hizo por **espacio medido**, no por diseño:

- Sacar un valor de `datos` a una columna obliga a reescribir las 110.000 filas para rellenarla. El
  relleno de `provincia` y `tipo_proceso` (0017) dejó ~230 MB de espacio muerto en `registro` y llevó
  la base de 410 MB a 704 MB; liberar aquello costó retirar el GIN del `jsonb` (0019) y **aún no se ha
  podido compactar**, porque `VACUUM FULL` necesita unos 370 MB libres que la instancia no tiene.
  Repetir el relleno ahora dejaría la base sin disco.
- Para **filtrar**, un índice sobre la expresión sirve igual de bien que sobre una columna: el
  planificador la reconoce y hace un `Bitmap Index Scan`. Lo que **no** funciona sobre una expresión
  que cuelga de `datos` son los **recuentos** —agrupar por ella obliga a visitar el montón fila a
  fila, y la 0016 lo documenta con las mediciones— y aquí no se cuenta por ella, se filtra.

Cuando se compacte la tabla (con el Postgres de Docker habrá sitio de sobra), la columna propia es la
mejor versión: se calcula el `tsvector` una vez al escribir en lugar de en cada consulta. Queda
anotado en la deuda de `docs/19`.

De dónde sale el texto del índice
---------------------------------
Del **mismo literal** que usa la consulta: `INDICE_OBJETO` en `bd/consultas.py`. Si los dos se
separan, el índice deja de usarse y no falla nada: la búsqueda vuelve a los 10 s y el único síntoma es
que va lenta. La prueba `test_el_indice_de_la_descripcion_es_el_de_la_consulta` compara los dos.

Los dos llevan `to_tsvector('simple', …)` con la configuración **explícita**: la versión de un solo
argumento depende de `default_text_search_config`, que puede cambiar por sesión, y no es inmutable, así
que PostgreSQL no deja indexarla.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Escrito literal, y a propósito: una migración tiene que construir **siempre** el mismo índice, así
# que no puede depender de una constante del código de la aplicación que mañana puede cambiar. La
# prueba que lo compara con `INDICE_OBJETO` es la que avisa si se separan.
#
# El texto va normalizado —minúsculas y sin tildes— para que coincida con las palabras de la consulta,
# que llegan normalizadas igual. Indexando la descripción tal cual, quien buscara «cómputo» no
# encontraría nada: la tilde estaría en el índice y no en la consulta.
TILDES = "'áéíóúüñÁÉÍÓÚÜÑ', 'aeiouunAEIOUUN'"

INDICE = f"""USING gin (
    to_tsvector('simple', lower(translate(
        COALESCE(datos ->> 'objeto_compra', ''), {TILDES})))
)"""


def upgrade() -> None:
    op.execute(f"CREATE INDEX ix_registro_objeto ON registro {INDICE}")
    # `CREATE INDEX` no analiza la tabla, y sin estadísticas de la expresión el planificador puede
    # seguir eligiendo el recorrido: medido antes con otro índice, el plan era el de antes.
    op.execute("ANALYZE registro")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_registro_objeto")
