"""Índices para las consultas del panel: orden, código y provincia.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-06

Por qué existe esta migración
-----------------------------
El histórico ya no cabe en la memoria de nadie: pasa de 110.000 filas, y varias consultas del panel
lo recorrían entero. El diagnóstico del camino de una consulta dejó tres causas concretas:

- El **orden por defecto** (`fecha_publicacion DESC`) no podía usar el índice que ya había, porque
  `ix_registro_fecha` empieza por `fuente_id` y la consulta no filtra por una fuente concreta: le
  faltaba la primera columna. Cada página acababa ordenando su resultado.
- La búsqueda por **código** —el NIC de una ínfima— iba con `ILIKE '%…%'`, que ningún btree puede
  aprovechar. Y es la búsqueda más concreta que hace una persona: sabe el código y quiere esa fila.
- El filtro por **provincia** compara contra una expresión (`lower(translate(...))`), así que el
  índice GIN del `jsonb` no sirve: el GIN indexa las claves y los valores tal cual, no una versión
  normalizada de ellos.

Qué se añade
------------
Tres índices, todos sobre expresiones que las consultas **ya** usan:

- `ix_registro_fecha_id` sobre `(fecha_publicacion DESC, id)` — el orden por defecto con su
  desempate y sin la columna de fuente delante. Es además lo que hará posible paginar por cursor.
- `ix_registro_provincia_norm` e `ix_registro_provincia_split` — las dos formas que compara el
  filtro del mapa: el valor completo («PICHINCHA - QUITO») y la parte de antes del guion
  («PICHINCHA»). Son dos expresiones distintas y **no** pueden compartir índice: con el `OR` de la
  condición, cada mitad se resuelve por el suyo.

Qué NO se añade, y por qué
--------------------------
- **El código del proceso.** Se buscó un índice de prefijo
  (`lower(COALESCE(datos ->> 'codigo', '')) text_pattern_ops`, que resuelve `LIKE 'nic-0360%'`) y
  **se descartó**: un btree solo sirve para prefijos, así que habría obligado a cambiar el filtro a
  «empieza por» y entonces recordar los últimos dígitos de un NIC —«26-00053», que es como lo hace
  la gente— no encontraría nada, porque los códigos empiezan por `NIC-`. Preferimos que el filtro
  siga acotando bien y que esa consulta sea un recorrido; si algún día molesta, la salida es una
  extensión de trigramas (`pg_trgm`), y eso es una decisión que conviene medir antes.
- **`estado`, `tipo_proceso` y `tipo_necesidad`.** Tienen cinco, dieciocho y tres valores distintos
  sobre el histórico entero, así que el planificador prefiere recorrer la tabla antes que saltar por
  un índice que le devuelve una quinta parte de las filas. Un índice así solo añadiría coste de
  escritura y peso: medir antes de creer.
- **`solo_con_plazo`.** Compara `datos ->> 'fecha_limite_proformas'` convertido a `timestamptz`, y
  esa conversión **no es inmutable** —depende de la zona horaria de la sesión—, de modo que
  PostgreSQL no admite indexarla. La salida sería una columna propia con la fecha, y eso es un
  cambio de esquema que conviene medir antes de hacer.
- **`ix_registro_datos`** (el GIN del `jsonb` completo) se queda. Es el índice más pesado de la
  tabla y un candidato a retirarlo, pero lo usa la consulta de catálogos: quitarlo exige medirla
  antes, y eso no es esta migración.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# La misma tabla de tildes que usa el filtro en Python (`normalizar_ubicacion`) y la expresión SQL de
# `PROVINCIA_NORMALIZADA`. Se escribe entera y explícita para que se pueda comparar a simple vista
# con la del código: si una quitara una tilde que la otra no, el índice no coincidiría con la
# condición y no se usaría —sin ningún error, solo más lento—.
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
        CREATE INDEX ix_registro_fecha_id ON registro (fecha_publicacion DESC, id);

        CREATE INDEX ix_registro_provincia_norm ON registro
            (lower(translate(COALESCE(datos ->> 'provincia', ''), {TILDES})));

        CREATE INDEX ix_registro_provincia_split ON registro
            (lower(translate(
                COALESCE(btrim(split_part(datos ->> 'provincia', '-', 1)), ''), {TILDES})));
        """
    )


def downgrade() -> None:
    _ejecutar(
        """
        DROP INDEX IF EXISTS ix_registro_provincia_split;
        DROP INDEX IF EXISTS ix_registro_provincia_norm;
        DROP INDEX IF EXISTS ix_registro_fecha_id;
        """
    )
