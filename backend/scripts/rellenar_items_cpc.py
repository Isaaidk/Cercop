"""Rellena los ítems con CPC de las necesidades a las que todavía no se les ha leído la ficha.

    .\\.venv\\Scripts\\python.exe scripts\\rellenar_items_cpc.py
    .\\.venv\\Scripts\\python.exe scripts\\rellenar_items_cpc.py --simular
    .\\.venv\\Scripts\\python.exe scripts\\rellenar_items_cpc.py --tanda 500 --maximo 1000

El `worker` ya hace esto por tandas dentro de cada ciclo, y con él en marcha **no hace falta este
guion**: existe para dos casos concretos.

- **Poner al día el histórico de golpe.** La primera vez hay más de dos mil fichas pendientes, y a
  la cadencia del ciclo —300 por vuelta, una vuelta cada 15 minutos— tardarían horas. Aquí se
  encadenan las tandas seguidas, sin esperar al siguiente ciclo.
- **Volver a leer lo que quedó a medias.** Si se cambió el analizador o hubo una caída larga, se
  puede repetir sin esperar a que el ciclo lo alcance.

Tres cosas que conviene saber antes de lanzarlo:

1. **Tarda.** Cada ficha es una petición y la fuente limita la tasa: a 0,6 s por petición y con una
   latencia de ~0,2 s, salen unas cuatro fichas por segundo como mucho. Dos mil fichas son unos
   ocho o diez minutos, no instantáneo.
2. **Toma el bloqueo del relleno**, el mismo que usa el worker. Si otro proceso está leyendo
   fichas, este se detiene en lugar de duplicar peticiones contra un origen que responde 429.
3. **Se puede cortar.** Lo leído se guarda tanda a tanda y lo que falta sigue marcado como
   pendiente, así que `Ctrl+C` no pierde nada: volver a lanzarlo continúa donde se quedó.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

sys.path.insert(0, "src")

from contratacion.aplicacion.casos_uso.recoger_items import recoger_items
from contratacion.infraestructura.adaptadores.salida.bd.bloqueo import bloqueo_de_ingesta
from contratacion.infraestructura.adaptadores.salida.bd.ingesta import RepositorioIngesta
from contratacion.infraestructura.adaptadores.salida.bd.sesion import cerrar_bd, obtener_motor
from contratacion.infraestructura.config.ajustes import obtener_ajustes
from contratacion.tareas.planificador import BLOQUEO_DETALLE, fuentes_por_defecto


def _minutos(segundos: float) -> str:
    """Duración legible: «1 min 20 s» dice más que «80,3 s»."""
    if segundos < 60:
        return f"{segundos:.0f} s"
    return f"{segundos // 60:.0f} min {segundos % 60:.0f} s"


async def main() -> int:
    ajustes = obtener_ajustes()
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument(
        "--tanda",
        type=int,
        default=ajustes.fichas_items_por_ciclo,
        help="Fichas por tanda (por defecto, el valor del ciclo: %(default)s).",
    )
    analizador.add_argument(
        "--maximo",
        type=int,
        default=0,
        help="Tope total de fichas en esta ejecución. 0 significa todas.",
    )
    analizador.add_argument(
        "--simular",
        action="store_true",
        help="Solo cuenta lo que falta; no pide nada a la fuente.",
    )
    opciones = analizador.parse_args()

    repositorio = RepositorioIngesta(obtener_motor())

    async with bloqueo_de_ingesta(BLOQUEO_DETALLE) as conexion:
        if conexion is None:
            print("Otro proceso ya está leyendo fichas. Nada que hacer aquí.")
            await cerrar_bd()
            return 0

        definiciones = await fuentes_por_defecto(
            repositorio,
            intervalo_min=ajustes.intervalo_ingesta_min,
            ventana_solape_ciclos=ajustes.ventana_solape_ciclos,
        )
        con_ficha = [d.codigo for d in definiciones if hasattr(d.adaptador, "items")]
        pendientes = await repositorio.contar_sin_items(con_ficha)
        print(f"Fuentes con ficha: {', '.join(con_ficha) or 'ninguna'}")
        print(f"Fichas pendientes de leer: {pendientes}")

        if opciones.simular or not pendientes:
            await cerrar_bd()
            return 0

        inicio = time.monotonic()
        leidas = 0
        con_items = 0
        fallidas = 0
        vueltas = 0

        try:
            while True:
                if opciones.maximo and leidas >= opciones.maximo:
                    print(f"\nSe alcanzó el tope de {opciones.maximo} fichas.")
                    break

                tanda = opciones.tanda
                if opciones.maximo:
                    tanda = min(tanda, opciones.maximo - leidas)

                resultado = await recoger_items(
                    repositorio, definiciones, presupuesto_peticiones=tanda, limite=tanda
                )
                vueltas += 1
                leidas += resultado.revisados
                con_items += resultado.con_items
                fallidas += resultado.fallidos

                transcurrido = time.monotonic() - inicio
                ritmo = leidas / transcurrido if transcurrido else 0
                falta = resultado.quedan
                # El tiempo estimado se calcula con el ritmo **real** de esta ejecución, que incluye
                # la latencia y los enfriamientos por 429. Un cálculo teórico («0,6 s por ficha»)
                # mentiría justo en los días en que la fuente va lenta, que son los que importan.
                estimado = f" · quedan ~{_minutos(falta / ritmo)}" if ritmo > 0 and falta else ""
                print(
                    f"[{vueltas:3}] leídas {resultado.revisados:4} · "
                    f"con ítems {resultado.con_items:4} · sin detalle {resultado.sin_items:3} · "
                    f"fallidas {resultado.fallidos:2} · faltan {falta:5}{estimado}"
                )

                # Parar por «nada revisado» y no solo por «nada pendiente» evita un bucle infinito
                # si la fuente deja de responder: en ese caso los pendientes no bajan, y sin esta
                # salida el guion se quedaría girando contra un origen que ya no contesta.
                if resultado.revisados == 0 or falta == 0:
                    break
        except KeyboardInterrupt:
            print("\nInterrumpido. Lo leído ya está guardado; se puede continuar después.")

        transcurrido = time.monotonic() - inicio
        print()
        resumen = f"Fichas leídas en esta ejecución: {leidas} en {_minutos(transcurrido)}"
        print(f"{resumen} ({vueltas} tandas)")
        print(f"  con ítems: {con_items} · sin detalle: {leidas - con_items - fallidas}")
        print(f"  fallidas: {fallidas}")
        print(f"  pendientes todavía: {await repositorio.contar_sin_items(con_ficha)}")

    await cerrar_bd()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
