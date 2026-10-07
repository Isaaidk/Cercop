"""Columna con la fecha límite de proformas: vencimientos y retención.

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-06

Por qué existe esta migración
-----------------------------
La fecha límite de proformas vivía **solo** dentro del `jsonb` de `datos`, y se leía en cada consulta
con un `CAST` del texto y una guarda de patrón. Para mostrar «faltan 3 días» eso da igual, pero hay
dos preguntas que se hacen a menudo y que así se respondían recorriendo el histórico entero:

- **«¿Qué sigue admitiendo proforma?»** — el filtro «solo con plazo». Un `CAST` sobre `datos` no lo
  resuelve ningún índice: se lee y se descomprime el `jsonb` de las 111.000 filas (~2 KB cada una).
- **«¿Qué venció hace más de una semana?»** — la retención. Es la misma cuenta, y encima repetida
  cada cinco minutos por el `worker`.

Con la fecha en una columna las dos son un **rango sobre un índice**. Es la misma decisión que se
tomó con `provincia`, `tipo_proceso`, `texto_busqueda` y `cpc_busqueda`: el valor se calcula una vez,
al escribir, y lo que se guarda está listo para comparar.

Por qué **no** se añade una columna de estado
---------------------------------------------
Se pidió un `worker` de «actualización de estados», y la tentación es guardar un `estado` calculado
(«en plazo» / «vencida»). No se hace por dos razones:

1. El estado **se deduce** de la fecha y del reloj. Guardarlo obliga a un `worker` que lo reescriba
   para que no mienta, y cualquier parada del `worker` deja filas diciendo «en plazo» cuando ya no lo
   están. Una fecha y una comparación no se quedan obsoletas.
2. La fuente **no publica un estado útil**: medido el 2026-10-06, las 6.896 necesidades de NCO traen
   todas el mismo texto, «En Curso». Copiarlo a una columna no informaría de nada.

Lo que sí hace el `worker` cada cinco minutos es mirar si **algún plazo cruzó** desde la vuelta
anterior y, si cruzó, subir la generación: eso invalida las páginas y las estadísticas cacheadas, que
se calcularon con la foto de hace cinco minutos. Sin eso, la caché seguiría contando como abierta una
ínfima que ya venció, sin ningún error que lo delatara.

Por qué el relleno es barato
----------------------------
El `UPDATE` lleva la guarda del patrón, así que **solo toca las filas que traen el campo**: 6.896 de
111.212 medidas. Las que no lo traen —todas las de OCDS y las ínfimas sin fecha— quedan en nulo, que
es lo correcto y además es lo que hace que el índice parcial sea pequeño. Es lo contrario del relleno
de la 0017, que reescribió la tabla entera y dejó ~230 MB de espacio muerto: aquí son unos pocos
megas.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Escrito literal a propósito: una migración tiene que construir **siempre** la misma columna, así que
# no puede depender de `PATRON_FECHA_ISO` del código de la aplicación, que mañana puede cambiar. La
# prueba `test_el_patron_de_la_migracion_es_el_del_dominio` avisa si se separan.
PATRON = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}"


def upgrade() -> None:
    op.execute("ALTER TABLE registro ADD COLUMN IF NOT EXISTS plazo_proformas_en timestamptz")

    # El relleno va **antes** del índice: construirlo con la tabla a medio llenar lo dejaría a medias.
    op.execute(
        f"""
        UPDATE registro
           SET plazo_proformas_en = (datos ->> 'fecha_limite_proformas')::timestamptz
         WHERE (datos ->> 'fecha_limite_proformas') ~ '{PATRON}'
        """
    )

    # Índice **parcial**: solo las filas que tienen plazo. Los dos usos —el filtro «solo con plazo» y
    # la retención— empiezan por `plazo_proformas_en IS NOT NULL`, así que el índice no necesita las
    # 104.000 filas de OCDS que nunca lo van a tener, y se queda en una fracción del tamaño.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_registro_plazo_proformas
            ON registro (plazo_proformas_en)
         WHERE plazo_proformas_en IS NOT NULL
        """
    )

    # Sin estadísticas, el planificador no sabe que solo el 6 % de las filas tiene plazo y elige un
    # recorrido de la tabla para una consulta que el índice resuelve. Cuesta unos segundos y se paga
    # una sola vez.
    op.execute("ANALYZE registro")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_registro_plazo_proformas")
    op.execute("ALTER TABLE registro DROP COLUMN IF EXISTS plazo_proformas_en")
