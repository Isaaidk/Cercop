"""Mantenimiento periódico del histórico.

Dos trabajos con una sola vuelta, porque los dos miran la misma columna y los dos son baratos:

1. **Avisar de lo que venció.** El estado de una ínfima se deduce de su fecha límite; lo que no se
   deduce solo es **cuándo cambió**. Si un plazo cruzó desde la vuelta anterior, las páginas y las
   estadísticas que están en la caché se calcularon cuando esa ínfima todavía admitía proforma, y
   seguirían contándola como abierta: no dan un error, dan un número viejo. Por eso se sube la
   generación —lo que las invalida en bloque— y no se reescribe ninguna fila.
2. **Retirar lo que ya no es una oportunidad.** Una ínfima cuyo plazo venció hace días no se va a
   consultar, y su fila pesa unos dos kilobytes entre `datos` y `crudo`.

Por qué no hay un `worker` que «actualice el estado» de las filas
----------------------------------------------------------------
Porque no hay nada que actualizar. Un estado guardado («en plazo» / «vencida») es una copia de una
cuenta que depende del reloj: se queda obsoleta en cuanto el `worker` se para un rato, y entonces la
base afirma algo falso sobre filas de las que nadie se acuerda. La fecha y la comparación no se
estropean. Lo que sí hacía falta de verdad es la segunda mitad —que la caché se entere— y eso es lo
que hace esta vuelta.

Cuánto se retira en cada pasada
------------------------------
`maximo_por_vuelta` acota el trabajo, no la política. Una pasada que borrara las cinco mil filas
vencidas de golpe mantendría bloqueadas sus páginas el tiempo suficiente para que el resto del
sistema lo notara —y compite con la ingesta por el mismo presupuesto de base—. Con el tope, la
retención se pone al día en unas cuantas vueltas y cada una dura milisegundos. **Cero desactiva la
retención**: se sigue contando lo que venció, que es información, y no se borra nada.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from contratacion.aplicacion.generaciones import subir_generacion
from contratacion.aplicacion.puertos.cache import Cache
from contratacion.aplicacion.puertos.mantenimiento import (
    RepositorioMantenimiento,
    ResultadoPurga,
)

registro = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ResultadoMantenimiento:
    """Lo que hizo una vuelta de mantenimiento."""

    #: Plazos de proformas que cruzaron desde la vuelta anterior.
    vencimientos: int
    #: Registros vencidos hace más de lo que dura la retención, contados todos.
    vencidas: int
    #: Los que se retiraron en esta vuelta (como mucho, el tope).
    registros_purgados: int
    #: Versiones del histórico que se fueron con ellos.
    historial_purgado: int
    #: `True` si no se escribió nada: solo se contó.
    simulado: bool

    def resumen(self) -> str:
        """Una línea para el registro del `worker`."""
        verbo = "por retirar" if self.simulado else "retiradas"
        return (
            f"vencimientos={self.vencimientos} · vencidas={self.vencidas} "
            f"({verbo}={self.registros_purgados}, historial={self.historial_purgado})"
        )


async def mantener_registros(
    repositorio: RepositorioMantenimiento,
    cache: Cache,
    *,
    intervalo_seg: int,
    dias_retencion: int,
    maximo_por_vuelta: int,
    simular: bool = False,
    ahora: datetime | None = None,
) -> ResultadoMantenimiento:
    """Una vuelta de mantenimiento.

    `intervalo_seg` es el hueco entre vueltas y **es** la ventana de los vencimientos: se cuentan
    los plazos que cruzaron dentro de ella, así que cada uno se cuenta una sola vez, en la vuelta
    siguiente. Es lo que permite no guardar en ningún sitio «cuándo fue la última pasada»:
    preguntarle al reloj cuesta lo mismo y no puede desincronizarse.

    Con `dias_retencion` en cero se retira en cuanto vence; con `maximo_por_vuelta` en cero no se
    retira nada y solo se informa de cuánto hay pendiente. Con `simular` tampoco se escribe.

    Un fallo no se propaga como excepción de negocio: quien llama —el `worker`— decide qué hacer.
    Lo que sí está garantizado es que **nada de esto puede dejar el histórico a medias**: la
    retención va en una sola sentencia con las dos tablas dentro.
    """
    momento = ahora or datetime.now(UTC)
    desde = momento - timedelta(seconds=max(intervalo_seg, 1))

    vencimientos = await repositorio.contar_vencimientos(desde=desde, hasta=momento)

    # El corte de la retención: lo que venció antes de este instante ya no es una oportunidad.
    corta_en = momento - timedelta(days=max(dias_retencion, 0))
    vencidas = await repositorio.contar_vencidas(antes_de=corta_en)

    if maximo_por_vuelta > 0:
        purga = await repositorio.purgar_vencidas(corta_en, maximo_por_vuelta, simular=simular)
    else:
        purga = ResultadoPurga(registros=0, historial=0, simulado=simular)

    # La generación solo sube si algo cambió de verdad. Subirla en cada vuelta dejaría inservible
    # todo lo cacheado cada cinco minutos y el catálogo de desplegables —que recorre el histórico
    # entero— se pagaría detrás de cada una. Con la simulación no se escribe, así que lo único que
    # puede justificar la subida son los vencimientos.
    if vencimientos or (purga.registros and not simular):
        await subir_generacion(cache)

    return ResultadoMantenimiento(
        vencimientos=vencimientos,
        vencidas=vencidas,
        registros_purgados=purga.registros,
        historial_purgado=purga.historial,
        simulado=simular,
    )
