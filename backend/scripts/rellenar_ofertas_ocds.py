"""Trae el **año entero** del listado general de OCDS, por tandas y reanudable.

    .\\.venv\\Scripts\\python.exe scripts\\rellenar_ofertas_ocds.py --simular
    .\\.venv\\Scripts\\python.exe scripts\\rellenar_ofertas_ocds.py
    .\\.venv\\Scripts\\python.exe scripts\\rellenar_ofertas_ocds.py --maximo 400
    .\\.venv\\Scripts\\python.exe scripts\\rellenar_ofertas_ocds.py --desde-pagina 10123

**PARA EL HISTÓRICO COMPLETO, USA `scripts/importar_ocds_masivo.py`.** Este guion sigue siendo la
forma de tapar un hueco **reciente** —los últimos días, o un tramo que quedó a medias— página a
página, pero para cargar un año entero es la vía lenta y no tiene sentido: medido, ~9 s por página
(429 cada cinco o seis, con esperas de 3 a 29 s) y ~26 horas para las 10.363 páginas del año. El
portal publica los mismos procedimientos en ficheros mensuales y aquel guion los importa en minutos:
**12 peticiones** en lugar de 10.363. Subir el intervalo entre peticiones no ayuda —2,5 s dieron
21 s por página— porque el límite de la fuente es una cuota por ventana, no la ráfaga.

POR QUÉ HACE FALTA. Desde el cambio a la ingesta general, el worker lee el **rabo** del listado: las
últimas páginas del año, que es donde está lo que se acaba de publicar. Eso mantiene al día la tabla
de ofertas, pero arranca vacío hacia atrás: lo publicado **antes** de que la fuente general
existiera no entra por ningún lado, y sin él los filtros del panel —que buscan sobre lo ya
ingestado— no encuentran más que lo reciente. Este guion recorre el año de atrás hacia adelante una
sola vez; el worker se encarga del resto a partir de ahí.

CÓMO SE HACE. Camina hacia atrás desde la última página hasta la 2, una página por petición, en
tandas del tamaño del ciclo. Cada tanda es un ciclo normal —los mismos mapeos, el mismo `upsert` por
huella, la misma invalidación de caché— con el adaptador arrancado en otra página. Se puede cortar
con `Ctrl+C` en cualquier momento: lo leído ya está guardado y el guion dice por dónde seguir.

CUÁNTO CUESTA. Medido contra la fuente el 2026-10-01: el año tiene **10.363 páginas** de 10 filas
—unas 103.600 filas, alrededor de 1 GB con los índices— y el ritmo real de una tanda fue de unos
**12 s por página**: 5 páginas tardaron 1 minuto, con un 429 y 29 s de espera dentro. Son unas **34
horas** de reloj para el año entero. Se lanza por tandas —o de una vez y se deja corriendo—; no hay
prisa, porque el worker ya cubre lo nuevo mientras tanto.

MIENTRAS CORRE, EL WORKER SIGUE CON SU CICLO. Cada tanda toma el bloqueo de la ingesta de OCDS y lo
suelta al terminar, así que el ciclo del worker se salta OCDS solo durante esa tanda y lo publicado
entretanto entra por su rabo como siempre. Si la tanda se encuentra el bloqueo tomado, espera a que
el worker acabe en lugar de pisarlo: dos procesos contra la misma fuente, con dos limitadores
distintos, es la forma más rápida de ganarse un 429 de veinte segundos.

LA MARCA DE AGUA NO SE MUEVE. Una tanda de relleno no cubre el final del listado —lee el principio
del año—, así que se declara parcial, y con eso la marca de agua se queda donde estaba. Si declarara
«completo», el ciclo siguiente creería estar al día y leería las dos páginas de siempre.

NO SE TOCA LA CONFIGURACIÓN DE LA FUENTE. Los valores de intervalo y presupuesto que se le pasan al
ciclo son **los mismos** que usa el worker, para no reescribir la fila de la fuente en cada tanda.
Por eso la tanda no puede ser mayor que el presupuesto del ciclo: por encima de eso habría que
cambiar la configuración de la fuente, y eso no lo hace un guion de mantenimiento.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from datetime import UTC, datetime

sys.path.insert(0, "src")

from contratacion.aplicacion.casos_uso.ejecutar_ingesta import (
    DefinicionFuente,
    ejecutar_ciclo,
)
from contratacion.aplicacion.puertos.fuente import ResultadoExtraccion
from contratacion.dominio.ingesta import Presupuesto
from contratacion.infraestructura.adaptadores.salida.bd.bloqueo import bloqueo_de_ingesta
from contratacion.infraestructura.adaptadores.salida.bd.ingesta import RepositorioIngesta
from contratacion.infraestructura.adaptadores.salida.bd.sesion import cerrar_bd, obtener_motor
from contratacion.infraestructura.adaptadores.salida.cache.cliente import (
    cerrar_cache,
    obtener_cache,
)
from contratacion.infraestructura.adaptadores.salida.fuentes import ocds, ocds_mapeos
from contratacion.infraestructura.adaptadores.salida.fuentes.limitador import (
    INTERVALO_MINIMO,
    LimitadorTasa,
)
from contratacion.infraestructura.config.ajustes import obtener_ajustes

# Filas que declara la API por página. Se comprobó en la sonda: siempre diez.
FILAS_POR_PAGINA = 10
# Ritmo real medido el 2026-10-01: cinco páginas en 1 minuto, con un 429 y 29 s de espera dentro. Se
# usa esta cifra y no el cálculo teórico —0,6 s de intervalo mínimo más la latencia— porque ese se
# queda corto por un factor de diez: la fuente responde 429 con esperas de 11-29 s a menudo, y la
# estimación que no lo cuente miente en la dirección peligrosa ("unas horas" cuando son días).
SEGUNDOS_POR_PAGINA = 12.0
# Cuánto esperar cuando el bloqueo de OCDS está tomado —es decir, cuando el worker está en su ciclo—
# y cuántas veces antes de rendirse. Un ciclo con rescate tarda unos dos minutos y medio, así que
# veinte esperas de medio minuto cubren de sobra un ciclo entero y algo más.
ESPERA_BLOQUEO_SEG = 30.0
MAX_ESPERAS_BLOQUEO = 20
# Bytes por fila medidos en la base con `scripts/peso_de_datos.py` (2026-10-01, incluye índices).
BYTES_POR_FILA = 10_437


def _duracion(segundos: float) -> str:
    """Duración legible: «2 h 51 min» dice más que «10.260,4 s»."""
    if segundos < 60:
        return f"{segundos:.0f} s"
    if segundos < 3600:
        return f"{segundos // 60:.0f} min {segundos % 60:.0f} s"
    return f"{segundos // 3600:.0f} h {segundos % 3600 // 60:.0f} min"


def _megas(filas: int) -> str:
    megas = filas * BYTES_POR_FILA / (1024 * 1024)
    return f"{megas:.1f} MB" if megas < 100 else f"{megas:.0f} MB"


class FuenteRelleno(ocds.FuenteOcdsGeneral):
    """El modo relleno, con una diferencia que importa: **no mueve la marca de agua**.

    `cerrar_sincronizacion` avanza la marca de agua cuando la vuelta termina bien, y de ella deduce
    el ciclo normal cuántas páginas del rabo tiene que leer. Una tanda de relleno lee el principio
    del año, no el final: si moviera la marca de agua, el ciclo siguiente se creería al día y leería
    las dos páginas de siempre, dejando fuera —y en silencio— todo lo publicado durante las horas de
    relleno.

    Se declara **parcial**, que es lo que de verdad es: esta vuelta no cubrió el listado reciente.
    Con eso la marca de agua se conserva y el ciclo siguiente abre la ventana que haga falta.
    """

    async def extraer(self, desde: datetime, presupuesto: Presupuesto) -> ResultadoExtraccion:
        resultado = await super().extraer(desde, presupuesto)
        resultado.parcial = True
        return resultado


async def _paginas_del_anio(limitador: LimitadorTasa, anio: int) -> int | None:
    """Cuántas páginas tiene el año, preguntando la primera (una sola petición)."""
    payload = await limitador.solicitar_json(
        ocds.SEARCH_URL,
        {"year": anio, "search": "", "page": 1},
        etiqueta=f"general · {anio} · pág. 1",
    )
    if payload is None:
        return None
    total = payload.get("pages")
    return total if isinstance(total, int) and total >= 1 else None


async def main() -> int:
    ajustes = obtener_ajustes()
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument(
        "--anio",
        type=int,
        default=datetime.now(UTC).year,
        help="Año a recorrer (por defecto, el actual).",
    )
    analizador.add_argument(
        "--paginas",
        type=int,
        default=ajustes.paginas_generales_por_ciclo,
        help="Páginas por tanda (por defecto, las del ciclo: %(default)s).",
    )
    analizador.add_argument(
        "--desde-pagina",
        type=int,
        default=0,
        help="Página por la que empezar a caminar hacia atrás. 0 = la última del año.",
    )
    analizador.add_argument(
        "--maximo",
        type=int,
        default=0,
        help="Tope de páginas en esta ejecución. 0 significa todas las que falten.",
    )
    analizador.add_argument(
        "--pausa",
        type=float,
        default=90.0,
        help=(
            "Segundos de espera entre tandas, para dejar hueco al ciclo del worker "
            "(por defecto: %(default)s). 0 = sin pausa."
        ),
    )
    # El ritmo se puede subir, y subirlo **acelera** aunque parezca lo contrario. Con el de la
    # ingesta (0,6 s) se lanzan ráfagas de ocho peticiones y la fuente responde 429 en la
    # octava: cada 429 cuesta de 3 a 29 s de espera global a todo el proceso, así que leer
    # cuarenta páginas sale a diez segundos por página. Repartiendo esas mismas peticiones sin
    # ráfagas —un intervalo de dos a tres segundos— el 429 no llega y el ritmo sube. Es lo que se
    # mide con este parámetro: se prueban intervalos y se cuenta cuántos 429 provoca cada uno.
    analizador.add_argument(
        "--intervalo",
        type=float,
        default=INTERVALO_MINIMO,
        help=(
            "Segundos entre peticiones consecutivas (por defecto, los de la ingesta: %(default)s). "
            "Más grande evita las ráfagas que provocan los 429."
        ),
    )
    analizador.add_argument(
        "--simular",
        action="store_true",
        help="Solo calcula y muestra el plan; no escribe nada en la base.",
    )
    opciones = analizador.parse_args()

    # El adaptador usa el **mismo** limitador que la ingesta —semáforo, intervalo mínimo,
    # enfriamiento y reintentos—, así que el relleno no puede provocar un 429 que después pague el
    # worker; y uno propio y no compartido porque el worker corre en otro proceso. El intervalo sí
    # se puede aflojar desde `--intervalo`: lo que no se toca son los reintentos ni el enfriamiento.
    limitador = LimitadorTasa(intervalo_minimo=opciones.intervalo)
    pagina_tope = min(opciones.paginas, ajustes.presupuesto_peticiones_ciclo)
    if opciones.paginas > pagina_tope:
        print(
            f"El presupuesto de la fuente es {ajustes.presupuesto_peticiones_ciclo} peticiones "
            f"por ciclo y la tanda no lo puede superar sin reconfigurar la fuente: "
            f"se usan {pagina_tope}."
        )

    try:
        total = None
        desde_pagina = opciones.desde_pagina
        if not desde_pagina:
            total = await _paginas_del_anio(limitador, opciones.anio)
            if total is None:
                print(
                    "La fuente no respondió a la sonda. Se puede continuar sin ella indicando la "
                    "página por la que seguir: --desde-pagina <n>."
                )
                return 2
            desde_pagina = total

        if desde_pagina <= 1:
            print(f"La página {desde_pagina} ya es el principio del año: no hay nada que rellenar.")
            return 0

        # De la página de arranque hacia abajo, sin contar la 1: esa la pide el ciclo normal en cada
        # vuelta —la necesita para saber cuántas páginas hay—, así que se leería dos veces.
        objetivo = desde_pagina - 1
        if opciones.maximo:
            objetivo = min(objetivo, opciones.maximo)

        print(f"OCDS {opciones.anio}")
        if total is not None:
            print(
                f"  el año tiene {total} páginas · {total * FILAS_POR_PAGINA} filas "
                f"· {_megas(total * FILAS_POR_PAGINA)} en la base con los índices"
            )
        print(
            f"  se camina de la página {desde_pagina} a la 2: {objetivo} páginas "
            f"· {objetivo * FILAS_POR_PAGINA} filas · ~{_megas(objetivo * FILAS_POR_PAGINA)}"
        )
        tandas = -(-objetivo // pagina_tope)  # redondeo hacia arriba
        cuantas = "tanda" if tandas == 1 else "tandas"
        print(
            f"  en tandas de {pagina_tope}: {tandas} {cuantas} "
            f"· ~{_duracion(objetivo * SEGUNDOS_POR_PAGINA)} al ritmo medido de "
            f"{SEGUNDOS_POR_PAGINA:.0f} s por página —429 incluidos—"
        )
        if opciones.pausa:
            print(
                f"  ({opciones.pausa:.0f} s de pausa entre tandas, para que el worker lea el rabo)"
            )
        print(f"  ritmo: una petición cada {opciones.intervalo:.1f} s")

        if opciones.simular:
            return 0

        repositorio = RepositorioIngesta(obtener_motor())
        cache = obtener_cache()
        leidas = 0
        nuevas = 0
        actualizadas = 0
        iguales = 0
        vueltas = 0
        cortado = False
        inicio = time.monotonic()

        try:
            print(
                "\nEl bloqueo de OCDS se toma **por tanda**, no durante toda la ejecución: así el"
            )
            print("ciclo del worker no se queda sin correr y lo publicado entra por su rabo como")
            print("siempre. Si la tanda se encuentra el bloqueo tomado, espera a que termine.\n")

            esperas = 0
            while leidas < objetivo and desde_pagina > 1:
                paginas_tanda = min(pagina_tope, objetivo - leidas)
                definicion = DefinicionFuente(
                    codigo=ocds.CODIGO,
                    nombre="Procesos publicados (OCDS)",
                    endpoint_base=ocds.SEARCH_URL,
                    # Sin términos: el relleno del año no rescata palabras clave, eso es trabajo
                    # del ciclo y lo hace con su propio presupuesto.
                    adaptador=FuenteRelleno(
                        (),
                        paginas_por_ciclo=paginas_tanda,
                        desde_pagina=desde_pagina,
                        limitador=limitador,
                        anios=[opciones.anio],
                    ),
                    mapeos_por_defecto=ocds_mapeos.MAPEOS_POR_DEFECTO,
                    # Un punto de partida muy antiguo no cambia lo que se lee —el modo relleno
                    # camina hacia atrás desde la página que se le dice—, pero sí fija el tope
                    # de páginas de la tanda: con una fecha lejana no lo recorta la estimación
                    # por tiempo, que es lo que se quiere aquí.
                    desde=datetime(opciones.anio, 1, 1, tzinfo=UTC),
                    # **No** se declara listado completo: lo que se lee es el principio del año,
                    # no la foto de lo vigente, y declararlo cerraría como «ya no vigente» casi
                    # todo lo que hay en la base.
                )

                async with bloqueo_de_ingesta(ocds.CODIGO) as conexion:
                    if conexion is None:
                        # El worker está en su ciclo. Se cede el turno: interrumpirlo o pisarlo
                        # serían dos procesos contra la misma fuente con dos limitadores distintos,
                        # que es la forma más rápida de ganarse un 429 largo.
                        esperas += 1
                        if esperas > MAX_ESPERAS_BLOQUEO:
                            print("      el bloqueo lleva ocupado demasiado: se corta aquí.")
                            cortado = True
                            break
                        print(
                            f"      el worker está ingestando OCDS; se espera "
                            f"{ESPERA_BLOQUEO_SEG} s ({esperas}/{MAX_ESPERAS_BLOQUEO})"
                        )
                        await asyncio.sleep(ESPERA_BLOQUEO_SEG)
                        continue
                    esperas = 0
                    resultado = await ejecutar_ciclo(
                        definicion,
                        repositorio,
                        cache,
                        intervalo_min=ajustes.intervalo_ingesta_min,
                        ventana_solape_ciclos=ajustes.ventana_solape_ciclos,
                        presupuesto_peticiones=ajustes.presupuesto_peticiones_ciclo,
                    )
                vueltas += 1

                # Una página que falló se contó como petición pero no se leyó, así que no se
                # descuenta: la próxima vuelta la reintenta en vez de saltársela.
                fallo = ocds.AVISO_SIN_RESPUESTA in resultado.avisos
                consumidas = resultado.peticiones - (1 if fallo else 0)
                leidas += consumidas
                desde_pagina -= consumidas
                nuevas += resultado.nuevos
                actualizadas += resultado.actualizados
                iguales += resultado.iguales

                transcurrido = time.monotonic() - inicio
                ritmo = leidas / transcurrido if transcurrido else 0
                faltan = objetivo - leidas
                estimado = ""
                if ritmo > 0 and faltan > 0:
                    estimado = f" · quedan ~{_duracion(faltan / ritmo)}"
                # Los 429 se cuentan y se imprimen porque son la mitad del coste real: cada uno
                # cuesta entre 3 y 29 s de espera, así que un ritmo de diez segundos por página se
                # entiende —o se corrige— sabiendo cuántos hubo. El limitador ya los anota en
                # `codigos_recibidos`; solo hay que leerlos.
                bloqueos = sum(1 for codigo in limitador.codigos_recibidos if codigo == 429)
                print(
                    f"[{vueltas:3}] páginas {consumidas:3} (hasta la {desde_pagina:5}) · "
                    f"nuevas {resultado.nuevos:4} · actualizadas {resultado.actualizados:4} · "
                    f"iguales {resultado.iguales:4} · sin mapear {resultado.sin_mapear:3} · "
                    f"429 {bloqueos:3} · faltan {faltan:5}{estimado}"
                )

                # Cualquier aviso —fallo de la fuente o presupuesto agotado— corta aquí: la
                # fuente ya está diciendo que no quiere más, y seguir dándole es lo que provoca
                # un bloqueo más largo. Lo leído está guardado y se reanuda por la misma página.
                if resultado.avisos:
                    for aviso in resultado.avisos:
                        print(f"      aviso: {aviso}")
                    cortado = True
                    break
                if consumidas == 0:
                    print("      la fuente no devolvió ninguna página: se corta aquí.")
                    cortado = True
                    break

                # Pausa entre tandas, y no es una cortesía: sin ella el relleno volvería a tomar el
                # bloqueo en cuanto lo suelta —termina una tanda y empieza la siguiente— y el ciclo
                # del worker no llegaría a ver la fuente en toda la ejecución. Con la pausa, el
                # worker tiene un hueco en cada vuelta para leer su rabo, que es lo que mantiene al
                # día lo recién publicado mientras el relleno mira hacia atrás.
                if leidas < objetivo and desde_pagina > 1 and opciones.pausa:
                    await asyncio.sleep(opciones.pausa)
        except KeyboardInterrupt:
            cortado = True
            print("\nInterrumpido. Lo leído ya está guardado.")

        transcurrido = time.monotonic() - inicio
        print()
        print(
            f"Páginas leídas en esta ejecución: {leidas} en {_duracion(transcurrido)} "
            f"({vueltas} tandas)"
        )
        bloqueos = sum(1 for codigo in limitador.codigos_recibidos if codigo == 429)
        print(f"  nuevas: {nuevas} · actualizadas: {actualizadas} · iguales: {iguales}")
        print(f"  429 recibidos: {bloqueos} (cada uno cuesta de 3 a 29 s de espera)")
        print(f"  filas estimadas en la base: ~{_megas(leidas * FILAS_POR_PAGINA)}")
        if desde_pagina <= 1:
            print(f"  el año {opciones.anio} queda recorrido entero, de la última página a la 2.")
        else:
            motivo = " (se cortó antes de tiempo)" if cortado else ""
            print(f"  faltan {desde_pagina - 1} páginas para llegar al principio{motivo}.")
            print(f"\nReanuda con:  --desde-pagina {desde_pagina}")
    finally:
        await limitador.cerrar()
        await cerrar_cache()
        await cerrar_bd()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
