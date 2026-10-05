"""Planificador de la ingesta.

Recorre las fuentes una a una, cada una bajo su bloqueo de exclusión mutua. Si otra réplica ya está
ingestando esa fuente, se salta y sigue: no se solapan peticiones ni escrituras.

`fuentes_por_defecto` es el único punto donde se decide qué se ingestan. Añadir una fuente nueva es
añadir una entrada, no reescribir el planificador.

La decisión importante de este módulo es **qué términos se buscan en cada ciclo y desde cuándo**.
Equivocarla cuesta datos de forma irreversible, así que conviene tener presente el razonamiento:

- Se piden a la cola los términos **más urgentes**, no los primeros de la lista. La urgencia la
  define el tiempo sin buscarse, no la antigüedad del término: es lo que impide que los que se
  añaden después queden fuera para siempre.
- La ventana de búsqueda la fija el término **más nuevo** del lote. Basta con que uno nunca se haya
  buscado para leer desde la ventana inicial amplia: perder contrataciones es irreversible, mientras
  que releer datos ya vistos solo cuesta peticiones, y el presupuesto acota ese coste.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from contratacion.aplicacion.casos_uso.ejecutar_ingesta import (
    DefinicionFuente,
    ResultadoCiclo,
    ejecutar_ciclo,
)
from contratacion.aplicacion.casos_uso.recoger_items import (
    LIMITE_FICHAS_POR_CICLO,
    recoger_items,
)
from contratacion.aplicacion.generaciones import subir_generacion
from contratacion.aplicacion.puertos.cache import Cache
from contratacion.dominio.ingesta import DIAS_VENTANA_INICIAL, ventana_de_cola
from contratacion.infraestructura.adaptadores.salida.bd.bloqueo import bloqueo_de_ingesta
from contratacion.infraestructura.adaptadores.salida.bd.ingesta import RepositorioIngesta
from contratacion.infraestructura.adaptadores.salida.fuentes import (
    nco,
    nco_mapeos,
    ocds,
    ocds_mapeos,
)

registro = logging.getLogger(__name__)

LIMITE_TERMINOS_POR_CICLO = 20

# Nombre del bloqueo de la lectura de fichas. Va aparte del de cada fuente porque es otro trabajo:
# una réplica puede estar ingestando el listado mientras otra lee fichas, y lo que no puede pasar es
# que las dos lean las mismas fichas y gasten dos veces la misma cuota.
BLOQUEO_DETALLE = "items-cpc"


async def fuentes_por_defecto(
    repositorio: RepositorioIngesta,
    *,
    intervalo_min: int,
    ventana_solape_ciclos: int,
    dias_ventana_inicial: int = DIAS_VENTANA_INICIAL,
    limite_terminos: int = LIMITE_TERMINOS_POR_CICLO,
    incluir_ocds: bool = True,
    paginas_generales: int = ocds.PAGINAS_GENERALES_POR_CICLO,
) -> list[DefinicionFuente]:
    """Fuentes que se ingestan en cada ciclo.

    NCO se ingesta siempre y completa: una sola petición trae todo el listado, así que no hay nada
    que priorizar y ninguna suscripción puede quedar sin cubrir en él.

    OCDS se ingesta **por el rabo del listado general del año**: una secuencia ordenada por fecha en
    la que lo recién publicado está siempre al final. Cuesta una petición para saber cuántas páginas
    hay más las que hayan crecido, en lugar de una por término, año y página. Los términos de la
    cola que se le pasan al adaptador son solo el **rescate** de una palabra clave que nunca se ha
    buscado: el listado general da lo que se publique de aquí en adelante, no lo que se publicó
    antes de que esta fuente existiera.

    `incluir_ocds=False` devuelve solo NCO **sin consultar la cola**, y no es un atajo para ahorrar
    la consulta: es lo que permite la vuelta corta, que a esa cadencia no puede permitirse ni el
    rescate ni la lectura del rabo.
    """
    definiciones = [
        DefinicionFuente(
            codigo=nco.CODIGO,
            nombre="Necesidades de Contratación (NCO)",
            endpoint_base=nco.ENDPOINT,
            adaptador=nco.FuenteNco(),
            mapeos_por_defecto=nco_mapeos.MAPEOS_POR_DEFECTO,
            # El listado de NCO **es** la foto completa de lo vigente, sin paginar ni filtrar por
            # fecha. Es lo único que permite deducir que una necesidad que ya no aparece se cerró,
            # y esa deducción es información de negocio: distingue la que todavía admite proformas
            # de la que ya no. Declararlo mal tiene dos consecuencias opuestas y las dos malas: sin
            # él, `cerrados` es siempre cero y el histórico entero parece abierto para siempre;
            # con él puesto en una fuente que se consulta por partes, se cerraría lo que solo no se
            # llegó a mirar.
            listado_completo=True,
        )
    ]

    if not incluir_ocds:
        return definiciones

    # Solo se rescata lo que **nunca** se ha buscado, y no es un detalle: volver a buscar por
    # palabra clave algo que ya se buscó son ~45-60 peticiones por ciclo —unas 4.300 al día— por
    # datos que el listado general ya trae. Lo que se publique de aquí en adelante entra por el
    # rabo; el rescate existe para lo que se publicó **antes** de que esta fuente existiera, y eso
    # solo le falta a una palabra clave nueva.
    #
    # Se pide la cola entera y se filtra aquí, y no al revés, porque el orden de la cola es
    # `ultima_ingesta_en NULLS FIRST`: los que nunca se buscaron van primero, así que el límite no
    # los deja fuera.
    pendientes = [
        fila
        for fila in await repositorio.obtener_pendientes_de_ingesta(limite_terminos)
        if fila["ultima_ingesta_en"] is None
    ]
    momento = datetime.now(UTC)
    # La ventana del rabo la fija la **marca de agua** de la fuente —cuándo se cerró el último
    # ciclo—, así que no se pasa ninguna: que la calcule el caso de uso. Es lo que hace que el rabo
    # se adapte solo a una caída del worker: si estuvo seis horas parado, la ventana son esas seis
    # horas y lee las páginas que caben en ellas.
    #
    # La excepción es que haya palabras clave **nuevas**: esas necesitan la ventana ancha —hasta
    # noventa días—, porque lo que hay que recuperar es anterior a esta fuente. Mientras quede
    # alguna, el ciclo abre la ventana, y el rabo se acota con su propio tope de páginas.
    desde = (
        ventana_de_cola(
            [fila["ultima_ingesta_en"] for fila in pendientes],
            intervalo_min,
            ventana_solape_ciclos,
            momento,
            dias_ventana_inicial,
        )
        if pendientes
        else None
    )
    if pendientes:
        registro.info(
            "OCDS: %s términos nuevos por rescatar, desde %s",
            len(pendientes),
            desde.isoformat() if desde else "la marca de agua",
        )
    else:
        registro.info("OCDS: sin términos por rescatar; se lee el rabo del listado general")

    definiciones.append(
        DefinicionFuente(
            codigo=ocds.CODIGO,
            nombre="Procesos publicados (OCDS)",
            endpoint_base=ocds.SEARCH_URL,
            adaptador=ocds.FuenteOcdsGeneral(
                [str(fila["texto"]) for fila in pendientes],
                paginas_por_ciclo=paginas_generales,
            ),
            mapeos_por_defecto=ocds_mapeos.MAPEOS_POR_DEFECTO,
            desde=desde,
            terminos_buscados=[fila["termino_id"] for fila in pendientes],
            # **No** se declara listado completo, y es importante: el rabo es una parte del listado,
            # no la foto entera del año. Declararlo cerraría como «ya no vigente» todo lo que no
            # apareció en las últimas páginas, que es casi todo.
        )
    )
    return definiciones


async def ejecutar_todos(
    repositorio: RepositorioIngesta,
    cache: Cache,
    *,
    intervalo_min: int,
    ventana_solape_ciclos: int,
    presupuesto_peticiones: int,
    dias_ventana_inicial: int = DIAS_VENTANA_INICIAL,
    limite_terminos: int = LIMITE_TERMINOS_POR_CICLO,
    fichas_items: int = LIMITE_FICHAS_POR_CICLO,
    paginas_generales: int = ocds.PAGINAS_GENERALES_POR_CICLO,
) -> list[ResultadoCiclo]:
    """Ejecuta un ciclo de todas las fuentes y devuelve sus resúmenes.

    Después de las fuentes se leen las fichas pendientes de CPC, con el **mismo adaptador** que
    acaba de traer el listado: es lo que hace que las dos cosas compartan un único control de tasa y
    una única cuota. Crear aquí un segundo cliente HTTP duplicaría la tasa de peticiones contra una
    fuente que ya responde 429 con facilidad.

    La lectura de fichas va **detrás** del ciclo y no dentro de él: el listado es el dato, la ficha
    es el enriquecimiento, y si algo tiene que quedar a medias que sea lo segundo.
    """
    resultados: list[ResultadoCiclo] = []

    definiciones = await fuentes_por_defecto(
        repositorio,
        intervalo_min=intervalo_min,
        ventana_solape_ciclos=ventana_solape_ciclos,
        dias_ventana_inicial=dias_ventana_inicial,
        limite_terminos=limite_terminos,
        paginas_generales=paginas_generales,
    )
    for definicion in definiciones:
        async with bloqueo_de_ingesta(definicion.codigo) as conexion:
            if conexion is None:
                registro.info("Otra réplica ya está ingestando %s: se omite.", definicion.codigo)
                continue

            resultado = await ejecutar_ciclo(
                definicion,
                repositorio,
                cache,
                intervalo_min=intervalo_min,
                ventana_solape_ciclos=ventana_solape_ciclos,
                presupuesto_peticiones=presupuesto_peticiones,
                dias_ventana_inicial=dias_ventana_inicial,
            )
            resultados.append(resultado)
            registro.info(
                "%s: %s · %s nuevos, %s actualizados, %s iguales, %s sin mapear (%s pet.)",
                resultado.fuente,
                resultado.estado,
                resultado.nuevos,
                resultado.actualizados,
                resultado.iguales,
                resultado.sin_mapear,
                resultado.peticiones,
            )
            for aviso in resultado.avisos:
                registro.warning("%s: %s", resultado.fuente, aviso)

    await _leer_fichas(repositorio, definiciones, fichas=fichas_items, cache=cache)
    return resultados


async def ejecutar_vigilancia(
    repositorio: RepositorioIngesta,
    cache: Cache,
    *,
    intervalo_min: int,
    ventana_solape_ciclos: int,
    presupuesto_peticiones: int,
    dias_ventana_inicial: int = DIAS_VENTANA_INICIAL,
) -> list[ResultadoCiclo]:
    """Vuelta corta: relee **solo el listado** de necesidades, sin cola de términos ni fichas.

    Existe por un hueco medido, no por precaución. La fuente no publica histórico: devuelve lo que
    está vigente en el momento de pedirlo. Una necesidad que entra y sale entre dos ciclos completos
    no se puede recuperar después, y la deuda se paga en datos que no vuelven —con el worker parado
    49 horas se perdieron 19 necesidades del Excel de interés del cliente, 14 de ellas con el plazo
    de proformas vencido dentro del hueco—. Esta vuelta estrecha ese agujero de un cuarto de hora a
    dos minutos y medio.

    Para repetirse tan a menudo deja fuera todo lo que cuesta, y cada ausencia es una decisión:

    - **No consulta la cola de términos** (`incluir_ocds=False`). Decidir qué busca OCDS es trabajo
      que solo sirve si OCDS va a correr, y consultar la cola cada dos minutos y medio sería leer y
      escribir la base para decidir algo que nadie va a usar.
    - **No lee fichas.** Cada ficha es una petición a un origen que responde 429 con facilidad, y la
      ficha no deja de existir: se lee en la vuelta larga, que es donde está el presupuesto.
    - **No invalida la caché** (`invalidar_cache=False`). Subir la generación a esta cadencia
      dejaría inservible todo lo cacheado cada dos minutos y medio, y el catálogo de desplegables
      —que recorre el histórico entero— se pagaría detrás de cada vuelta. El panel no pierde
      frescura por esto: una página de resultados ya vive 900 s de todos modos.
    El bloqueo se toma igual que en la vuelta larga, y no es un detalle heredado: con dos réplicas
    las dos vigilan, y lo que no puede pasar es que las dos pidan el mismo listado a la vez y
    escriban las mismas filas dos veces.
    """
    resultados: list[ResultadoCiclo] = []

    definiciones = await fuentes_por_defecto(
        repositorio,
        intervalo_min=intervalo_min,
        ventana_solape_ciclos=ventana_solape_ciclos,
        dias_ventana_inicial=dias_ventana_inicial,
        incluir_ocds=False,
    )
    for definicion in definiciones:
        async with bloqueo_de_ingesta(definicion.codigo) as conexion:
            if conexion is None:
                registro.info("Otra réplica ya está ingestando %s: se omite.", definicion.codigo)
                continue

            resultado = await ejecutar_ciclo(
                definicion,
                repositorio,
                cache,
                intervalo_min=intervalo_min,
                ventana_solape_ciclos=ventana_solape_ciclos,
                presupuesto_peticiones=presupuesto_peticiones,
                dias_ventana_inicial=dias_ventana_inicial,
                invalidar_cache=False,
            )
            resultados.append(resultado)
            registro.info(
                "Vigilancia %s: %s · %s nuevos, %s actualizados, %s iguales, %s cerrados",
                resultado.fuente,
                resultado.estado,
                resultado.nuevos,
                resultado.actualizados,
                resultado.iguales,
                resultado.cerrados,
            )

    return resultados


async def _leer_fichas(
    repositorio: RepositorioIngesta,
    definiciones: list[DefinicionFuente],
    *,
    fichas: int,
    cache: Cache,
) -> None:
    """Lee, por tandas, las fichas de las que aún no se tienen los ítems con CPC.

    Un fallo aquí **no puede tumbar el ciclo**. Para cuando esto se ejecuta, el listado ya está
    guardado y la sincronización cerrada: perder la lectura de fichas cuesta que 300 necesidades
    sigan buscándose solo por texto libre hasta la vuelta siguiente, mientras que dejar escapar la
    excepción haría que el worker diera el ciclo por fallido después de haberlo completado.

    Y cuando **sí** se escribe algo, sube la generación. No es un detalle: el CPC entra después de
    que cada fuente haya invalidado lo suyo, así que sin esta subida las páginas que el panel tiene
    en caché seguirían saliendo **sin columna CPC** hasta caducar por tiempo —hasta quince
    minutos—. El síntoma sería el peor de todos: la necesidad está, su clasificación no, y parece
    que la ficha no se leyó. Solo se sube si hay ítems escritos: marcar una ficha como «leída y sin
    detalle» no cambia nada de lo que se puede buscar.
    """
    if fichas <= 0:
        return
    con_cpc = 0
    try:
        async with bloqueo_de_ingesta(BLOQUEO_DETALLE) as conexion:
            if conexion is None:
                registro.info("Otra réplica ya está leyendo fichas: se omite.")
                return
            resultado = await recoger_items(
                repositorio,
                definiciones,
                presupuesto_peticiones=fichas,
                limite=fichas,
            )
            con_cpc = resultado.con_items
    except Exception:  # noqa: BLE001 - el enriquecimiento no puede tumbar el ciclo
        registro.exception("Fallo leyendo las fichas de CPC; el ciclo ya está guardado.")
        return

    if con_cpc:
        await subir_generacion(cache)
