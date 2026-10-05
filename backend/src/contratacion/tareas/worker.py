"""Proceso `worker`: la ingesta automática.

Es el segundo punto de entrada del monolito modular y el que **acumula el activo del producto**. Se
mantiene separado del API por dos razones:

1. Ninguna petición de un usuario debe llegar a la fuente oficial. El único que habla con el SERCOP
   es este proceso, con su presupuesto de peticiones.
2. La ingesta puede tardar: si viviera dentro del API, bloquearía la atención a los usuarios.

Ejecución:

    # Bucle continuo (producción)
    python -m contratacion.tareas.worker

    # Un solo ciclo (pruebas, despliegues con cron externo)
    python -m contratacion.tareas.worker --una-vez
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time

from contratacion.aplicacion.casos_uso.buscar_registros import obtener_catalogos
from contratacion.aplicacion.casos_uso.operar_ingesta import (
    PASO_COMPROBACION_SEG,
    SolicitudCiclo,
    consumir_solicitud,
)
from contratacion.infraestructura.adaptadores.salida.bd.consultas import RepositorioConsultasBd
from contratacion.infraestructura.adaptadores.salida.bd.ingesta import RepositorioIngesta
from contratacion.infraestructura.adaptadores.salida.bd.sesion import cerrar_bd, obtener_motor
from contratacion.infraestructura.adaptadores.salida.cache.cliente import (
    cerrar_cache,
    obtener_cache,
)
from contratacion.infraestructura.config.ajustes import obtener_ajustes
from contratacion.tareas.planificador import ejecutar_todos, ejecutar_vigilancia

registro = logging.getLogger("contratacion.worker")

ESPERA_MINIMA_SEG = 5.0


async def _precalentar_catalogos() -> None:
    """Deja calientes los desplegables justo después del ciclo.

    La caché se invalida **en bloque** al subir la generación: todas las claves calculadas con la
    anterior dejan de encontrarse a la vez. Los desplegables son la consulta más cara del sistema
    —recorren el histórico entero— y se piden al abrir cada panel, así que sin esto la primera
    tanda de personas que entrara después del ciclo pagaría el recorrido completo, todas a la vez,
    justo en el momento en que la caché acaba de quedarse vacía.

    Se hace aquí, en el worker, y no dentro del caso de uso de la ingesta: el worker ya conoce las
    dos mitades —lo que escribe y lo que se lee— y así la ingesta sigue sin depender de las
    consultas del panel. Es el mismo criterio que separa el `worker` del API.

    No hace falta saber si el ciclo cambió algo: si la generación no se movió, la clave es la misma
    y esto es un acierto de caché. Cuesta un comando, y a cambio no hay que averiguar nada.

    Un fallo aquí **no puede tumbar el ciclo**. Precalentar es una mejora de latencia, y el ciclo de
    ingesta es el activo del producto: perder el precalentado cuesta unos segundos de base de datos
    en la siguiente visita, perder el ciclo cuesta datos.
    """
    try:
        await obtener_catalogos(
            cache=obtener_cache(),
            repositorio=RepositorioConsultasBd(obtener_motor()),
            ttl_seg=obtener_ajustes().ttl_catalogo_seg,
        )
    except Exception:  # noqa: BLE001 - precalentar no es requisito del ciclo
        registro.warning("No se pudieron precalentar los catálogos", exc_info=False)


async def ejecutar_un_ciclo() -> int:
    """Ejecuta un ciclo completo y devuelve el código de salida."""
    ajustes = obtener_ajustes()
    repositorio = RepositorioIngesta(obtener_motor())

    try:
        resultados = await ejecutar_todos(
            repositorio,
            obtener_cache(),
            intervalo_min=ajustes.intervalo_ingesta_min,
            ventana_solape_ciclos=ajustes.ventana_solape_ciclos,
            presupuesto_peticiones=ajustes.presupuesto_peticiones_ciclo,
            fichas_items=ajustes.fichas_items_por_ciclo,
            paginas_generales=ajustes.paginas_generales_por_ciclo,
        )
        await _precalentar_catalogos()
    finally:
        await cerrar_cache()
        await cerrar_bd()

    if not resultados:
        registro.warning("Ninguna fuente se ingestó en este ciclo.")
        return 0
    return 1 if all(resultado.estado == "error" for resultado in resultados) else 0


async def vigilar_listado() -> None:
    """Vuelta corta: relee solo el listado de necesidades y no enciende nada más.

    Es el otro trabajo del worker, y va en su propia función porque tiene su propia cadencia y sus
    propias ausencias —ver `planificador.ejecutar_vigilancia`—: no consulta la cola de términos, no
    lee fichas y no invalida la caché. Lo que **sí** comparte con el ciclo completo son los ajustes
    de la fuente: `asegurar_fuente` guarda el intervalo y el presupuesto en la fila de la fuente, y
    mandar valores distintos en cada vuelta la haría cambiar de configuración dos veces por minuto.
    """
    ajustes = obtener_ajustes()
    repositorio = RepositorioIngesta(obtener_motor())

    try:
        await ejecutar_vigilancia(
            repositorio,
            obtener_cache(),
            intervalo_min=ajustes.intervalo_ingesta_min,
            ventana_solape_ciclos=ajustes.ventana_solape_ciclos,
            presupuesto_peticiones=ajustes.presupuesto_peticiones_ciclo,
        )
    finally:
        await cerrar_cache()
        await cerrar_bd()


async def _solicitud_de_ciclo() -> SolicitudCiclo | None:
    """Toma la petición que haya dejado el panel, si hay alguna.

    El bucle no tiene el caché abierto —cada trabajo abre el suyo y lo cierra al terminar—, así que
    se abre aquí, y solo para esto: es una lectura de una clave.

    Un fallo al preguntar **no puede** tumbar el worker: quedarse sin atender una petición cuesta un
    ciclo a mano, y morir cuesta la ingesta entera. Es la misma razón que protege al ciclo de un
    fallo de la fuente, y por eso se traga la excepción en lugar de propagarla.
    """
    try:
        return await consumir_solicitud(obtener_cache())
    except Exception:  # noqa: BLE001 - preguntar por la petición no puede tumbar el bucle
        registro.warning("No se pudo comprobar si hay un ciclo pedido", exc_info=False)
        return None


async def bucle() -> int:
    """Alterna las dos cadencias: la vuelta corta y el ciclo completo.

    No son dos bucles ni dos procesos: es **un** bucle que mira la hora y decide qué toca. Se hace
    así porque las dos cosas escriben las mismas tablas y comparten el control de tasa de la fuente,
    y dos bucles independientes acabarían solapándose justo en la petición que más cuesta.

    La hora del ciclo completo se da por servida **antes** de intentarlo, y eso no es un descuido:
    si solo avanzara al salir bien, un ciclo que falla se reintentaría en cada vuelta corta —cada
    dos minutos y medio, con las búsquedas por palabra clave y las fichas dentro—, que es
    exactamente lo que la fuente castiga con 429. Y como el reintento ocuparía cada vuelta, la
    vigilancia no llegaría a correr nunca.

    Cuando las dos coinciden, manda el ciclo completo: se trae el listado de NCO de todos modos, así
    que la vuelta corta no tendría nada que hacer, y su hora se reprograma desde ahí.

    Desde que existe el botón del panel hay una tercera cosa que mirar, y por eso el bucle duerme en
    tramos de `PASO_COMPROBACION_SEG` en vez de hasta la hora que toque: quien pulsa «ejecutar
    ahora» espera ver el ciclo arrancar, no descubrir dentro de un cuarto de hora que su petición
    estaba esperando a que venciera la vigilancia. El tramo no cuesta nada —es una lectura de caché—
    y a cambio el retardo de un ciclo a mano es de segundos.
    """
    ajustes = obtener_ajustes()
    intervalo_largo = max(60, ajustes.intervalo_ingesta_min * 60)
    intervalo_corto = max(10, ajustes.intervalo_vigilancia_seg)
    registro.info(
        "Worker iniciado. Ciclo completo: %s min. Vigilancia del listado: %s s.",
        ajustes.intervalo_ingesta_min,
        intervalo_corto,
    )

    # Las dos horas se calculan sobre `time.monotonic()`, no sobre la hora del reloj: un ajuste de
    # hora del sistema —o un salto por NTP— no debe provocar una ráfaga de ciclos ni dejar el bucle
    # esperando una hora que ya pasó.
    proximo_ciclo = 0.0
    proxima_vigilancia = 0.0
    proxima_comprobacion = 0.0

    while True:
        momento = time.monotonic()

        # Lo primero es atender lo que pidan a mano: si el dueño del sistema acaba de pedir un
        # ciclo, no debe esperar a que venza la vigilancia del listado. Se consume la petición —una
        # petición es una vez— y se da por servida la hora del ciclo completo, igual que en la
        # vuelta programada: un ciclo a mano **es** un ciclo, así que no viene seguido de otro
        # inmediato ni de una vuelta corta que ya no tendría nada que leer.
        if momento >= proxima_comprobacion:
            proxima_comprobacion = momento + PASO_COMPROBACION_SEG
            peticion = await _solicitud_de_ciclo()
            if peticion is not None:
                registro.info(
                    "Ciclo completo pedido desde el panel por %s; se adelanta.",
                    peticion.solicitado_por,
                )
                proximo_ciclo = momento + intervalo_largo
                proxima_vigilancia = momento + intervalo_corto
                try:
                    await ejecutar_un_ciclo()
                except Exception:  # noqa: BLE001 - el bucle nunca debe morir por un ciclo fallido
                    registro.exception("El ciclo pedido a mano falló; se seguirá con el siguiente.")
                continue

        if momento >= proximo_ciclo:
            proximo_ciclo = momento + intervalo_largo
            proxima_vigilancia = momento + intervalo_corto
            try:
                await ejecutar_un_ciclo()
            except Exception:  # noqa: BLE001 - el bucle nunca debe morir por un ciclo fallido
                registro.exception("El ciclo falló; se continuará con el siguiente.")
        elif momento >= proxima_vigilancia:
            proxima_vigilancia = momento + intervalo_corto
            try:
                await vigilar_listado()
            except Exception:  # noqa: BLE001 - ni por una vigilancia fallida
                registro.exception("La vigilancia falló; se continuará con la siguiente.")

        momento = time.monotonic()
        # El sueño llega hasta la hora que toque, pero nunca más allá del siguiente vistazo a las
        # peticiones: `proxima_comprobacion` es el techo que trocea la espera.
        espera = min(proximo_ciclo, proxima_vigilancia, proxima_comprobacion) - momento
        # `ESPERA_MINIMA_SEG` protege del caso en que las dos horas ya pasaron —un ciclo que tardó
        # más que su propio intervalo—: sin él el bucle giraría sin dormir y martillearía la fuente.
        await asyncio.sleep(max(ESPERA_MINIMA_SEG, espera))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Worker de ingesta de contratación pública.")
    parser.add_argument(
        "--una-vez",
        action="store_true",
        help="Ejecuta un único ciclo completo y termina (útil para cron externo o para probar).",
    )
    # La vuelta corta, sola. Sirve para dos cosas: comprobar que la vigilancia funciona sin esperar
    # al ciclo completo, y forzar una relectura del listado cuando se sospecha que una necesidad
    # está a punto de cerrarse. Si el worker está corriendo, el bloqueo hace que esta vuelta se
    # omita en vez de duplicar la lectura; hay que pararlo antes (`levantar.ps1 -Detener`).
    parser.add_argument(
        "--vigilancia",
        action="store_true",
        help="Ejecuta una sola vuelta corta (solo el listado de NCO) y termina.",
    )
    argumentos = parser.parse_args(argv)

    logging.basicConfig(
        level=obtener_ajustes().log_nivel.upper(),
        format="%(asctime)s %(levelname)-5s %(name)s %(message)s",
    )

    try:
        if argumentos.vigilancia:
            asyncio.run(vigilar_listado())
            return 0
        if argumentos.una_vez:
            return asyncio.run(ejecutar_un_ciclo())
        return asyncio.run(bucle())
    except KeyboardInterrupt:
        registro.info("Worker detenido por el usuario.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
