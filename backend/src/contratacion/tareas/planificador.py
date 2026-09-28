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


async def fuentes_por_defecto(
    repositorio: RepositorioIngesta,
    *,
    intervalo_min: int,
    ventana_solape_ciclos: int,
    dias_ventana_inicial: int = DIAS_VENTANA_INICIAL,
    limite_terminos: int = LIMITE_TERMINOS_POR_CICLO,
) -> list[DefinicionFuente]:
    """Fuentes que se ingestan en cada ciclo.

    NCO se ingesta siempre y completa: una sola petición trae todo el listado, así que no hay nada
    que priorizar y ninguna suscripción puede quedar sin cubrir en él. OCDS se consulta por palabra
    clave y por año, así que solo tiene sentido si hay términos, y lo que se busca son los más
    urgentes de la cola.
    """
    definiciones = [
        DefinicionFuente(
            codigo=nco.CODIGO,
            nombre="Necesidades de Contratación (NCO)",
            endpoint_base=nco.ENDPOINT,
            adaptador=nco.FuenteNco(),
            mapeos_por_defecto=nco_mapeos.MAPEOS_POR_DEFECTO,
        )
    ]

    pendientes = await repositorio.obtener_pendientes_de_ingesta(limite_terminos)
    if not pendientes:
        registro.info("Sin términos activos: se omite la fuente OCDS en este ciclo.")
        return definiciones

    momento = datetime.now(UTC)
    desde = ventana_de_cola(
        [fila["ultima_ingesta_en"] for fila in pendientes],
        intervalo_min,
        ventana_solape_ciclos,
        momento,
        dias_ventana_inicial,
    )
    nuevos = sum(1 for fila in pendientes if fila["ultima_ingesta_en"] is None)
    registro.info(
        "OCDS: %s términos en este ciclo (%s nunca buscados), desde %s",
        len(pendientes),
        nuevos,
        desde.isoformat(),
    )

    definiciones.append(
        DefinicionFuente(
            codigo=ocds.CODIGO,
            nombre="Procesos publicados (OCDS)",
            endpoint_base=ocds.SEARCH_URL,
            adaptador=ocds.FuenteOcds([str(fila["texto"]) for fila in pendientes]),
            mapeos_por_defecto=ocds_mapeos.MAPEOS_POR_DEFECTO,
            desde=desde,
            terminos_buscados=[fila["termino_id"] for fila in pendientes],
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
) -> list[ResultadoCiclo]:
    """Ejecuta un ciclo de todas las fuentes y devuelve sus resúmenes."""
    resultados: list[ResultadoCiclo] = []

    definiciones = await fuentes_por_defecto(
        repositorio,
        intervalo_min=intervalo_min,
        ventana_solape_ciclos=ventana_solape_ciclos,
        dias_ventana_inicial=dias_ventana_inicial,
        limite_terminos=limite_terminos,
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

    return resultados
