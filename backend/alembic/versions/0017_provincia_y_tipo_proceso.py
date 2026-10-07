"""Provincia y tipo de proceso como columnas propias, para no leer el `jsonb` al filtrar ni agrupar.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-06

Por qué existe esta migración
-----------------------------
Los dos repartos de las estadísticas eran lo más lento del panel: **21,4 s** el de provincia y
**15,1 s** el de tipo de proceso, medidos el 2026-10-06 con 110.743 filas. Y no era culpa del plan:
para contar hay que leer todas las filas, así que lo único que los hacía lentos era **qué** leían.
La expresión que se agrupa —`lower(translate(COALESCE(datos ->> 'provincia', '')))`— cuelga de
`datos`, el `jsonb` de unos 2 KB por fila que vive comprimido en `TOAST`: recorrer el histórico es
descomprimir 180 MB, fila a fila.

Se intentó primero con un índice sobre la expresión (migración 0015) y **no sirve**: el planificador
lo usa con una visita al montón por fila —29,8 s, once segundos peor— y un escaneo «solo índice»
sobre una expresión que cuelga del `jsonb` **no existe**, por mucho que se fuercen los parámetros
(comprobado en la 0016, que retira aquellos índices). Agrupando por una columna normal sí lo hay:
por eso esta migración saca el valor a su columna.

No es una idea nueva en este esquema: `texto_busqueda`, `cpc_busqueda`, `items` y `fecha_publicacion`
ya son valores de `datos` extraídos a una columna en el momento de escribir. Esto hace lo mismo con
los dos campos por los que el panel filtra y agrupa más.

Qué se guarda
-------------
La **clave**, no el texto de la fuente: la misma que las consultas comparan, calculada por las
mismas dos funciones que ahora usa la ingesta (`clave_provincia` y `clave_tipo_proceso`, en
`bd/claves.py`). Así la condición del filtro es una igualdad contra una columna —y no
`lower(translate(...))` sobre `datos`— y el planificador puede usar un índice.

- `provincia`: la provincia sin el cantón, en minúsculas y sin tildes («pichincha»), o
  «sin provincia» cuando la fuente no publica el campo.
- `tipo_proceso`: el texto publicado, sin espacios de sobra, o «sin clasificar» si no viene.

Las dos son `NOT NULL` con valor por defecto. No es un adorno: garantiza que **ninguna fila queda
fuera** de un filtro o de un reparto por olvidarse alguien de escribir la columna. Sin el `NOT NULL`,
un escritor que no la rellenara dejaría filas que no aparecen en ninguna búsqueda y que nadie echaría
de menos: el fallo más caro posible.

Cómo se rellena, y por qué así
------------------------------
Las columnas se añaden **sin `DEFAULT`** y se rellenan después, por tandas, dentro de la misma
transacción de la migración. El orden importa: en PostgreSQL 11+ un `ADD COLUMN … DEFAULT` no
reescribe la tabla —el valor se resuelve al leer—, así que las filas existentes **parecerían** ya
rellenas, el `UPDATE` no encontraría nada que actualizar y la migración terminaría en unos segundos
sin haber rellenado nada. El `DEFAULT` se pone al final, cuando ya está todo escrito.

El `UPDATE` reescribe la tabla: unos 230 MB de versiones nuevas más el `UPDATE` de WAL. Conviene
aplicarla con el worker de ingesta parado y pasar un `VACUUM` después para recuperar el espacio. Los
índices no son `CONCURRENTLY` y bloquean la escritura mientras se construyen, igual que en la 0015.

Los dos índices llevan la clave delante y, detrás, la fecha y el identificador con el que el panel
ordena: así sirven para las dos cosas a la vez —agrupar por la clave y sacar la página ordenada de
una provincia— con el mismo índice.

Qué se retira
-------------
`ix_registro_provincia_norm` e `ix_registro_provincia_split` (de la 0014). Existían para que el
filtro del mapa pudiera saltar por la expresión normalizada de `datos`; ahora el filtro compara
contra la columna, así que no los usa nadie y solo serían peso que mantener en cada escritura.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# La misma tabla de tildes que `bd/claves.py`, escrita entera para que se pueda comparar a simple
# vista con la de Python. Si una quitara una tilde que la otra no, la clave guardada y la clave que
# pide el filtro dejarían de coincidir y las filas de esa provincia no aparecerían: sin error, sin
# aviso, solo una provincia con menos contrataciones de las que tiene.
TILDES = "'áéíóúüñÁÉÍÓÚÜÑ', 'aeiouunAEIOUUN'"

# Filas por tanda del relleno. El `UPDATE` de 110.000 filas de golpe funciona, pero troceado se ve
# avanzar y, si algo va mal, el error dice en qué punto estaba.
FILAS_POR_TANDA = 4000

# La clave de cada fila, escrita igual que en `claves.py`. La prueba
# `test_las_claves_del_relleno_son_las_de_la_ingesta` compara este texto con el que construye Python.
RELLENAR = f"""
    UPDATE registro
       SET provincia = COALESCE(NULLIF(
               lower(translate(
                   COALESCE(btrim(split_part(datos ->> 'provincia', '-', 1)), ''), {TILDES})),
               ''), 'sin provincia'),
           tipo_proceso = COALESCE(NULLIF(btrim(datos ->> 'tipo_proceso'), ''), 'sin clasificar')
     WHERE id IN (SELECT id FROM registro WHERE provincia IS NULL LIMIT {FILAS_POR_TANDA})
"""


def upgrade() -> None:
    op.execute("ALTER TABLE registro ADD COLUMN provincia text")
    op.execute("ALTER TABLE registro ADD COLUMN tipo_proceso text")

    # El relleno, por tandas y en la misma transacción: o quedan todas las filas rellenas o no queda
    # ninguna. La condición de corte es «las que aún no la tienen», así que la última vuelta
    # actualiza cero filas y el bucle termina.
    enlace = op.get_bind()
    while True:
        resultado = enlace.execute(text(RELLENAR))
        if not resultado.rowcount:
            break

    # El valor por defecto y el `NOT NULL` van **después** del relleno, y en ese orden: con el
    # `DEFAULT` puesto de antes, las filas viejas parecerían rellenas y no se habrían escrito.
    op.execute("ALTER TABLE registro ALTER COLUMN provincia SET DEFAULT 'sin provincia'")
    op.execute("ALTER TABLE registro ALTER COLUMN tipo_proceso SET DEFAULT 'sin clasificar'")
    op.execute("ALTER TABLE registro ALTER COLUMN provincia SET NOT NULL")
    op.execute("ALTER TABLE registro ALTER COLUMN tipo_proceso SET NOT NULL")

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
    op.execute("DROP INDEX IF EXISTS ix_registro_provincia_norm")
    op.execute("DROP INDEX IF EXISTS ix_registro_provincia_split")

    # Sin esto el planificador no tiene estadísticas de las columnas nuevas y puede seguir eligiendo
    # el plan de antes: `CREATE INDEX` no analiza la tabla. Medido en la fase anterior, cuando un
    # índice recién creado parecía no usarse y el problema era que nadie había hecho `ANALYZE`.
    op.execute("ANALYZE registro")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_registro_tipo_proceso")
    op.execute("DROP INDEX IF EXISTS ix_registro_provincia")
    op.execute(
        f"""
        CREATE INDEX ix_registro_provincia_norm ON registro
            (lower(translate(COALESCE(datos ->> 'provincia', ''), {TILDES})))
        """
    )
    op.execute(
        f"""
        CREATE INDEX ix_registro_provincia_split ON registro
            (lower(translate(
                COALESCE(btrim(split_part(datos ->> 'provincia', '-', 1)), ''), {TILDES})))
        """
    )
    op.execute("ALTER TABLE registro DROP COLUMN IF EXISTS tipo_proceso")
    op.execute("ALTER TABLE registro DROP COLUMN IF EXISTS provincia")
