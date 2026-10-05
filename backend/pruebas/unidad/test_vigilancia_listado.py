"""Pruebas de la vigilancia del listado.

Esta pieza existe por un hueco medido: la fuente no publica histórico, solo lo vigente, y una
necesidad puede vivir un día entero. Con el worker parado 49 horas se perdieron 19 necesidades de
interés y ninguna se pudo recuperar. La vigilancia estrecha ese hueco de un cuarto de hora a dos
minutos y medio.

Aquí se comprueban las tres decisiones que la sostienen, y las tres se pueden romper sin que nada
falle a la vista:

- la vuelta corta **no** consulta la cola de términos ni lee fichas: si lo hiciera gastaría lo mismo
  que el ciclo completo y no podría repetirse cada dos minutos y medio;
- **no** invalida la caché: a esa cadencia dejaría inservible cada vuelta el catálogo de
  desplegables, que es el recorrido del histórico entero;
- el ciclo completo **no** se queda sin correr por una racha de vueltas cortas.

Las dos primeras son ausencias, y una ausencia no se nota hasta que alguien la introduce. Por eso
las pruebas no comprueban solo que la vuelta corta hace lo suyo, sino que **no** hace lo demás.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import pytest

from contratacion.aplicacion.casos_uso.ejecutar_ingesta import DefinicionFuente, ResultadoCiclo
from contratacion.aplicacion.casos_uso.operar_ingesta import PASO_COMPROBACION_SEG, SolicitudCiclo
from contratacion.aplicacion.casos_uso.recoger_items import ResultadoDetalle
from contratacion.aplicacion.puertos.cache import Cache
from contratacion.infraestructura.adaptadores.salida.bd.ingesta import RepositorioIngesta
from contratacion.tareas import planificador, worker

AHORA = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
_UUID_NUEVO = uuid4()
_UUID_VIEJO = uuid4()


class CacheEspia:
    """Caché que solo anota los incrementos de generación.

    Implementa el protocolo completo aunque aquí no se use todo: un doble al que le falten métodos
    no falla al escribirlo, falla el día que alguien usa el que falta.
    """

    def __init__(self) -> None:
        self.incrementos: list[str] = []

    @property
    def habilitada(self) -> bool:
        return True

    async def obtener(self, clave: str) -> str | None:
        return None

    async def obtener_renovando(self, clave: str, ttl_seg: int) -> str | None:
        return None

    async def guardar(self, clave: str, valor: str, ttl_seg: int) -> None:
        return None

    async def eliminar(self, clave: str) -> None:
        return None

    async def incrementar(self, clave: str) -> int:
        self.incrementos.append(clave)
        return len(self.incrementos)

    async def ping(self) -> bool:
        return True

    async def cerrar(self) -> None:
        return None


class RepositorioEspia:
    """Doble del repositorio. No toca ninguna base: anota lo que le piden.

    La cola de términos es justo lo que la vuelta corta **no** debe consultar, así que lo que se
    comprueba es que su lista de peticiones se queda vacía.
    """

    def __init__(self, cola: list[dict[str, Any]] | None = None) -> None:
        self.limites_pedidos: list[int] = []
        self._cola = cola or []

    async def obtener_pendientes_de_ingesta(self, limite: int) -> list[dict[str, Any]]:
        self.limites_pedidos.append(limite)
        return self._cola


@asynccontextmanager
async def _bloqueo_libre(codigo: str) -> AsyncIterator[object]:
    """Bloqueo que siempre se concede: aquí se prueba la cadencia, no la exclusión mutua."""
    yield object()


def _resultado(codigo: str) -> ResultadoCiclo:
    return ResultadoCiclo(
        fuente=codigo,
        estado="ok",
        nuevos=0,
        actualizados=0,
        iguales=0,
        sin_mapear=0,
        peticiones=1,
        avisos=(),
    )


# --------------------------------------------------------------------------- #
# El planificador: la vuelta corta y lo que deja de hacer
# --------------------------------------------------------------------------- #


async def test_la_vuelta_corta_no_consulta_la_cola_de_terminos() -> None:
    """NCO se trae entero con una petición; pedir términos sería gastar cuota para nada."""
    espia = RepositorioEspia()

    definiciones = await planificador.fuentes_por_defecto(
        cast(RepositorioIngesta, espia),
        intervalo_min=15,
        ventana_solape_ciclos=2,
        incluir_ocds=False,
    )

    assert [definicion.codigo for definicion in definiciones] == ["NCO"]
    assert espia.limites_pedidos == []


async def test_el_ciclo_completo_si_consulta_la_cola() -> None:
    """La prueba anterior solo vale si la consulta existe de verdad en el otro camino.

    Y el ciclo completo incluye OCDS **siempre**, aunque no haya términos: el listado general se lee
    por el rabo y no depende de ninguna palabra clave. La cola se sigue consultando, pero para otra
    cosa: el rescate de una palabra que nunca se ha buscado.
    """
    espia = RepositorioEspia()

    definiciones = await planificador.fuentes_por_defecto(
        cast(RepositorioIngesta, espia),
        intervalo_min=15,
        ventana_solape_ciclos=2,
        incluir_ocds=True,
        limite_terminos=7,
    )

    assert [definicion.codigo for definicion in definiciones] == ["NCO", "OCDS"]
    assert espia.limites_pedidos == [7]


async def test_solo_se_rescatan_los_terminos_que_nunca_se_han_buscado() -> None:
    """Es lo que convierte el rescate en algo que pasa una vez y no en el ciclo de siempre.

    Un término ya buscado que volviera a la cola costaría sus dos o tres peticiones de cada ciclo
    para siempre —con veinte términos, las ~4.300 al día que el listado general viene a evitar—, y
    no aportaría nada: lo que se publique de aquí en adelante entra por el rabo. El rescate solo
    tiene sentido para lo publicado **antes** de que esta fuente existiera, y eso solo le falta a
    una palabra clave que se acaba de añadir.
    """
    espia = RepositorioEspia(
        [
            {"termino_id": _UUID_NUEVO, "texto": "nueva", "ultima_ingesta_en": None},
            {"termino_id": _UUID_VIEJO, "texto": "ya buscada", "ultima_ingesta_en": AHORA},
        ]
    )

    definiciones = await planificador.fuentes_por_defecto(
        cast(RepositorioIngesta, espia),
        intervalo_min=15,
        ventana_solape_ciclos=2,
    )
    ocds = next(definicion for definicion in definiciones if definicion.codigo == "OCDS")

    assert ocds.terminos_buscados == [_UUID_NUEVO]
    assert cast(Any, ocds.adaptador)._terminos == ["nueva"]


async def test_sin_terminos_nuevos_el_rabo_usa_la_marca_de_agua() -> None:
    """Y esto es lo que hace que un ciclo normal cueste dos o tres peticiones y no cuarenta.

    Cuando **no** hay nada que rescatar no se pasa ventana: que la calcule el caso de uso a partir
    de la marca de agua, que es cuántas páginas hay que leer para cubrir el hueco real. Pasarle los
    noventa días de una palabra clave nueva le haría leer el tope entero del ciclo.
    """
    espia = RepositorioEspia(
        [{"termino_id": _UUID_VIEJO, "texto": "ya buscada", "ultima_ingesta_en": AHORA}]
    )

    definiciones = await planificador.fuentes_por_defecto(
        cast(RepositorioIngesta, espia),
        intervalo_min=15,
        ventana_solape_ciclos=2,
    )
    ocds = next(definicion for definicion in definiciones if definicion.codigo == "OCDS")

    assert ocds.desde is None
    assert ocds.terminos_buscados == []


async def test_la_vuelta_corta_no_invalida_la_cache_ni_lee_fichas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lo que se le pasa a cada ciclo, que es donde está la decisión.

    Sin esto, la vigilancia subiría la generación cada dos minutos y medio: todas las claves
    cacheadas quedarían inservibles a esa cadencia, y el catálogo de desplegables —el recorrido del
    histórico entero— se pagaría entero detrás de cada vuelta.
    """
    llamadas: list[dict[str, Any]] = []

    async def ciclo_falso(
        definicion: DefinicionFuente,
        repositorio: RepositorioIngesta,
        cache: Cache,
        **kwargs: Any,
    ) -> ResultadoCiclo:
        llamadas.append({"fuente": definicion.codigo, **kwargs})
        return _resultado(definicion.codigo)

    async def fichas_prohibidas(*_: Any, **__: Any) -> None:
        raise AssertionError("la vuelta corta no debe leer fichas de CPC")

    monkeypatch.setattr(planificador, "bloqueo_de_ingesta", _bloqueo_libre)
    monkeypatch.setattr(planificador, "ejecutar_ciclo", ciclo_falso)
    monkeypatch.setattr(planificador, "_leer_fichas", fichas_prohibidas)

    espia = RepositorioEspia()
    resultados = await planificador.ejecutar_vigilancia(
        cast(RepositorioIngesta, espia),
        CacheEspia(),
        intervalo_min=15,
        ventana_solape_ciclos=2,
        presupuesto_peticiones=90,
    )

    assert [resultado.fuente for resultado in resultados] == ["NCO"]
    assert espia.limites_pedidos == []
    assert len(llamadas) == 1
    assert llamadas[0]["fuente"] == "NCO"
    assert llamadas[0]["invalidar_cache"] is False
    assert llamadas[0]["presupuesto_peticiones"] == 90


async def test_la_vuelta_corta_se_salta_la_fuente_si_otra_replica_la_tiene(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El bloqueo no es un detalle de la vuelta larga: con dos réplicas, las dos vigilan."""
    llamadas: list[str] = []

    @asynccontextmanager
    async def bloqueo_ocupado(codigo: str) -> AsyncIterator[None]:
        yield None

    async def ciclo_prohibido(*_: Any, **__: Any) -> ResultadoCiclo:
        llamadas.append("ciclo")
        raise AssertionError("no se debe ingestar sin el bloqueo")

    monkeypatch.setattr(planificador, "bloqueo_de_ingesta", bloqueo_ocupado)
    monkeypatch.setattr(planificador, "ejecutar_ciclo", ciclo_prohibido)

    resultados = await planificador.ejecutar_vigilancia(
        cast(RepositorioIngesta, RepositorioEspia()),
        CacheEspia(),
        intervalo_min=15,
        ventana_solape_ciclos=2,
        presupuesto_peticiones=90,
    )

    assert resultados == []
    assert llamadas == []


# --------------------------------------------------------------------------- #
# El worker: las dos cadencias
# --------------------------------------------------------------------------- #


class _FinDelBucle(Exception):
    """Corta el bucle del worker desde el reloj falso, que si no es infinito."""


class RelojFalso:
    """Reloj y sueño falsos. El worker espera de verdad; la prueba no.

    Sustituye a `time` **y** a `asyncio` dentro del worker, que son los dos módulos que usa el
    bucle. Se hace así, y no parcheando `asyncio.sleep` a secas, porque el módulo `asyncio` es el
    mismo para todo el proceso: tocarlo dejaría sin sueño al propio motor de pruebas.

    Se para por **tiempo acumulado** y no por número de sueños, que es lo que importa: el bucle
    duerme en tramos cortos para poder atender un ciclo pedido a mano, así que contar sueños mediría
    el tamaño del tramo —un detalle de implementación— en vez de la cadencia, que es lo que estas
    pruebas vienen a fijar. Con el reloj por tiempo, un cambio en el tamaño del tramo no las toca.

    El umbral se pone **después** del último suceso que se quiere ver: el reloj corta al terminar el
    sueño que lo alcanza, así que parar en 900 dejaría el ciclo de los 900 s sin ejecutar.
    """

    def __init__(self, *, parar_en_seg: float) -> None:
        self.ahora = 0.0
        self.dormidas = 0
        self.parar_en_seg = parar_en_seg

    def monotonic(self) -> float:
        return self.ahora

    async def sleep(self, segundos: float) -> None:
        self.dormidas += 1
        self.ahora += segundos
        if self.ahora >= self.parar_en_seg:
            raise _FinDelBucle


@dataclass(frozen=True)
class AjustesDePrueba:
    """Los ajustes que el worker lee de verdad, con los valores por defecto del proyecto."""

    intervalo_ingesta_min: int = 15
    intervalo_vigilancia_seg: int = 150
    ventana_solape_ciclos: int = 2
    presupuesto_peticiones_ciclo: int = 90


async def _nadie_pide_nada() -> None:
    """Sin petición pendiente, que es el caso normal: el worker trabaja a su cadencia."""
    return None


async def test_el_ciclo_completo_no_se_queda_sin_correr(monkeypatch: pytest.MonkeyPatch) -> None:
    """Vueltas cortas cada 150 s, y el ciclo completo a los 900 s, no cuando se pueda.

    Es la condición que hace útil la vigilancia: estrechar el hueco del listado no puede convertirse
    en que las búsquedas por palabra clave y las fichas dejen de correr.
    """
    reloj = RelojFalso(parar_en_seg=1051.0)
    vueltas: list[tuple[str, float]] = []

    async def ciclo() -> int:
        vueltas.append(("ingesta", reloj.ahora))
        return 0

    async def vigila() -> None:
        vueltas.append(("vigilancia", reloj.ahora))

    monkeypatch.setattr(worker, "time", reloj)
    monkeypatch.setattr(worker, "asyncio", reloj)
    monkeypatch.setattr(worker, "ejecutar_un_ciclo", ciclo)
    monkeypatch.setattr(worker, "vigilar_listado", vigila)
    monkeypatch.setattr(worker, "_solicitud_de_ciclo", _nadie_pide_nada)
    monkeypatch.setattr(worker, "obtener_ajustes", lambda: AjustesDePrueba())

    with pytest.raises(_FinDelBucle):
        await worker.bucle()

    assert [momento for nombre, momento in vueltas if nombre == "ingesta"] == [0.0, 900.0]
    assert [momento for nombre, momento in vueltas if nombre == "vigilancia"] == [
        150.0,
        300.0,
        450.0,
        600.0,
        750.0,
        1050.0,
    ]


async def test_una_vuelta_que_falla_no_mata_el_bucle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Y además devuelve la vez al ciclo completo, en lugar de reintentarlo sin parar.

    Las dos mitades se comprueban juntas porque el mismo descuido rompe las dos: si la hora del
    ciclo completo solo avanzara al salir bien, un ciclo que falla se reintentaría en **cada**
    vuelta corta —cada dos minutos y medio, con las búsquedas por palabra clave y las fichas dentro,
    que es lo que la fuente castiga con 429— y la vigilancia no llegaría a correr nunca.
    """
    reloj = RelojFalso(parar_en_seg=451.0)
    cortas: list[str] = []

    async def ciclo_roto() -> int:
        raise RuntimeError("la fuente no responde")

    async def vigila() -> None:
        cortas.append("vigilancia")

    monkeypatch.setattr(worker, "time", reloj)
    monkeypatch.setattr(worker, "asyncio", reloj)
    monkeypatch.setattr(worker, "ejecutar_un_ciclo", ciclo_roto)
    monkeypatch.setattr(worker, "vigilar_listado", vigila)
    monkeypatch.setattr(worker, "_solicitud_de_ciclo", _nadie_pide_nada)
    monkeypatch.setattr(worker, "obtener_ajustes", lambda: AjustesDePrueba())

    with pytest.raises(_FinDelBucle):
        await worker.bucle()

    assert cortas == ["vigilancia"] * 3


async def test_un_ciclo_pedido_desde_el_panel_se_adelanta(monkeypatch: pytest.MonkeyPatch) -> None:
    """El botón del panel no espera a la cadencia: espera a lo que tarde el worker en mirar.

    Es lo que hace el botón utilizable. Si el bucle durmiera hasta la hora que toca —hasta quince
    minutos— quien lo pulsa no vería nada, y volvería a pulsarlo, y creería que está roto. El
    retardo real es el tramo de comprobación, y por eso se fija aquí: lo que se prueba es que el
    ciclo arranca en la **primera** vuelta siguiente a la petición, no en la siguiente cadencia.

    Y también que se atiende una sola vez: si el bucle releyera la petición en cada tramo, un botón
    sería un ciclo cada cinco segundos.
    """
    reloj = RelojFalso(parar_en_seg=260.0)
    pedida_en = 200.0
    pendiente: list[SolicitudCiclo] = [
        SolicitudCiclo(solicitado_por="alguien", solicitado_en=AHORA)
    ]
    ciclos: list[float] = []
    vistas: list[float] = []

    async def solicitud_de_ciclo() -> SolicitudCiclo | None:
        vistas.append(reloj.ahora)
        if reloj.ahora >= pedida_en and pendiente:
            return pendiente.pop()
        return None

    async def ciclo() -> int:
        ciclos.append(reloj.ahora)
        return 0

    async def vigila() -> None:
        return None

    monkeypatch.setattr(worker, "time", reloj)
    monkeypatch.setattr(worker, "asyncio", reloj)
    monkeypatch.setattr(worker, "ejecutar_un_ciclo", ciclo)
    monkeypatch.setattr(worker, "vigilar_listado", vigila)
    monkeypatch.setattr(worker, "_solicitud_de_ciclo", solicitud_de_ciclo)
    monkeypatch.setattr(worker, "obtener_ajustes", lambda: AjustesDePrueba())

    with pytest.raises(_FinDelBucle):
        await worker.bucle()

    assert ciclos == [0.0, pedida_en]
    # Se mira en cada tramo, y el tramo es corto a propósito: es el retardo del botón.
    assert PASO_COMPROBACION_SEG <= 15.0
    assert vistas[:3] == [0.0, PASO_COMPROBACION_SEG, 2 * PASO_COMPROBACION_SEG]
    # Y después del ciclo pedido ya no se vuelve a ejecutar hasta la hora reprogramada.
    assert ciclos.count(pedida_en) == 1


async def test_si_el_worker_no_puede_preguntar_por_la_peticion_sigue_el_bucle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un caché caído no puede llevarse por delante el worker.

    Preguntar por una petición es lo accesorio; ingerir es el activo. Si el `GET` falla, el bucle
    tiene que seguir como si no hubiera nada pedido —y avisar en el registro—, no morir.
    """

    class CacheRota:
        habilitada = True

        async def obtener(self, clave: str) -> str | None:
            raise RuntimeError("el almacén no responde")

    monkeypatch.setattr(worker, "obtener_cache", lambda: CacheRota())

    assert await worker._solicitud_de_ciclo() is None


async def test_la_vuelta_corta_no_precalienta_los_catalogos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Precalentar recorre el histórico: a esta cadencia trabajaría para nadie cada dos minutos."""
    llamadas: list[dict[str, Any]] = []

    async def vigilancias(
        repositorio: RepositorioIngesta, cache: Cache, **kwargs: Any
    ) -> list[ResultadoCiclo]:
        llamadas.append(kwargs)
        return []

    async def catalogo_prohibido(*_: Any, **__: Any) -> dict[str, Any]:
        raise AssertionError("la vuelta corta no debe precalentar los catálogos")

    async def sin_efecto() -> None:
        return None

    monkeypatch.setattr(worker, "ejecutar_vigilancia", vigilancias)
    monkeypatch.setattr(worker, "obtener_catalogos", catalogo_prohibido)
    monkeypatch.setattr(worker, "obtener_ajustes", lambda: AjustesDePrueba())
    monkeypatch.setattr(worker, "obtener_motor", lambda: object())
    monkeypatch.setattr(worker, "RepositorioIngesta", lambda *_: object())
    monkeypatch.setattr(worker, "obtener_cache", CacheEspia)
    monkeypatch.setattr(worker, "cerrar_cache", sin_efecto)
    monkeypatch.setattr(worker, "cerrar_bd", sin_efecto)

    await worker.vigilar_listado()

    # Los mismos ajustes que el ciclo completo, a propósito: `asegurar_fuente` guarda el intervalo
    # y el presupuesto en la fila de la fuente, y dos valores distintos la harían cambiar en cada
    # vuelta.
    assert len(llamadas) == 1
    assert llamadas[0]["intervalo_min"] == AjustesDePrueba.intervalo_ingesta_min


# --------------------------------------------------------------------------- #
# Las fichas de CPC: escriben después de invalidar, así que tienen que invalidar
# --------------------------------------------------------------------------- #


async def test_escribir_cpc_sube_la_generacion(monkeypatch: pytest.MonkeyPatch) -> None:
    """El CPC entra **después** de que cada fuente invalide lo suyo.

    Sin esta subida, las páginas que el panel tiene cacheadas seguirían saliendo sin columna CPC
    hasta caducar por tiempo —hasta quince minutos—, y el síntoma es el peor de todos: la necesidad
    está, su clasificación no, y parece que la ficha no se leyó.
    """
    subidas: list[str] = []

    async def fichas_leidas(*_: Any, **__: Any) -> ResultadoDetalle:
        return ResultadoDetalle(revisados=3, con_items=2)

    async def subir_falsa(cache: Cache, fuente: str = "global") -> None:
        subidas.append(fuente)

    monkeypatch.setattr(planificador, "bloqueo_de_ingesta", _bloqueo_libre)
    monkeypatch.setattr(planificador, "recoger_items", fichas_leidas)
    monkeypatch.setattr(planificador, "subir_generacion", subir_falsa)

    await planificador._leer_fichas(
        cast(RepositorioIngesta, RepositorioEspia()), [], fichas=10, cache=CacheEspia()
    )

    assert len(subidas) == 1, "escribir ítems de CPC tiene que invalidar lo cacheado"


async def test_una_ficha_leida_sin_items_no_sube_la_generacion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Marcar una ficha como «leída y sin detalle» no cambia nada de lo que se puede buscar.

    Es un caso real —hay necesidades publicadas sin tabla de CPC— y subir la generación por él
    invalidaría todo el caché cada ciclo para no enseñar nada distinto.
    """
    subidas: list[str] = []

    async def fichas_sin_items(*_: Any, **__: Any) -> ResultadoDetalle:
        return ResultadoDetalle(revisados=4, con_items=0, sin_items=4)

    async def subir_falsa(cache: Cache, fuente: str = "global") -> None:
        subidas.append(fuente)

    monkeypatch.setattr(planificador, "bloqueo_de_ingesta", _bloqueo_libre)
    monkeypatch.setattr(planificador, "recoger_items", fichas_sin_items)
    monkeypatch.setattr(planificador, "subir_generacion", subir_falsa)

    await planificador._leer_fichas(
        cast(RepositorioIngesta, RepositorioEspia()), [], fichas=10, cache=CacheEspia()
    )

    assert subidas == []


async def test_un_fallo_leyendo_fichas_no_sube_la_generacion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un fallo a medias no puede anunciar cambios que no se sabe si ocurrieron."""
    subidas: list[str] = []

    async def fichas_rotas(*_: Any, **__: Any) -> ResultadoDetalle:
        raise RuntimeError("la fuente se cayó a mitad de la tanda")

    async def subir_falsa(cache: Cache, fuente: str = "global") -> None:
        subidas.append(fuente)

    monkeypatch.setattr(planificador, "bloqueo_de_ingesta", _bloqueo_libre)
    monkeypatch.setattr(planificador, "recoger_items", fichas_rotas)
    monkeypatch.setattr(planificador, "subir_generacion", subir_falsa)

    await planificador._leer_fichas(
        cast(RepositorioIngesta, RepositorioEspia()), [], fichas=10, cache=CacheEspia()
    )

    assert subidas == []
