"""Retira del histórico las ínfimas cuyo plazo de proformas venció hace días.

    # Enseña lo que haría, sin tocar nada (es lo que hace por defecto)
    .\\.venv\\Scripts\\python.exe scripts\\purgar_vencidas.py

    # Lo hace, en tandas del tamaño configurado, hasta que no quede nada
    .\\.venv\\Scripts\\python.exe scripts\\purgar_vencidas.py --aplicar --todas

    # Otro plazo y otro tope, sin tocar los ajustes
    .\\.venv\\Scripts\\python.exe scripts\\purgar_vencidas.py --dias 30 --limite 200 --aplicar

Por qué existe, si el `worker` ya lo hace
----------------------------------------
El `worker` retira en cada vuelta unas pocas filas y lo cuenta en su registro. Eso pone la
retención al día en horas, que es lo correcto para que no compita con la ingesta —pero no sirve
para **decidir** si se quiere retención, ni para retirar de golpe lo que se acumuló antes de
activarla.

Por eso el guion **no borra si no se le dice `--aplicar`**: primero enseña cuánto se llevaría. Un
borrado no se deshace, y estas filas son las de los procesos ya cerrados que sostienen las
estadísticas del periodo.

Lo que se lleva cada fila
-------------------------
Su punto de contacto (la base lo hace por `ON DELETE CASCADE`) y sus versiones del histórico, que
hay que borrar a mano porque esa tabla **no** tiene clave foránea. Se hace en **una sola sentencia**
con las dos escrituras dentro: o pasan las dos o no pasa ninguna, así que no pueden quedar versiones
apuntando a un registro que ya no existe.

Todo esto sube la generación del caché, así que las páginas y las estadísticas guardadas dejan de
servir en el acto: el panel no sigue enseñando las filas que se acaban de retirar.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

sys.path.insert(0, "src")

from sqlalchemy import text

from contratacion.aplicacion.casos_uso.mantener_registros import mantener_registros
from contratacion.infraestructura.adaptadores.salida.bd.mantenimiento import (
    RepositorioMantenimientoBd,
)
from contratacion.infraestructura.adaptadores.salida.bd.sesion import cerrar_bd, obtener_motor
from contratacion.infraestructura.adaptadores.salida.cache.cliente import (
    cerrar_cache,
    obtener_cache,
)
from contratacion.infraestructura.config.ajustes import obtener_ajustes

CUANTAS = """
    SELECT count(*) FROM registro r JOIN fuente f ON f.id = r.fuente_id
     WHERE f.codigo = 'NCO'
"""

TAMANO = "SELECT pg_size_pretty(pg_total_relation_size('registro'))"


async def _cuantas_quedan() -> tuple[int, str]:
    async with obtener_motor().connect() as conexion:
        cuantas = int((await conexion.execute(text(CUANTAS))).scalar_one())
        # `scalar_one()` y no el resultado entero: el tamaño es **un** valor de texto, y quedarse
        # con el objeto del cursor lo que imprime es su `repr`, que no dice nada.
        tamano = str((await conexion.execute(text(TAMANO))).scalar_one())
    return cuantas, tamano


async def main(argv: list[str] | None = None) -> int:
    ajustes = obtener_ajustes()
    parser = argparse.ArgumentParser(description="Retención de ínfimas cuyas proformas vencieron.")
    parser.add_argument(
        "--aplicar",
        action="store_true",
        help="Borra de verdad. Sin esto solo cuenta lo que se llevaría (simulación).",
    )
    parser.add_argument(
        "--dias",
        type=int,
        default=ajustes.purga_plazo_dias,
        help=f"Días de retención tras el vencimiento (por defecto {ajustes.purga_plazo_dias}).",
    )
    parser.add_argument(
        "--limite",
        type=int,
        default=ajustes.purga_max_filas_por_vuelta,
        help=f"Filas como mucho en cada vuelta (por defecto {ajustes.purga_max_filas_por_vuelta}).",
    )
    parser.add_argument(
        "--todas",
        action="store_true",
        help="Repite vueltas hasta que no quede nada. Solo tiene sentido con --aplicar.",
    )
    argumentos = parser.parse_args(argv)

    antes, tamano_antes = await _cuantas_quedan()
    print(f"Ínfimas guardadas: {antes} · tamaño de la tabla: {tamano_antes}")
    print(
        f"Retención: {argumentos.dias} días tras el vencimiento · "
        f"tope por vuelta: {argumentos.limite}"
        + ("" if argumentos.limite else " (tope en cero: la retención está desactivada)")
    )
    if not argumentos.aplicar:
        print("Simulación: no se borra nada. Añade --aplicar para hacerlo de verdad.\n")

    vueltas = 0
    retiradas = 0
    historial = 0
    try:
        while True:
            resultado = await mantener_registros(
                RepositorioMantenimientoBd(obtener_motor()),
                obtener_cache(),
                intervalo_seg=ajustes.intervalo_mantenimiento_seg,
                dias_retencion=argumentos.dias,
                maximo_por_vuelta=argumentos.limite,
                simular=not argumentos.aplicar,
            )
            vueltas += 1
            retiradas += resultado.registros_purgados
            historial += resultado.historial_purgado
            print(
                f"  vuelta {vueltas}: {resultado.resumen()} · "
                f"quedan {max(resultado.vencidas - resultado.registros_purgados, 0)}"
            )
            # Una vuelta que no retira nada es el final, tanto si ya no queda material como si el
            # tope está en cero —que es «no retires», y entonces parar es lo correcto—.
            if not argumentos.todas or not resultado.registros_purgados:
                break
    finally:
        await cerrar_cache()
        await cerrar_bd()

    despues, tamano_despues = await _cuantas_quedan()
    verbo = "retiradas" if argumentos.aplicar else "se retirarían"
    print(
        f"\n{verbo}: {retiradas} ínfimas y {historial} versiones del histórico "
        f"en {vueltas} vuelta(s)"
    )
    print(f"Ínfimas: {antes} → {despues} · tamaño de la tabla: {tamano_antes} → {tamano_despues}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
