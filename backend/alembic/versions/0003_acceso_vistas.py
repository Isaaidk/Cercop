"""Acceso a vistas por suscripción y búsqueda de texto completo.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-27

Por qué existe esta migración
-----------------------------
Dos cambios independientes, ambos aditivos: no se modifica ni se borra ninguna columna existente,
así que es reversible sin pérdida y no obliga a reingestar nada.

1. **`acceso_vista`** — la concesión de acceso a cada vista por plazos. Cada fila es una concesión,
   no un estado: extender añade una fila y retirar marca `revocado_en`. El vencimiento es un instante
   absoluto (`vence_en`), no un número de días, para que el significado de una fila no cambie con el
   tiempo. Lleva `negocio_id` y entra en el mismo patrón de RLS que el resto del plano de negocio:
   el aislamiento lo impone la base de datos, no una condición escrita en una consulta.

2. **`ix_registro_busqueda`** — índice de texto completo sobre `registro.texto_busqueda`, que ya se
   guarda normalizado (minúsculas y sin acentos). Se usa la configuración `simple` a propósito: como
   el texto ya viene normalizado, aplicar el analizador de un idioma solo añadiría sorpresas.
   Los índices GIN de `tsvector` **no aceleran `LIKE '%texto%'`**, por eso la búsqueda se hace con
   `@@` y prefijos (`palabra:*`), que sí aprovecha el índice.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONTEXTO = "current_setting('app.negocio_id', true)::uuid"

VISTAS = ("necesidades", "ofertas", "contrataciones", "graficas")
PLAZOS = ("7d", "30d", "3m", "6m", "1a")


def _ejecutar(sql: str) -> None:
    """Ejecuta un bloque SQL sentencia a sentencia (asyncpg no admite varias por consulta)."""
    for sentencia in sql.split(";"):
        limpia = sentencia.strip()
        if limpia:
            op.execute(limpia)


def _lista(valores: Sequence[str]) -> str:
    return ", ".join(f"'{valor}'" for valor in valores)


def upgrade() -> None:
    _ejecutar(
        f"""
        CREATE TABLE acceso_vista (
            id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            negocio_id   uuid NOT NULL REFERENCES negocio(id) ON DELETE CASCADE,
            usuario_id   uuid NOT NULL REFERENCES usuario(id) ON DELETE CASCADE,
            vista        text NOT NULL CHECK (vista IN ({_lista(VISTAS)})),
            plazo_codigo text NOT NULL CHECK (plazo_codigo IN ({_lista(PLAZOS)})),
            otorgado_en  timestamptz NOT NULL DEFAULT now(),
            vence_en     timestamptz NOT NULL,
            otorgado_por uuid REFERENCES usuario(id) ON DELETE SET NULL,
            revocado_en  timestamptz,
            revocado_por uuid REFERENCES usuario(id) ON DELETE SET NULL,
            motivo       text,
            CONSTRAINT acceso_vista_vence_despues_de_otorgar CHECK (vence_en > otorgado_en)
        );

        CREATE INDEX ix_acceso_vista_vigencia ON acceso_vista (usuario_id, vista)
            WHERE revocado_en IS NULL;

        CREATE INDEX ix_acceso_vista_negocio ON acceso_vista (negocio_id, vence_en);

        CREATE INDEX ix_acceso_vista_vencimientos ON acceso_vista (vence_en)
            WHERE revocado_en IS NULL;

        ALTER TABLE acceso_vista ENABLE ROW LEVEL SECURITY;
        ALTER TABLE acceso_vista FORCE ROW LEVEL SECURITY;
        CREATE POLICY aislamiento_acceso_vista ON acceso_vista
            USING (negocio_id = {CONTEXTO})
            WITH CHECK (negocio_id = {CONTEXTO});
        """
    )

    _ejecutar(
        """
        CREATE INDEX ix_registro_busqueda ON registro
            USING gin (to_tsvector('simple', texto_busqueda));
        """
    )

    # El planificador ordena la cola por «cuántos negocios lo piden», y esa cuenta vive en
    # `suscripcion_termino`, que está protegida por RLS: una consulta normal desde el worker —que no
    # tiene contexto de negocio— contaría cero. Contar por negocio tampoco sirve, porque el término
    # es global y hay que verlos todos.
    #
    # La solución es una función `SECURITY DEFINER` que devuelve **solo un número**, nunca filas: no
    # puede filtrar datos de un negocio a otro porque no hay ninguna fila que devolver. El conteo de
    # popularidad es, además, información que el producto muestra a propósito («N negocios ya piden
    # este término»).
    #
    # `SET search_path` explícito es obligatorio en una función `SECURITY DEFINER`: sin él, un
    # esquema malicioso colocado antes en la ruta podría suplantar las tablas que la función usa.
    #
    # Esta sentencia **no** pasa por `_ejecutar`: el cuerpo de la función lleva un punto y coma
    # dentro del bloque entre dólares, y dividir por `;` partiría la función en dos mitades y
    # PostgreSQL fallaría con «unterminated dollar-quoted string». Como es una única sentencia, se
    # envía tal cual.
    op.execute(
        """
        CREATE FUNCTION conteo_suscriptores(p_termino_id uuid) RETURNS integer
            LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp
            AS $cuerpo$
                SELECT count(*)::integer
                FROM suscripcion_termino
                WHERE termino_id = p_termino_id AND activa;
            $cuerpo$
        """
    )


def downgrade() -> None:
    _ejecutar(
        """
        DROP FUNCTION IF EXISTS conteo_suscriptores(uuid);
        DROP INDEX IF EXISTS ix_registro_busqueda;
        DROP POLICY IF EXISTS aislamiento_acceso_vista ON acceso_vista;
        ALTER TABLE acceso_vista NO FORCE ROW LEVEL SECURITY;
        ALTER TABLE acceso_vista DISABLE ROW LEVEL SECURITY;
        DROP TABLE IF EXISTS acceso_vista;
        """
    )
