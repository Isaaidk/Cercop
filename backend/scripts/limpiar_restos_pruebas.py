"""Borra de la base los negocios creados por las pruebas de integración.

Existe porque una prueba dejaba sus datos a propósito y nadie los borraba nunca: se acumularon 540
negocios con correos `@prueba.ec` en la base de desarrollo. El listado administrativo de usuarios
devuelve como máximo quinientas cuentas, así que ese volumen de basura habría empezado a desplazar a
los datos de verdad sin que nada fallara —el síntoma habría sido un listado incompleto, que es mucho
peor que un error—.

**Por defecto no borra nada**: informa de lo que encontraría. Borrar en una base compartida es una
operación destructiva y no debe ocurrir por ejecutar un script sin argumentos.

    python scripts/limpiar_restos_pruebas.py             # informe, no toca nada
    python scripts/limpiar_restos_pruebas.py --aplicar   # borra

El criterio es deliberadamente estrecho: un negocio se considera resto de pruebas **solo** si todos
sus usuarios tienen un correo terminado en `@prueba.ec`, que es el dominio que usan las pruebas. Un
negocio con una sola cuenta real no se toca, aunque tenga otra de prueba al lado.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from contratacion.infraestructura.adaptadores.salida.bd.sesion import (  # noqa: E402
    normalizar_url_bd,
)
from contratacion.infraestructura.config.ajustes import obtener_ajustes  # noqa: E402

DOMINIO_DE_PRUEBAS = "@prueba.ec"

# Un negocio es resto de pruebas si **no tiene ninguna cuenta que no sea de pruebas**. Se expresa al
# revés —«no existe un usuario que no sea de pruebas»— porque es la forma de que un negocio con una
# cuenta real mezclada quede fuera del borrado.
SELECCION = f"""
    SELECT n.id, n.nombre, count(u.id) AS cuentas
    FROM negocio n
    JOIN usuario u ON u.negocio_id = n.id
    GROUP BY n.id, n.nombre
    HAVING count(*) = count(*) FILTER (WHERE u.email LIKE '%{DOMINIO_DE_PRUEBAS}')
"""

BORRADO = f"""
    DELETE FROM negocio
    WHERE id IN (
        SELECT n.id
        FROM negocio n
        JOIN usuario u ON u.negocio_id = n.id
        GROUP BY n.id
        HAVING count(*) = count(*) FILTER (WHERE u.email LIKE '%{DOMINIO_DE_PRUEBAS}')
    )
"""


async def principal() -> None:
    aplicar = "--aplicar" in sys.argv

    ajustes = obtener_ajustes()
    motor = create_async_engine(
        normalizar_url_bd(ajustes.database_url).render_as_string(hide_password=False)
    )

    async with motor.connect() as conexion:
        candidatos = (await conexion.execute(text(SELECCION))).all()
        total_negocios: int = (
            await conexion.execute(text("SELECT count(*) FROM negocio"))
        ).scalar_one()

    print(f"Negocios en la base: {total_negocios}")
    print(f"Restos de pruebas detectados: {len(candidatos)}")

    for negocio_id, nombre, cuentas in candidatos[:10]:
        print(f"  {negocio_id}  {cuentas} cuenta(s)  {nombre!r}")
    if len(candidatos) > 10:
        print(f"  … y {len(candidatos) - 10} más")

    if not candidatos:
        await motor.dispose()
        return

    if not aplicar:
        print("\nNo se ha borrado nada. Vuelve a ejecutarlo con --aplicar para eliminarlos.")
        await motor.dispose()
        return

    async with motor.begin() as conexion:
        resultado = await conexion.execute(text(BORRADO))
        borrados = int(resultado.rowcount or 0)

    print(f"\nNegocios borrados: {borrados}")
    print("Sus usuarios, sesiones, concesiones y consentimientos se han ido en cascada.")

    async with motor.connect() as conexion:
        quedan: int = (await conexion.execute(text("SELECT count(*) FROM negocio"))).scalar_one()
    print(f"Negocios que quedan: {quedan}")

    await motor.dispose()


if __name__ == "__main__":
    asyncio.run(principal())
