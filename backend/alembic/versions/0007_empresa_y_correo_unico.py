"""Datos de contacto de la empresa y correo único en toda la plataforma.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-27

Dos cambios, y el segundo es el que importa.

**Los datos de contacto de la empresa.** La tabla `negocio` guardaba nombre y RUC, nada más. Para que
alguien pueda registrar su empresa hacen falta, como mínimo, un correo y un teléfono de contacto: son
los datos con los que se le responde. Son columnas nuevas y admiten nulo, así que las empresas que ya
existen —hoy no hay ninguna, pero el razonamiento vale igual— no se ven afectadas.

**El correo pasa a ser único en toda la plataforma.** Es la corrección de un defecto real, y conviene
explicarlo porque el cambio de alcance no es evidente.

Hasta ahora la unicidad era por negocio (`ux_usuario_email_negocio`), lo que permitía que el mismo
correo existiera en dos empresas. Pero el inicio de sesión averigua a qué empresa pertenece quien
llama buscando **solo por correo** (`resolver_cuenta`), y con dos candidatos hace

    ORDER BY u.creado_en LIMIT 1

es decir, elige el más antiguo. La consecuencia: quien se registrara después con un correo ya usado
en otra empresa **no podría entrar nunca**. Su contraseña se comprobaría contra la ficha de la primera
empresa y fallaría siempre. No es un fallo visible —el mensaje es «el correo o la contraseña no son
correctos»— y no tiene arreglo desde la interfaz.

El índice global lo cierra en el único sitio donde se puede cerrar sin carreras: la base de datos. La
comprobación en el caso de uso daría un mensaje más agradable, pero dos registros simultáneos con el
mismo correo podrían pasar los dos; un índice único, no.

Al hacerlo, el índice por negocio queda subsumido: si el correo es único en toda la tabla, también lo
es dentro de cada negocio. Se retira para no pagar dos veces la comprobación en cada inserción.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Nombre del índice nuevo. El adaptador de base de datos lo busca por su nombre para traducir el
# error de la base a un mensaje entendible, así que **forma parte del contrato** entre la migración y
# el código: renombrarlo aquí sin cambiar allí convertiría «ese correo ya está en uso» en un error
# interno.
INDICE_CORREO_GLOBAL = "ux_usuario_email_global"


def _ejecutar(sql: str) -> None:
    """Ejecuta un bloque SQL sentencia a sentencia (asyncpg no admite varias por consulta)."""
    for sentencia in sql.split(";"):
        limpia = sentencia.strip()
        if limpia:
            op.execute(limpia)


def _correos_duplicados() -> list[str]:
    """Correos que hoy están repetidos en la tabla. Se consulta antes de crear el índice.

    Sin esta comprobación previa, la creación del índice fallaría con un mensaje de PostgreSQL sobre
    una relación duplicada que no dice **qué** correos son el problema ni en qué empresas están. Con
    datos reales, eso obliga a investigar a mano antes de poder desplegar.
    """
    conexion = op.get_bind()
    filas = conexion.execute(
        text(
            """
            SELECT lower(email) AS correo, count(*) AS cuantas
            FROM usuario
            GROUP BY lower(email)
            HAVING count(*) > 1
            ORDER BY cuantas DESC, correo
            """
        )
    ).all()
    return [f"{fila.correo} ({fila.cuantas} veces)" for fila in filas]


def upgrade() -> None:
    duplicados = _correos_duplicados()
    if duplicados:
        listado = "; ".join(duplicados[:20])
        raise RuntimeError(
            "No se puede hacer único el correo en toda la plataforma: hay correos repetidos en "
            f"empresas distintas. Resuélvelos antes de continuar. Correos: {listado}"
        )

    _ejecutar(
        """
        ALTER TABLE negocio ADD COLUMN email_contacto text;
        ALTER TABLE negocio ADD COLUMN telefono text;
        ALTER TABLE negocio ADD COLUMN direccion text;
        ALTER TABLE negocio ADD COLUMN ciudad text;
        """
    )

    # Se nombra el índice para que el adaptador pueda reconocerlo. En PostgreSQL, `CREATE UNIQUE
    # INDEX` es la forma de añadir unicidad sin bloquear la tabla como lo haría `ALTER TABLE ... ADD
    # CONSTRAINT`, que es una diferencia real en una tabla con movimiento.
    op.execute(f"CREATE UNIQUE INDEX {INDICE_CORREO_GLOBAL} ON usuario (lower(email))")
    op.execute("DROP INDEX IF EXISTS ux_usuario_email_negocio")


def downgrade() -> None:
    # Se restaura el índice por negocio antes de quitar el global: en el instante intermedio, la
    # tabla tiene que seguir teniendo la unicidad que tenía antes de esta migración.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_usuario_email_negocio ON usuario (negocio_id, lower(email))"
    )
    op.execute(f"DROP INDEX IF EXISTS {INDICE_CORREO_GLOBAL}")

    _ejecutar(
        """
        ALTER TABLE negocio DROP COLUMN IF EXISTS ciudad;
        ALTER TABLE negocio DROP COLUMN IF EXISTS direccion;
        ALTER TABLE negocio DROP COLUMN IF EXISTS telefono;
        ALTER TABLE negocio DROP COLUMN IF EXISTS email_contacto;
        """
    )
