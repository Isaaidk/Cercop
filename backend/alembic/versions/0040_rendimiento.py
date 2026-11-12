"""Rendimiento y concurrencia para 500 a 1.000 personas a la vez.

Revision ID: 0040
Revises: 0038
Create Date: 2026-11-12

`down_revision` es 0038 porque, al crear esta migración, 0039 (seguridad) todavía no existía. Si se
añade 0039 colgando también de 0038, hay que cambiar aquí `down_revision = "0039"` para que la
cadena tenga una sola cabeza (ver docs/39-rendimiento-y-concurrencia.md).

Qué hace y por qué (medido con EXPLAIN ANALYZE en la base local, ver el documento):

1. **Ficha por código** (`desde-codigo` y su sondeo cada pocos segundos): la búsqueda comparaba
   `datos->>'codigo' ILIKE :c OR clave_natural ILIKE :c` y recorría la tabla `registro` entera
   (Seq Scan) en cada sondeo de cada persona. Ahora compara `upper(...) = upper(:c)` y estos dos
   índices btree la resuelven por índice.
2. **Avisos repetidos**: índice único `(alerta_id, registro_id)` para que dos réplicas del worker,
   o una revisión repetida tras un fallo, no avisen dos veces del mismo proceso. Antes de crearlo se
   borran los duplicados que ya hubiera (se conserva el más antiguo de cada par).
3. **Cola de TDR**: columna `tomado_en` para reservar pedidos con `FOR UPDATE SKIP LOCKED` sin
   inventar un estado nuevo que el panel no conoce.
4. Índices de lecturas calientes que hoy filtran por empresa y ordenan en memoria: requisitos de una
   lectura, «Mis ofertas» por fecha, lecturas recientes, títulos de proforma.
5. Trigramas sobre `texto_busqueda` de lo vigente, para el `ILIKE '%…%'` de «Precios y
   competencia» (y las herramientas del asistente que lo usan), que hoy recorre la tabla.

Los índices sobre tablas grandes van con `CREATE INDEX CONCURRENTLY` dentro de un bloque de
autocommit: así no bloquean las escrituras del worker mientras se construyen en producción.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0040"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDICES_CONCURRENTES: tuple[tuple[str, str], ...] = (
    (
        "ix_registro_codigo_mayus",
        "ON registro (upper(datos ->> 'codigo'))",
    ),
    (
        "ix_registro_clave_natural_mayus",
        "ON registro (upper(clave_natural))",
    ),
    (
        "ix_registro_texto_trgm_vigente",
        "ON registro USING gin (texto_busqueda gin_trgm_ops) WHERE es_vigente",
    ),
    (
        "ix_requisito_proceso_lectura",
        "ON requisito_proceso (negocio_id, lectura_id, orden)",
    ),
    (
        "ix_proforma_negocio_creado",
        "ON proforma (negocio_id, creado_en DESC)",
    ),
    (
        "ix_proforma_titulo",
        "ON proforma (negocio_id, lower(titulo)) WHERE tipo IN ('proforma', 'cotizacion')",
    ),
    (
        "ix_lectura_documento_reciente",
        "ON lectura_documento (negocio_id, creado_en DESC)",
    ),
)


def upgrade() -> None:
    op.execute("ALTER TABLE documento_tdr ADD COLUMN IF NOT EXISTS tomado_en timestamptz")
    # Duplicados de antes del índice único: se queda el aviso más antiguo de cada (alerta, proceso).
    # `aviso` tiene RLS forzado: con el rol dueño (no superusuario) y sin contexto de empresa el
    # borrado no vería filas y el índice único fallaría. Se suspende el forzado solo para borrar.
    op.execute("ALTER TABLE aviso NO FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        DELETE FROM aviso a
        USING aviso b
        WHERE a.alerta_id IS NOT NULL
          AND a.alerta_id = b.alerta_id
          AND a.registro_id IS NOT DISTINCT FROM b.registro_id
          AND (a.creado_en, a.id) > (b.creado_en, b.id)
        """
    )
    op.execute("ALTER TABLE aviso FORCE ROW LEVEL SECURITY")
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS ux_aviso_alerta_registro "
            "ON aviso (alerta_id, registro_id) WHERE alerta_id IS NOT NULL"
        )
        for nombre, definicion in _INDICES_CONCURRENTES:
            op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {nombre} {definicion}")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for nombre, _ in reversed(_INDICES_CONCURRENTES):
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {nombre}")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ux_aviso_alerta_registro")
    op.execute("ALTER TABLE documento_tdr DROP COLUMN IF EXISTS tomado_en")
