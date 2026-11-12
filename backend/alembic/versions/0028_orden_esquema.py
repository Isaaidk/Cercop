"""Orden del esquema: RLS uniforme, particiones, índices y tablas sin uso.

Revision ID: 0028
Revises: 0027
Create Date: 2026-11-09

Tres políticas de RLS se crearon después del arreglo de `0004` y volvieron a usar
`current_setting` sin `NULLIF`. Con el pool de conexiones, un setting vacío no es lo mismo que
ausente y la comparación falla del lado que deja ver filas de más o ninguna. Se rehacen.

`acceso_vista.vista` deja de aceptar `contrataciones`: esa vista ya no concede una fuente propia.
Las filas que quedaran se borran; las vigentes se copiaron a `ofertas` en `0025`.

Se retiran cuatro tablas que ninguna consulta de la aplicación usa. `solicitud_arco` y
`punto_contacto_entidad` se quedan, por la LOPDP.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONTEXTO = "NULLIF(current_setting('app.negocio_id', true), '')::uuid"


def _ejecutar(sql: str) -> None:
    for sentencia in sql.split(";"):
        limpia = sentencia.strip()
        if limpia:
            op.execute(limpia)


def _rehacer_politica(tabla: str) -> None:
    _ejecutar(
        f"""
        DROP POLICY IF EXISTS aislamiento_{tabla} ON {tabla};
        CREATE POLICY aislamiento_{tabla} ON {tabla}
            USING (negocio_id = {CONTEXTO})
            WITH CHECK (negocio_id = {CONTEXTO});
        """
    )


def upgrade() -> None:
    for tabla in ("plantilla_excel", "exportacion_columnas", "cpc_clave"):
        _rehacer_politica(tabla)

    _ejecutar(
        """
        DELETE FROM acceso_vista WHERE vista = 'contrataciones';
        ALTER TABLE acceso_vista DROP CONSTRAINT IF EXISTS acceso_vista_vista_check;
        ALTER TABLE acceso_vista ADD CONSTRAINT acceso_vista_vista_check
            CHECK (vista IN ('necesidades', 'ofertas', 'graficas'));

        CREATE INDEX IF NOT EXISTS ix_auditoria_solicitud_plazo
            ON auditoria (usuario_id, ocurrido_en DESC)
            WHERE accion = 'solicitud_plazo';

        DROP TABLE IF EXISTS conjunto_termino;
        DROP TABLE IF EXISTS conjunto_terminos;
        DROP TABLE IF EXISTS filtro_guardado;
        DROP TABLE IF EXISTS exportacion;
        """
    )
    op.execute(_FUNCION_PARTICIONES)


def downgrade() -> None:
    # Las tablas retiradas no se recrean: no tenían datos de la aplicación y recrearlas sin su
    # migración original dejaría un esquema a medias. El downgrade deshace índices y el CHECK.
    _ejecutar(
        """
        DROP FUNCTION IF EXISTS asegurar_particiones();
        DROP INDEX IF EXISTS ix_auditoria_solicitud_plazo;
        ALTER TABLE acceso_vista DROP CONSTRAINT IF EXISTS acceso_vista_vista_check;
        ALTER TABLE acceso_vista ADD CONSTRAINT acceso_vista_vista_check
            CHECK (vista IN ('necesidades', 'ofertas', 'contrataciones', 'graficas'));
        """
    )


_FUNCION_PARTICIONES = """
CREATE OR REPLACE FUNCTION asegurar_particiones()
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    mes timestamptz;
    inicio timestamptz;
    fin timestamptz;
    nombre text;
BEGIN
    -- Tres meses hacia adelante, incluido el actual. Si la partición predeterminada ya tiene
    -- filas de ese mes, PostgreSQL rechaza el CREATE y se deja para una pasada manual: preferible
    -- a soltar la partición predeterminada en medio de una migración.
    FOR mes IN
        SELECT generate_series(
            date_trunc('month', now()),
            date_trunc('month', now()) + interval '3 months',
            interval '1 month'
        )
    LOOP
        inicio := mes;
        fin := mes + interval '1 month';
        nombre := 'auditoria_' || to_char(inicio, 'YYYYMM');
        BEGIN
            EXECUTE format(
                'CREATE TABLE IF NOT EXISTS %I PARTITION OF auditoria FOR VALUES FROM (%L) TO (%L)',
                nombre, inicio, fin
            );
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'No se pudo crear %: %', nombre, SQLERRM;
        END;
        nombre := 'registro_historial_' || to_char(inicio, 'YYYYMM');
        BEGIN
            EXECUTE format(
                'CREATE TABLE IF NOT EXISTS %I PARTITION OF registro_historial FOR VALUES FROM (%L) TO (%L)',
                nombre, inicio, fin
            );
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'No se pudo crear %: %', nombre, SQLERRM;
        END;
    END LOOP;
END;
$$;
"""
