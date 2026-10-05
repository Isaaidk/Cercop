"""Palabras clave de CPC guardadas por empresa.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-29

Por qué existe esta migración
-----------------------------
El filtro por CPC nació viviendo solo en el navegador: la lista de términos se escribía, se aplicaba
y se perdía al recargar. Eso sirve para una consulta suelta, no para lo que hace un cliente: mantener
**la misma lista** que el equipo revisa todos los días. Sin guardarla, cada persona la reescribe y
ninguna ve lo que ven las demás.

Qué es una fila y qué no
------------------------
Una fila es **un término que la empresa quiere vigilar por su clasificación**. No hay catálogo global
—a diferencia de `termino`, que se comparte entre negocios porque cada término dispara una consulta
a la fuente oficial— porque un término de CPC no dispara nada: filtra un histórico que ya está
ingestado. Por eso la clave única es por negocio y no por texto: dos empresas pueden vigilar lo mismo
sin compartir nada, y eso es correcto, porque cada una lo puede quitar sin afectar a la otra.

`texto_normalizado` y no `texto` en la clave única
--------------------------------------------------
«Lavado», «lavado» y «LAVADO» son el mismo filtro: el servidor los reduce al mismo término al
buscar. Guardar los tres sería enseñar tres fichas que hacen lo mismo y dejar que la lista parezca
tener más de lo que tiene. Se guarda el texto tal y como lo escribió la persona —para que la ficha
se lea como la reconoce— y se compara por la forma normalizada, que es la misma función que usa la
búsqueda (`normalizar_termino`).

Sobre el aislamiento
--------------------
El mismo patrón que el resto del plano de negocio: `ENABLE` y `FORCE ROW LEVEL SECURITY` —`FORCE`
para que la política valga también para el propietario de la tabla— y una política con `USING` y
`WITH CHECK`, de modo que nadie pueda leer ni escribir una fila a nombre de otra empresa. Una lista
de vigilancia es información del negocio: revela en qué está trabajando.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONTEXTO = "current_setting('app.negocio_id', true)::uuid"


def _ejecutar(sql: str) -> None:
    """Ejecuta un bloque SQL sentencia a sentencia (asyncpg no admite varias por consulta)."""
    for sentencia in sql.split(";"):
        limpia = sentencia.strip()
        if limpia:
            op.execute(limpia)


def upgrade() -> None:
    _ejecutar(
        f"""
        CREATE TABLE cpc_clave (
            id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            negocio_id        uuid NOT NULL REFERENCES negocio(id) ON DELETE CASCADE,
            texto             text NOT NULL,
            texto_normalizado text NOT NULL,
            creado_por        uuid REFERENCES usuario(id) ON DELETE SET NULL,
            creado_en         timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT cpc_clave_texto_no_vacio CHECK (btrim(texto) <> ''),
            CONSTRAINT cpc_clave_normalizado_no_vacio CHECK (btrim(texto_normalizado) <> '')
        );

        CREATE UNIQUE INDEX ix_cpc_clave_unica ON cpc_clave (negocio_id, texto_normalizado);

        CREATE INDEX ix_cpc_clave_negocio ON cpc_clave (negocio_id, creado_en);

        ALTER TABLE cpc_clave ENABLE ROW LEVEL SECURITY;
        ALTER TABLE cpc_clave FORCE ROW LEVEL SECURITY;
        CREATE POLICY aislamiento_cpc_clave ON cpc_clave
            USING (negocio_id = {CONTEXTO})
            WITH CHECK (negocio_id = {CONTEXTO});

        COMMENT ON TABLE cpc_clave IS
            'Terminos de CPC que una empresa vigila. Sin catalogo global: no disparan ingesta';
        """
    )


def downgrade() -> None:
    _ejecutar(
        """
        DROP POLICY IF EXISTS aislamiento_cpc_clave ON cpc_clave;
        ALTER TABLE cpc_clave NO FORCE ROW LEVEL SECURITY;
        ALTER TABLE cpc_clave DISABLE ROW LEVEL SECURITY;
        DROP INDEX IF EXISTS ix_cpc_clave_negocio;
        DROP INDEX IF EXISTS ix_cpc_clave_unica;
        DROP TABLE IF EXISTS cpc_clave;
        """
    )
