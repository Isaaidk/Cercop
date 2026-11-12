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
import contextlib
import logging
import os
import sys
import time
from pathlib import Path

from contratacion.aplicacion.casos_uso.atender_tdr import atender_lote
from contratacion.aplicacion.casos_uso.buscar_registros import obtener_catalogos
from contratacion.aplicacion.casos_uso.mantener_registros import (
    ResultadoMantenimiento,
    mantener_registros,
)
from contratacion.aplicacion.casos_uso.operar_ingesta import (
    PASO_COMPROBACION_SEG,
    SolicitudCiclo,
    consumir_solicitud,
)
from contratacion.aplicacion.casos_uso.revisar_alertas import revisar_alertas
from contratacion.aplicacion.casos_uso.seguimiento_ofertas import recordar_cierres
from contratacion.infraestructura.adaptadores.salida.bd.bloqueo import bloqueo_de_ingesta
from contratacion.infraestructura.adaptadores.salida.bd.consultas import RepositorioConsultasBd
from contratacion.infraestructura.adaptadores.salida.bd.ingesta import RepositorioIngesta
from contratacion.infraestructura.adaptadores.salida.bd.mantenimiento import (
    RepositorioMantenimientoBd,
)
from contratacion.infraestructura.adaptadores.salida.bd.radar import RepositorioRadar
from contratacion.infraestructura.adaptadores.salida.bd.seguimiento import (
    RepositorioSeguimiento,
)
from contratacion.infraestructura.adaptadores.salida.bd.sesion import cerrar_bd, obtener_motor
from contratacion.infraestructura.adaptadores.salida.bd.tdr import RepositorioTdr
from contratacion.infraestructura.adaptadores.salida.cache.cliente import (
    cerrar_cache,
    obtener_cache,
)
from contratacion.infraestructura.config.ajustes import obtener_ajustes
from contratacion.tareas.planificador import (
    ejecutar_todos,
    ejecutar_vigilancia,
    leer_fichas_nuevas,
    leer_fichas_prioritarias,
)

registro = logging.getLogger("contratacion.worker")

ESPERA_MINIMA_SEG = 5.0
# Lotes seguidos por pasada de la cola de TDR. Si quedan más, la pasada siguiente empieza enseguida.
_TOPE_LOTES_TDR_POR_VUELTA = 4
# Cada cuánto se mira la cola cuando está vacía. Es una lectura de índice: no cuesta nada, y es lo
# que separa «el TDR está en segundos» de «el TDR está cuando acabe el ciclo».
_ESPERA_COLA_TDR_SEG = 2.0


# `True` mientras corre el bucle completo (`servir`). Cada trabajo suelto (`--una-vez`,
# `--vigilancia`, `--mantenimiento`) abre y cierra su caché y su pool; dentro del bucle eso era un
# error: la cola de TDR corre **a la vez** en otra tarea, y cerrar el pool al acabar cada vigilancia
# (cada dos minutos y medio) le tiraba el motor debajo y obligaba a reabrir todas las conexiones.
# En el bucle el pool y la caché viven lo que vive el proceso y se cierran una vez, al salir.
_EN_BUCLE = False


async def _cerrar_si_suelto() -> None:
    """Cierra caché y pool solo si el trabajo corre suelto, no dentro del bucle."""
    if _EN_BUCLE:
        return
    await cerrar_cache()
    await cerrar_bd()


async def _atender_cola() -> int:
    """Baja los TDR pendientes del momento, hasta el tope. Cero si no había ninguno."""
    hechos = 0
    repositorio = RepositorioTdr(obtener_motor())
    carpeta = Path(obtener_ajustes().tdr_dir)
    for _ in range(_TOPE_LOTES_TDR_POR_VUELTA):
        try:
            atendidos = await atender_lote(repositorio, carpeta)
        except Exception:  # noqa: BLE001 - un TDR no puede tumbar la ingesta
            registro.exception("No se pudo atender un lote de TDR pendientes.")
            break
        if not atendidos:
            break
        hechos += atendidos
    return hechos


async def _servir_cola_tdr() -> None:
    """Atiende la cola de TDR por su cuenta, sin esperar a la ingesta.

    Antes la cola se miraba dentro del bucle principal, y un ciclo completo —búsquedas, páginas de
    OCDS y fichas de CPC— puede durar muchos minutos. Quien pedía un TDR en ese rato esperaba a que
    terminara. Es una tarea aparte porque las dos cosas no comparten nada: la ingesta habla con los
    datos abiertos y esto baja archivos de la ficha de cada proceso.
    """
    ajustes = obtener_ajustes()
    while True:
        try:
            hechos = await _atender_cola()
            # Los ítems del proceso que alguien está armando se leen aquí, sin esperar al ciclo.
            if await leer_fichas_prioritarias(
                RepositorioIngesta(obtener_motor()),
                obtener_cache(),
                intervalo_min=ajustes.intervalo_ingesta_min,
                ventana_solape_ciclos=ajustes.ventana_solape_ciclos,
            ):
                hechos += 1
        except Exception:  # noqa: BLE001 - la cola no puede morir por un fallo suelto
            registro.exception("Falló una pasada de la cola de TDR.")
            hechos = 0
        await asyncio.sleep(0.5 if hechos else _ESPERA_COLA_TDR_SEG)


async def _alertas() -> None:
    """Avisa de oportunidades nuevas. Un fallo aquí no puede parar la ingesta.

    Va bajo el mismo bloqueo de asesoría que la ingesta (clave «alertas»): con dos réplicas del
    worker, las dos revisarían las mismas alertas a la vez y cada aviso saldría dos veces. Quien no
    obtiene el bloqueo se salta la vuelta; la otra réplica la está haciendo.
    """
    try:
        async with bloqueo_de_ingesta("alertas") as conexion:
            if conexion is None:
                registro.info("Otra réplica está revisando las alertas; se omite esta vuelta.")
                return
            await _revisar_alertas_y_cierres()
    except Exception:  # noqa: BLE001 - ni sin base para el bloqueo puede caer el bucle
        registro.exception("No se pudo tomar el bloqueo de las alertas.")


async def _revisar_alertas_y_cierres() -> None:
    try:
        await revisar_alertas(RepositorioRadar(obtener_motor()))
    except Exception:  # noqa: BLE001 - las alertas no pueden tumbar el bucle
        registro.exception("No se pudieron revisar las alertas.")
    try:
        await recordar_cierres(RepositorioSeguimiento(obtener_motor()))
    except Exception:  # noqa: BLE001 - los recordatorios no pueden tumbar el bucle
        registro.exception("No se pudieron revisar los recordatorios de cierre.")


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
        await _cerrar_si_suelto()

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
        resultados = await ejecutar_vigilancia(
            repositorio,
            obtener_cache(),
            intervalo_min=ajustes.intervalo_ingesta_min,
            ventana_solape_ciclos=ajustes.ventana_solape_ciclos,
            presupuesto_peticiones=ajustes.presupuesto_peticiones_ciclo,
        )
        # Las ínfimas nuevas se publican con sus CPC: se leen sus fichas en esta misma vuelta y,
        # si se escribió alguno, se sube la generación y se dejan calientes los desplegables.
        if any(resultado.nuevos for resultado in resultados) and await leer_fichas_nuevas(
            repositorio,
            obtener_cache(),
            intervalo_min=ajustes.intervalo_ingesta_min,
            ventana_solape_ciclos=ajustes.ventana_solape_ciclos,
            fichas=ajustes.fichas_por_vigilancia,
        ):
            await _precalentar_catalogos()
    finally:
        await _cerrar_si_suelto()


async def mantener_historico(*, simular: bool = False) -> ResultadoMantenimiento:
    """Una vuelta de mantenimiento: vencimientos que invalidan y filas que se retiran.

    Abre y cierra su propia caché, como los otros dos trabajos del bucle, que no la tienen abierta.
    El caso de uso se encarga de subir la generación solo si algo cambió de verdad.

    No consulta la fuente ni gasta presupuesto: es base de datos y caché, y por eso puede correr
    cada cinco minutos sin acercarse al límite de tasa del SERCOP.
    """
    ajustes = obtener_ajustes()
    try:
        repositorio = RepositorioMantenimientoBd(obtener_motor())
        await repositorio.asegurar_particiones()
        return await mantener_registros(
            repositorio,
            obtener_cache(),
            intervalo_seg=ajustes.intervalo_mantenimiento_seg,
            dias_retencion=ajustes.purga_plazo_dias,
            maximo_por_vuelta=ajustes.purga_max_filas_por_vuelta,
            simular=simular,
        )
    finally:
        await _cerrar_si_suelto()


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


async def servir() -> int:
    """El worker completo: la ingesta y, a su lado, la cola de TDR."""
    global _EN_BUCLE
    _EN_BUCLE = True
    cola = asyncio.create_task(_servir_cola_tdr(), name="cola-tdr")
    try:
        return await bucle()
    finally:
        cola.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await cola
        _EN_BUCLE = False
        await cerrar_cache()
        await cerrar_bd()


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
    intervalo_mantenimiento = max(30, ajustes.intervalo_mantenimiento_seg)
    registro.info(
        "Worker iniciado. Ciclo completo: %s min. Vigilancia del listado: %s s. "
        "Mantenimiento: %s s (retirar lo vencido hace %s días, %s por vuelta).",
        ajustes.intervalo_ingesta_min,
        intervalo_corto,
        intervalo_mantenimiento,
        ajustes.purga_plazo_dias,
        ajustes.purga_max_filas_por_vuelta or "nada",
    )

    # Las dos horas se calculan sobre `time.monotonic()`, no sobre la hora del reloj: un ajuste de
    # hora del sistema —o un salto por NTP— no debe provocar una ráfaga de ciclos ni dejar el bucle
    # esperando una hora que ya pasó.
    proximo_ciclo = 0.0
    proxima_vigilancia = 0.0
    proxima_comprobacion = 0.0
    # El mantenimiento se retrasa una vuelta: en el arranque toca un ciclo completo, que es lo que
    # trae los datos, y el mantenimiento solo mira vencimientos de lo que ya está guardado.
    proximo_mantenimiento = time.monotonic() + intervalo_mantenimiento

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
            await _alertas()
        elif momento >= proxima_vigilancia:
            proxima_vigilancia = momento + intervalo_corto
            try:
                await vigilar_listado()
            except Exception:  # noqa: BLE001 - ni por una vigilancia fallida
                registro.exception("La vigilancia falló; se continuará con la siguiente.")
            await _alertas()

        # El mantenimiento va **detrás** del ciclo y de la vigilancia, en el mismo bucle y no en un
        # proceso aparte: no consulta la fuente, así que no compite por la cuota, pero sí compite
        # por la base de datos, y aquí queda claro que lo primero es traer los datos.
        if momento >= proximo_mantenimiento:
            proximo_mantenimiento = momento + intervalo_mantenimiento
            try:
                resultado = await mantener_historico()
                registro.info("Mantenimiento: %s", resultado.resumen())
            except Exception:  # noqa: BLE001 - el mantenimiento no puede tumbar la ingesta
                registro.exception("El mantenimiento falló; se continuará con el siguiente.")

        momento = time.monotonic()
        # El sueño llega hasta la hora que toque, pero nunca más allá del siguiente vistazo a las
        # peticiones: `proxima_comprobacion` es el techo que trocea la espera.
        espera = (
            min(proximo_ciclo, proxima_vigilancia, proxima_comprobacion, proximo_mantenimiento)
            - momento
        )
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
    # El mantenimiento, solo. Sirve para no esperar cinco minutos a ver si los vencimientos mueven
    # la generación, y con `--simular` para saber cuánto retiraría **antes** de retirarlo.
    parser.add_argument(
        "--mantenimiento",
        action="store_true",
        help="Ejecuta una sola vuelta de mantenimiento (vencimientos y retención) y termina.",
    )
    parser.add_argument(
        "--simular",
        action="store_true",
        help="Con --mantenimiento: cuenta lo que se retiraría sin borrar nada.",
    )
    argumentos = parser.parse_args(argv)

    # El worker no lleva los topes del API: la ingesta y el mantenimiento tienen consultas largas
    # legítimas, y el bloqueo de ingesta vive en una conexión ociosa durante todo el ciclo. Se fija
    # **antes** de leer los ajustes (que se leen una vez por proceso) y solo si el entorno no dice
    # otra cosa, para que se pueda poner un tope al worker a propósito.
    os.environ.setdefault("BD_STATEMENT_TIMEOUT_MS", "0")
    os.environ.setdefault("BD_IDLE_TX_TIMEOUT_MS", "0")
    os.environ.setdefault("BD_NOMBRE_APLICACION", "cercoapp-worker")

    logging.basicConfig(
        level=obtener_ajustes().log_nivel.upper(),
        format="%(asctime)s %(levelname)-5s %(name)s %(message)s",
    )

    try:
        if argumentos.mantenimiento:
            resultado = asyncio.run(mantener_historico(simular=argumentos.simular))
            print(resultado.resumen())
            return 0
        if argumentos.vigilancia:
            asyncio.run(vigilar_listado())
            return 0
        if argumentos.una_vez:
            return asyncio.run(ejecutar_un_ciclo())
        return asyncio.run(servir())
    except KeyboardInterrupt:
        registro.info("Worker detenido por el usuario.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
