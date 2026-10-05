"""Diagnóstico de una lista de términos de CPC: por qué acota (o no acota).

    .\\.venv\\Scripts\\python.exe scripts\\verificar_cpc_lista.py
    .\\.venv\\Scripts\\python.exe scripts\\verificar_cpc_lista.py lavado engrasado 871410032

Existe por un síntoma que no se puede distinguir mirando la pantalla: **añado mi lista de CPC, el
filtro se aplica, y la tabla sigue enseñando lo mismo que sin él**. Hay tres causas posibles y cada
una se arregla de una manera distinta:

1. **La lista no se está enviando** (algo del panel): aquí se vería que el total con CPC y sin CPC
   coinciden cuando la lista sí debería acotar.
2. **La lista es demasiado ancha** —términos genéricos con modo «cualquiera»—: el filtro funciona y
   está acotando, pero tan poco que no se nota. Aquí se ve cuánto aporta **cada término** por
   separado, que es el dato que falta para decidir cuál sobra.
3. **Las fichas no están leídas**: un registro sin CPC leído no puede coincidir con ningún término,
   y eso hace que el filtro parezca roto cuando lo que falta es ingesta.

No pasa por HTTP: llama a la capa de consulta directamente, así que no necesita credenciales y
comprueba la consulta, no el transporte. Es el mismo criterio que `verificar_filtros.py`.
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text

sys.path.insert(0, "src")

from contratacion.dominio.busqueda import Filtros, ModoBusqueda, OrdenBusqueda
from contratacion.infraestructura.adaptadores.salida.bd.consultas import (
    RepositorioConsultasBd,
)
from contratacion.infraestructura.adaptadores.salida.bd.sesion import (
    cerrar_bd,
    obtener_motor,
)

FUENTES = ("NCO", "OCDS")

# La lista que se comportaba como si no filtrara, tal y como llegó en la consulta del panel.
LISTA_DEL_PANEL = (
    "atl",
    "btl",
    "camara",
    "campana",
    "cinemometro",
    "cobertura",
    "comunicacion",
    "concierto",
    "control",
    "cultura",
    "deportivo",
    "desfile",
    "educativos",
    "espectaculo",
    "evento",
    "exposicion",
    "festival",
    "foto radar",
    "gestion",
    "historia",
    "memoria",
    "museologia",
    "organización",
    "pauta",
    "presentacion",
    "produccion",
    "publicidad",
    "senalizacion",
    "trasito",
    "video",
    "962200561",
)


async def _reparto_cpc() -> tuple[int, int, int]:
    """(con CPC leído, sin CPC leído, registros totales)."""
    async with obtener_motor().connect() as conexion:
        fila = (
            await conexion.execute(
                text(
                    """
                    SELECT count(*) FILTER (WHERE cpc_busqueda <> '') AS con_cpc,
                           count(*) FILTER (WHERE cpc_busqueda = '')  AS sin_cpc,
                           count(*) AS total
                    FROM registro
                    """
                )
            )
        ).one()
        return int(fila.con_cpc), int(fila.sin_cpc), int(fila.total)


async def main() -> None:
    terminos = tuple(sys.argv[1:]) or LISTA_DEL_PANEL
    repositorio = RepositorioConsultasBd(obtener_motor())

    def filtros(**cambios: object) -> Filtros:
        base: dict[str, object] = {
            "fuentes_permitidas": FUENTES,
            "orden": OrdenBusqueda.RECIENTES,
        }
        base.update(cambios)
        return Filtros(**base)  # type: ignore[arg-type]

    async def total(f: Filtros) -> int:
        _, cantidad = await repositorio.buscar(f)
        return cantidad

    try:
        con_cpc, sin_cpc, todos = await _reparto_cpc()
        print()
        print(f"  Terminos de la lista: {len(terminos)}")
        print(f"  Registros: {todos} | con CPC leido: {con_cpc} | sin CPC leido: {sin_cpc}")
        print()

        base = await total(filtros())
        cualquiera = await total(filtros(cpc=terminos, modo=ModoBusqueda.CUALQUIERA))
        todas = await total(filtros(cpc=terminos, modo=ModoBusqueda.TODAS))
        # La pestaña de familia viaja con los criterios, así que hay que medir la combinación:
        # un total que se lee en la pantalla es siempre el de la familia que está abierta.
        infimas = await total(filtros(categoria="infimas"))
        infimas_cpc = await total(
            filtros(categoria="infimas", cpc=terminos, modo=ModoBusqueda.CUALQUIERA)
        )

        print("  == La lista entera ==")
        print(f"    sin CPC                       -> {base}")
        print(f"    con CPC y modo 'cualquiera'   -> {cualquiera}")
        print(f"    con CPC y modo 'todas'        -> {todas}")
        print(f"    solo infimas (sin CPC)        -> {infimas}")
        print(f"    infimas + CPC 'cualquiera'    -> {infimas_cpc}")
        print()

        if todas == 0 and len(terminos) > 1:
            print("  El modo 'todas' exige que el CPC de un registro contenga TODOS los")
            print("  terminos a la vez. Con clasificaciones alternativas eso es imposible: para")
            print("  una lista de categorias el modo correcto es 'cualquiera'.")
            print()

        if cualquiera == base:
            print("  AVISO: la lista no acota NADA. O no se esta aplicando, o todos los")
            print("         registros con CPC leido coinciden con algun termino.")
        elif cualquiera > todos * 0.8:
            print("  AVISO: la lista acota muy poco. Suele ser sintoma de terminos genericos")
            print("         combinados con 'cualquiera': mira el reparto de abajo.")
        print()

        print("  == Cuanto aporta cada termino por separado ==")
        conteos: list[tuple[int, str]] = []
        for termino in terminos:
            conteos.append((await total(filtros(cpc=(termino,))), termino))
        reparto = sorted(conteos, reverse=True)
        for cantidad, termino in reparto:
            print(f"    {cantidad:>6}  {termino}")

        sin_leituras = [termino for cantidad, termino in reparto if cantidad == 0]
        if sin_leituras:
            print()
            print(f"  Terminos que no encuentran nada ({len(sin_leituras)}):")
            for termino in sin_leituras:
                print(f"    - {termino}")
            print("    Puede ser que el termino no exista en ningun CPC, o que las fichas de")
            print("    esas necesidades todavia no se hayan leido.")
        print()
    finally:
        await cerrar_bd()


if __name__ == "__main__":
    asyncio.run(main())
