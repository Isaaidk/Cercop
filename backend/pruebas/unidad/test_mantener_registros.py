"""La vuelta de mantenimiento: vencimientos que invalidan y filas que se retiran.

Lo que se protege aquí no es un cálculo, son dos **decisiones** que se pueden perder sin que nada
falle:

- Que la generación suba **solo** cuando algo cambió. Subirla en cada vuelta de cinco minutos deja
  inservible todo lo cacheado, y el catálogo de desplegables —que recorre el histórico entero— se
  paga detrás de cada subida. Es una optimización que no da error si se pierde: solo va todo más
  lento, y por eso hay que fijarla.
- Que la retención **respete el tope**. Sin él, la primera vuelta intentaría borrar cinco mil filas
  de golpe: mantendría bloqueadas sus páginas y competiría con la ingesta por la misma base.

El doble del repositorio implementa el protocolo completo y **falla si lo llaman para algo que no
toca**, que es lo que convierte el doble en una red y no en un guion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from contratacion.aplicacion.casos_uso.mantener_registros import (
    ResultadoMantenimiento,
    mantener_registros,
)
from contratacion.aplicacion.puertos.cache import Cache
from contratacion.aplicacion.puertos.mantenimiento import ResultadoPurga
from contratacion.infraestructura.adaptadores.salida.cache.nula import CacheNula

AHORA = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


@dataclass
class DobleMantenimiento:
    """Repositorio de mentira que anota con qué se le llamó."""

    vencimientos: int = 0
    vencidas: int = 0
    vencidas_por_vuelta: int = 0
    #: Ventanas y cortes que pidió quien llamó, para poder comprobarlos.
    ventanas: list[tuple[datetime, datetime]] = field(default_factory=list)
    cortes: list[datetime] = field(default_factory=list)
    purgas: list[tuple[datetime, int, bool]] = field(default_factory=list)

    async def contar_vencimientos(self, *, desde: datetime, hasta: datetime) -> int:
        self.ventanas.append((desde, hasta))
        return self.vencimientos

    async def contar_vencidas(self, antes_de: datetime) -> int:
        self.cortes.append(antes_de)
        return self.vencidas

    async def purgar_vencidas(
        self, antes_de: datetime, maximo: int, *, simular: bool = False
    ) -> ResultadoPurga:
        self.purgas.append((antes_de, maximo, simular))
        if simular:
            return ResultadoPurga(registros=self.vencidas, historial=0, simulado=True)
        cuantas = min(maximo, self.vencidas_por_vuelta)
        return ResultadoPurga(registros=cuantas, historial=cuantas * 2)


class CacheContadora(CacheNula):
    """Caché nula que además cuenta los incrementos de la generación."""

    def __init__(self) -> None:
        self.incrementos: list[str] = []

    async def incrementar(self, clave: str) -> int:
        self.incrementos.append(clave)
        return len(self.incrementos)


async def _mantener(
    doble: DobleMantenimiento,
    cache: Cache,
    *,
    intervalo_seg: int = 300,
    dias_retencion: int = 7,
    maximo_por_vuelta: int = 500,
    simular: bool = False,
) -> ResultadoMantenimiento:
    """Una vuelta con los valores por defecto y el reloj fijo, que es lo habitual."""
    return await mantener_registros(
        doble,
        cache,
        intervalo_seg=intervalo_seg,
        dias_retencion=dias_retencion,
        maximo_por_vuelta=maximo_por_vuelta,
        simular=simular,
        ahora=AHORA,
    )


async def test_sin_vencimientos_no_se_toca_la_generacion() -> None:
    """Subirla de más no rompe nada y deja el sistema más lento; por eso se comprueba."""
    doble = DobleMantenimiento()
    cache = CacheContadora()

    resultado = await _mantener(doble, cache)

    assert cache.incrementos == []
    assert resultado.vencimientos == 0
    assert resultado.registros_purgados == 0


async def test_un_vencimiento_sube_la_generacion() -> None:
    """Es la única forma de que la caché deje de contar como abierta una ínfima que ya venció.

    Sin esto el panel no da ningún error: sigue enseñando el número de hace cinco minutos, con la
    ínfima dentro, y nadie puede saber que está mal.
    """
    doble = DobleMantenimiento(vencimientos=3)
    cache = CacheContadora()

    resultado = await _mantener(doble, cache)

    assert len(cache.incrementos) == 1
    assert resultado.vencimientos == 3


async def test_la_ventana_de_los_vencimientos_es_el_intervalo_entre_vueltas() -> None:
    """Cada vencimiento se cuenta **una sola vez**, en la vuelta siguiente.

    Es lo que permite no guardar en ningún sitio cuándo fue la última pasada: si la ventana fuera
    «todo lo vencido hasta ahora», el contador crecería para siempre y no distinguiría una vuelta
    tranquila de una que dejó pasar veinte vencimientos.
    """
    doble = DobleMantenimiento()

    await _mantener(doble, cache=CacheContadora(), intervalo_seg=300)

    desde, hasta = doble.ventanas[0]
    assert hasta == AHORA
    assert desde == AHORA - timedelta(seconds=300)


async def test_el_corte_de_la_retencion_cuenta_los_dias_configurados() -> None:
    doble = DobleMantenimiento()

    await _mantener(doble, cache=CacheContadora(), dias_retencion=7)

    assert doble.cortes == [AHORA - timedelta(days=7)]


async def test_la_purga_respeta_el_tope_por_vuelta() -> None:
    doble = DobleMantenimiento(vencidas=5000, vencidas_por_vuelta=500)

    resultado = await _mantener(doble, cache=CacheContadora(), maximo_por_vuelta=500)

    assert doble.purgas == [(AHORA - timedelta(days=7), 500, False)]
    assert resultado.registros_purgados == 500
    assert resultado.vencidas == 5000


async def test_un_tope_en_cero_desactiva_la_retencion_sin_dejar_de_informar() -> None:
    """Es la forma de conservar el histórico entero: sigue diciendo cuánto hay, y no borra nada."""
    doble = DobleMantenimiento(vencidas=5000, vencidas_por_vuelta=500)
    cache = CacheContadora()

    resultado = await _mantener(doble, cache, maximo_por_vuelta=0)

    assert doble.purgas == []
    assert resultado.vencidas == 5000
    assert resultado.registros_purgados == 0
    assert cache.incrementos == []


async def test_lo_que_se_retira_tambien_invalida_la_cache() -> None:
    """Las filas borradas no pueden seguir saliendo en una página guardada."""
    doble = DobleMantenimiento(vencidas=10, vencidas_por_vuelta=10)
    cache = CacheContadora()

    resultado = await _mantener(doble, cache)

    assert resultado.registros_purgados == 10
    assert resultado.historial_purgado == 20
    assert len(cache.incrementos) == 1


async def test_la_simulacion_cuenta_pero_no_escribe_ni_invalida() -> None:
    """Es lo que permite enseñar el tamaño de la retención **antes** de activarla.

    Si la simulación subiera la generación, se estaría invalidando la caché por un borrado que no ha
    ocurrido: el panel pediría todo otra vez para nada.
    """
    doble = DobleMantenimiento(vencidas=4321, vencidas_por_vuelta=500)
    cache = CacheContadora()

    resultado = await _mantener(doble, cache, simular=True)

    assert doble.purgas == [(AHORA - timedelta(days=7), 500, True)]
    assert resultado.simulado is True
    assert resultado.registros_purgados == 4321
    assert cache.incrementos == []


async def test_el_resumen_dice_lo_que_paso_y_si_fue_simulacion() -> None:
    """Es la línea que queda en el registro del worker; tiene que poder leerse sola."""
    doble = DobleMantenimiento(vencidas=10, vencidas_por_vuelta=8)

    aplicado = await _mantener(doble, CacheContadora())
    simulado = await _mantener(doble, CacheContadora(), simular=True)

    assert "retiradas=8" in aplicado.resumen()
    assert "por retirar=10" in simulado.resumen()


@pytest.mark.parametrize("dias", [0, 1, 30])
async def test_un_plazo_de_retencion_variable_se_respeta(dias: int) -> None:
    doble = DobleMantenimiento()

    await _mantener(doble, cache=CacheContadora(), dias_retencion=dias)

    assert doble.cortes == [AHORA - timedelta(days=dias)]
