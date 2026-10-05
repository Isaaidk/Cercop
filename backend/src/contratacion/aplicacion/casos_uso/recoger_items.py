"""Caso de uso: leer la ficha de cada necesidad y guardar sus ítems con el CPC.

Es la pieza que hace posible **buscar por clasificación** en lugar de por texto libre. El listado de
necesidades no publica el CPC; la ficha sí, y cuesta una petición por necesidad.

Tres decisiones gobiernan este módulo.

**Va aparte del ciclo, por tandas y es reanudable.** El listado medido trae 1.779 necesidades, así
que leerlas todas son 1.779 peticiones contra un origen que responde 429 con facilidad: a 0,6 s por
petición son más de veinte minutos, y eso no cabe en un ciclo. Se hace lo que quepa y lo demás queda
marcado como pendiente para el ciclo siguiente. Como el trabajo es idempotente, una tanda cortada a
la mitad no rompe nada: la siguiente empieza por lo que falta.

**Se pide solo lo que falta.** El criterio es `items_recogidos_en` nulo, y **no** «ítems vacíos»:
hay necesidades publicadas sin detalle, y confundir «no tiene ítems» con «no se ha pedido» las
dejaría reintentándose para siempre —una petición perdida por ciclo y por necesidad, contra una
fuente que limita la tasa—.

**Un fallo no borra lo que ya había.** Si la fuente no responde, el registro se queda pendiente y
conserva sus ítems anteriores. Sustituirlos por nada convertiría un corte de red en una pérdida de
datos: esa necesidad dejaría de encontrarse por CPC hasta que se reintentara, sin que nada lo
delatara.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from contratacion.aplicacion.casos_uso.ejecutar_ingesta import DefinicionFuente
from contratacion.aplicacion.puertos.fuente import FuenteConDetalle
from contratacion.aplicacion.puertos.items import RepositorioItems
from contratacion.dominio.cpc import codigos_de, texto_de_cpc
from contratacion.dominio.ingesta import Presupuesto

registro = logging.getLogger(__name__)

# Tanda predeterminada de fichas por ciclo. Es un tope de **peticiones**, no de tiempo: 300 fichas a
# 0,6 s son unos tres minutos, que caben de sobra entre dos ciclos sin retrasar el siguiente.
LIMITE_FICHAS_POR_CICLO = 300


@dataclass
class ResultadoDetalle:
    """Resumen de una tanda, para el registro del worker y para poder auditarla."""

    revisados: int = 0
    con_items: int = 0
    sin_items: int = 0
    fallidos: int = 0
    peticiones: int = 0
    quedan: int = 0

    def resumen(self) -> str:
        """Una línea, para no llenar el registro de un ciclo con 300 detalles."""
        return (
            f"{self.revisados} fichas leídas ({self.con_items} con ítems, "
            f"{self.sin_items} sin detalle), {self.fallidos} fallidas, "
            f"{self.peticiones} peticiones, {self.quedan} pendientes"
        )


def _adaptadores_con_detalle(
    definiciones: Sequence[DefinicionFuente],
) -> dict[str, FuenteConDetalle]:
    """Adaptadores de las fuentes que publican ficha, por código de fuente.

    Se comprueba la capacidad en lugar de suponerla: la mayoría de las fuentes dan un listado y
    nada más, y preguntarles por una ficha que no existe sería gastar una petición del presupuesto
    —que es de todos— para recibir un 404.
    """
    return {
        definicion.codigo: definicion.adaptador
        for definicion in definiciones
        if isinstance(definicion.adaptador, FuenteConDetalle)
    }


async def recoger_items(
    repositorio: RepositorioItems,
    definiciones: Sequence[DefinicionFuente],
    *,
    presupuesto_peticiones: int,
    limite: int = LIMITE_FICHAS_POR_CICLO,
) -> ResultadoDetalle:
    """Lee las fichas pendientes y guarda sus ítems. Devuelve lo que hizo.

    No lanza excepciones por un fallo de la fuente: es un enriquecimiento, y un corte de red no debe
    tumbar el ciclo que acaba de traer los datos.
    """
    resultado = ResultadoDetalle()
    adaptadores = _adaptadores_con_detalle(definiciones)
    if not adaptadores or limite <= 0:
        return resultado

    pendientes = await repositorio.registros_sin_items(list(adaptadores), limite)
    presupuesto = Presupuesto(limite=presupuesto_peticiones)

    for fila in pendientes:
        if presupuesto.agotado():
            break

        adaptador = adaptadores.get(str(fila["fuente"]))
        if adaptador is None:
            continue

        resultado.revisados += 1
        items = await adaptador.items(fila["enlace"], presupuesto)
        if items is None:
            # No se marca como leída: se reintenta en la siguiente, con los ítems que ya tuviera.
            resultado.fallidos += 1
            continue

        await repositorio.guardar_items(
            fila["id"],
            items=[item.como_diccionario() for item in items],
            cpc_busqueda=texto_de_cpc(items),
            cpc_codigos=codigos_de(items),
        )
        if items:
            resultado.con_items += 1
        else:
            resultado.sin_items += 1

    resultado.peticiones = presupuesto.usadas
    # Lo que falta se **pregunta**, no se deduce: la cuenta anterior era la diferencia de la tanda
    # —«lo que no cabía en el presupuesto de esta vuelta»—, que en el caso normal vale cero y hacía
    # que el registro dijera «0 pendientes» con el relleno a medias. Un aviso que no informa es un
    # aviso que nadie mira, y este es el único que dice cuánto queda por leer.
    resultado.quedan = await repositorio.contar_sin_items(list(adaptadores))
    if resultado.revisados:
        registro.info("Ítems CPC: %s", resultado.resumen())
    return resultado
