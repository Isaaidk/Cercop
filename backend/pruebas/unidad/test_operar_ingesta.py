"""Pruebas de la petición de ciclo y del tablero de la ingesta.

Lo que se comprueba aquí es la costura entre los dos procesos, que es donde está el riesgo: el panel
no ingesta nada, solo deja una petición donde el worker la ve. Las tres cosas que pueden salir mal
son que la petición la pueda dejar quien no debe, que se quede esperando para siempre, y que se
ejecute dos veces porque nadie la borró.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.casos_uso.operar_ingesta import (
    CLAVE_SOLICITUD,
    PASO_COMPROBACION_SEG,
    TTL_SOLICITUD_SEG,
    consumir_solicitud,
    solicitar_ciclo,
    solicitud_pendiente,
    tablero_ingesta,
)
from contratacion.dominio.busqueda import Filtros
from contratacion.dominio.errores import EstadoInvalido, SinPermiso
from contratacion.dominio.serializacion import de_json

NEGOCIO = uuid4()
USUARIO = uuid4()
AHORA = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)

PLATAFORMA = Actor(usuario_id=USUARIO, negocio_id=NEGOCIO, rol="super_admin")
ADMIN = Actor(usuario_id=USUARIO, negocio_id=NEGOCIO, rol="admin_negocio")
CONSULTOR = Actor(usuario_id=USUARIO, negocio_id=NEGOCIO, rol="consultor")


class CacheFalsa:
    """Caché en memoria que además recuerda con qué tiempo de vida se guardó cada clave.

    El tiempo de vida no es un detalle: una petición sin caducidad se ejecutaría el día que el
    worker vuelva, horas después de que nadie se acuerde de haberla pedido.
    """

    def __init__(self, *, habilitada: bool = True) -> None:
        self.guardadas: dict[str, str] = {}
        self.ttl: dict[str, int] = {}
        self.borradas: list[str] = []
        self._habilitada = habilitada

    @property
    def habilitada(self) -> bool:
        return self._habilitada

    async def obtener(self, clave: str) -> str | None:
        return self.guardadas.get(clave)

    async def obtener_renovando(self, clave: str, ttl_seg: int) -> str | None:
        return await self.obtener(clave)

    async def guardar(self, clave: str, valor: str, ttl_seg: int) -> None:
        self.guardadas[clave] = valor
        self.ttl[clave] = ttl_seg

    async def eliminar(self, clave: str) -> None:
        self.guardadas.pop(clave, None)
        self.borradas.append(clave)

    async def incrementar(self, clave: str) -> int:
        resultado = int(self.guardadas.get(clave, "0")) + 1
        self.guardadas[clave] = str(resultado)
        return resultado

    async def ping(self) -> bool:
        return self._habilitada

    async def cerrar(self) -> None:
        return None


class ConsultasFalsas:
    """Repositorio de lectura del tablero, con espía de lo que le pidieron."""

    def __init__(
        self,
        *,
        fuentes: Sequence[Mapping[str, Any]] = (),
        historial: Sequence[Mapping[str, Any]] = (),
    ) -> None:
        self.fuentes = tuple(fuentes)
        self.historial = tuple(historial)
        self.pedidos: list[str] = []

    async def buscar(self, filtros: Filtros) -> tuple[tuple[Mapping[str, Any], ...], int]:
        raise AssertionError("el tablero de ingesta no busca registros")

    async def catalogos(self) -> Mapping[str, Sequence[str]]:
        raise AssertionError("el tablero de ingesta no pide catálogos")

    async def todos(self, filtros: Filtros, limite: int) -> tuple[Mapping[str, Any], ...]:
        raise AssertionError("el tablero de ingesta no exporta")

    async def estadisticas(self, filtros: Filtros) -> Mapping[str, Any]:
        raise AssertionError("el tablero de ingesta no calcula agregados")

    async def estado_fuentes(self) -> Sequence[Mapping[str, Any]]:
        self.pedidos.append("estado_fuentes")
        return self.fuentes

    async def historial_sincronizaciones(self, por_fuente: int = 24) -> Sequence[Mapping[str, Any]]:
        self.pedidos.append("historial_sincronizaciones")
        return self.historial

    async def estado_fuente(self, codigo: str) -> Mapping[str, Any] | None:
        raise AssertionError("el tablero de ingesta no consulta una fuente suelta")

    async def ultima_ingesta_de(self, terminos: Sequence[str]) -> datetime | None:
        raise AssertionError("el tablero de ingesta no consulta ingestas de términos")


# --------------------------------------------------------------------------- #
# Quién puede pedir un ciclo
# --------------------------------------------------------------------------- #


async def test_solo_el_superadministrador_puede_pedir_un_ciclo() -> None:
    """Ni un administrador de empresa: ingerir es cosa de la plataforma, no de un cliente."""
    cache = CacheFalsa()

    for actor in (ADMIN, CONSULTOR):
        with pytest.raises(SinPermiso):
            await solicitar_ciclo(actor, cache=cache)

    assert cache.guardadas == {}


async def test_sin_cache_no_se_finge_la_peticion() -> None:
    """Aceptarla sin poder entregarla dejaría un botón que dice «hecho» sin que pase nada.

    El worker nunca la vería —pregunta al caché, y sin caché no hay donde preguntar—, así que la
    respuesta honesta es negarse y decir por qué.
    """
    cache = CacheFalsa(habilitada=False)

    with pytest.raises(EstadoInvalido) as fallo:
        await solicitar_ciclo(PLATAFORMA, cache=cache)

    assert "caché" in str(fallo.value).lower()
    assert cache.guardadas == {}


# --------------------------------------------------------------------------- #
# Una petición es una vez
# --------------------------------------------------------------------------- #


async def test_la_peticion_guarda_quien_la_pidio_y_caduca() -> None:
    cache = CacheFalsa()

    peticion = await solicitar_ciclo(PLATAFORMA, cache=cache, ahora=AHORA)

    assert peticion.solicitado_por == str(USUARIO)
    guardada = de_json(cache.guardadas[CLAVE_SOLICITUD])
    assert guardada["solicitado_en"] == AHORA.isoformat()
    assert cache.ttl[CLAVE_SOLICITUD] == TTL_SOLICITUD_SEG


async def test_la_peticion_se_consume_una_sola_vez() -> None:
    """Si nadie la borrara, el worker la ejecutaría en cada vuelta: un ciclo cada cinco segundos."""
    cache = CacheFalsa()
    await solicitar_ciclo(PLATAFORMA, cache=cache, ahora=AHORA)

    primera = await consumir_solicitud(cache)
    segunda = await consumir_solicitud(cache)

    assert primera is not None and primera.solicitado_por == str(USUARIO)
    assert primera.solicitado_en == AHORA
    assert segunda is None
    assert await solicitud_pendiente(cache) is None


async def test_una_peticion_ilegible_no_es_una_peticion() -> None:
    """Lo que hay en la caché lo escribió otro proceso: si llega roto, no puede tumbar al worker."""
    cache = CacheFalsa()
    cache.guardadas[CLAVE_SOLICITUD] = "esto no es json"

    assert await solicitud_pendiente(cache) is None
    assert await consumir_solicitud(cache) is None
    # Y se quita: un valor ilegible no se va a volver legible, y dejarlo sería preguntarlo en cada
    # vuelta durante quince minutos.
    assert CLAVE_SOLICITUD not in cache.guardadas


async def test_sin_cache_el_worker_no_pregunta() -> None:
    cache = CacheFalsa(habilitada=False)

    assert await solicitud_pendiente(cache) is None
    assert await consumir_solicitud(cache) is None


# --------------------------------------------------------------------------- #
# El tablero
# --------------------------------------------------------------------------- #


async def test_el_tablero_agrupa_los_ciclos_por_fuente() -> None:
    """Dos series y no una lista mezclada: las dos fuentes llevan cadencias distintas."""
    consultas = ConsultasFalsas(
        fuentes=[{"codigo": "NCO", "estado": "ok"}],
        historial=[
            {"fuente": "NCO", "nuevos": 3, "estado": "ok"},
            {"fuente": "OCDS", "nuevos": 5000, "estado": "parcial"},
            {"fuente": "NCO", "nuevos": 0, "estado": "ok"},
        ],
    )

    tablero = await tablero_ingesta(PLATAFORMA, repositorio=consultas, cache=CacheFalsa())

    assert tablero["fuentes"] == [{"codigo": "NCO", "estado": "ok"}]
    assert [ciclo["nuevos"] for ciclo in tablero["historial"]["NCO"]] == [3, 0]
    assert [ciclo["estado"] for ciclo in tablero["historial"]["OCDS"]] == ["parcial"]
    assert tablero["solicitud"] is None
    assert tablero["cadencia_seg"] == PASO_COMPROBACION_SEG


async def test_el_tablero_enseña_la_peticion_pendiente() -> None:
    cache = CacheFalsa()
    await solicitar_ciclo(PLATAFORMA, cache=cache, ahora=AHORA)

    tablero = await tablero_ingesta(PLATAFORMA, repositorio=ConsultasFalsas(), cache=cache)

    assert tablero["solicitud"] == {
        "solicitado_por": str(USUARIO),
        "solicitado_en": AHORA.isoformat(),
    }


async def test_el_tablero_tambien_es_solo_para_la_plataforma() -> None:
    """Se niega **antes** de leer: el historial de ciclos no lo mira un cliente ni de casualidad."""
    consultas = ConsultasFalsas()

    with pytest.raises(SinPermiso):
        await tablero_ingesta(ADMIN, repositorio=consultas, cache=CacheFalsa())

    assert consultas.pedidos == []
