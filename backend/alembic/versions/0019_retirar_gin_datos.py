"""Se retira el índice GIN del `jsonb` completo: 113 MB que no usa ninguna consulta.

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-06

Por qué existe esta migración
-----------------------------
Al rellenar `provincia` y `tipo_proceso` (0017) se reescribieron las 110.000 filas de `registro`, lo
que dejó una versión muerta de cada una: la tabla pasó de 230 MB a 415 MB y la base entera de 410 MB a
**704 MB**. Un `VACUUM FULL` para recuperar ese espacio **falló con «No space left on device»**,
porque reescribir la tabla necesita sitio libre para la copia mientras la original sigue ahí. Es
decir: el espacio hay que sacarlo de otro sitio antes de poder compactar.

`ix_registro_datos` es un GIN sobre **todo** el `jsonb` de `datos` y pesa **113 MB**, casi la mitad
de lo que suman los demás índices juntos. La 0014 ya lo señaló como «el más pesado de la tabla y un
candidato a retirarlo», pero lo dejó con un `pendiente`: quitarlo exigía medir antes si alguien lo
usaba.

Medido ahora, con `EXPLAIN (ANALYZE)`:

- **La consulta de catálogos, que era su única usuaria declarada, no lo usa.** Hace un
  `Parallel Seq Scan on registro` de 11,1 s, y el `jsonb_exists(r.datos, c.campo)` de la unión se
  resuelve como condición del recorrido. El índice GIN existe para los operadores `@>` y `?`, que el
  planificador solo prefiere cuando la condición **acota mucho**; aquí se pide «la fila tiene esta
  clave», y eso lo cumplen casi todas, así que recorrer sale más barato.
- **Ninguna otra consulta de la aplicación usa `datos @>` ni `jsonb_exists`.** Los filtros leen campos
  sueltos (`datos ->> 'campo'`), que no pueden usar el GIN; y el único `@>` del código es el de
  `cpc_codigos`, que tiene su propio índice.

Se retira, y con él se liberan 113 MB que hacen falta para poder compactar el resto. El `downgrade`
lo vuelve a crear igual que estaba, así que recuperarlo es una orden si algún día se quiere consultar
el `jsonb` por contenido.

Lo que **no** arregla esta migración
------------------------------------
Los ~230 MB de espacio muerto que quedan **dentro** de `registro`: liberarlos necesita un
`VACUUM FULL`, que a su vez necesita unos 370 MB libres —la copia nueva más el WAL, mientras la
original sigue ocupando su sitio—. Con lo que se libera aquí no llega. Hasta entonces el espacio
muerto se reutiliza (las filas nuevas de la ingesta ocupan ese hueco, así que la tabla no crecerá),
pero la tabla sigue midiendo 415 MB y un recorrido completo la lee entera: eso es lo que hace que los
catálogos tarden 11 s en lugar de 6.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TILDES = "'áéíóúüñÁÉÍÓÚÜÑ', 'aeiouunAEIOUUN'"


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_registro_datos")


def downgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_registro_datos ON registro USING gin (datos)")
    # La tabla de tildes se cita aquí solo para que quede constancia de que este archivo no la usa;
    # el índice del `jsonb` no normaliza nada.
    _ = TILDES
