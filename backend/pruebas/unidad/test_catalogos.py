"""Pruebas de la caché de los catálogos de filtros.

Es la consulta más cara del sistema —recorre el histórico entero sacando los valores distintos de
cada campo— y se dispara **al abrir cada panel**. Así que lo que se comprueba aquí es una sola cosa:
que el recorrido se paga una vez y no una por persona. Y, en el otro sentido, que un caché roto no
deja el panel sin desplegables.

La entrada es compartida por todos los usuarios, a diferencia de los resultados. Eso es correcto
porque un desplegable ofrece lo que hay en el histórico y no lo que cumple un filtro, pero es
precisamente lo que hace que la comprobación de permiso tenga que ocurrir **antes** de mirar el
caché: eso se prueba en el enrutador, no aquí.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from contratacion.aplicacion.casos_uso.buscar_registros import (
    CATALOGO_DE_FILTROS,
    obtener_catalogos,
)
from contratacion.dominio.busqueda import (
    GENERACION_GLOBAL,
    Filtros,
    clave_catalogo,
    clave_generacion,
)

CATALOGOS: dict[str, list[str]] = {
    "provincia": ["Pichincha", "Napo"],
    "estado": ["En Curso"],
    "entidad": ["TGP", "Municipio de Quito"],
}


class CacheFalsa:
    """Caché en memoria. `falla` permite simular un almacén que no responde.

    Implementa el protocolo completo aunque la prueba no use todo: un doble al que le falte un
    método no falla al escribirlo, falla el día que alguien usa el que falta.
    """

    def __init__(self, *, falla: bool = False) -> None:
        self.guardadas: dict[str, str] = {}
        self.falla = falla

    async def obtener(self, clave: str) -> str | None:
        if self.falla:
            raise RuntimeError("el almacén no responde")
        return self.guardadas.get(clave)

    @property
    def habilitada(self) -> bool:
        return True

    async def obtener_renovando(self, clave: str, ttl_seg: int) -> str | None:
        return await self.obtener(clave)

    async def guardar(self, clave: str, valor: str, ttl_seg: int) -> None:
        if self.falla:
            raise RuntimeError("el almacén no responde")
        self.guardadas[clave] = valor

    async def eliminar(self, clave: str) -> None:
        self.guardadas.pop(clave, None)

    async def incrementar(self, clave: str) -> int:
        resultado = int(self.guardadas.get(clave, "0")) + 1
        self.guardadas[clave] = str(resultado)
        return resultado

    async def ping(self) -> bool:
        return not self.falla

    async def cerrar(self) -> None:
        return None


class ConsultasEspia:
    """Repositorio que cuenta cuántas veces le pidieron los catálogos."""

    def __init__(self) -> None:
        self.veces = 0

    async def buscar(self, filtros: Filtros) -> tuple[tuple[Mapping[str, Any], ...], int]:
        raise AssertionError("pedir catálogos no debería buscar registros")

    async def catalogos(self) -> Mapping[str, Sequence[str]]:
        self.veces += 1
        return CATALOGOS

    async def todos(self, filtros: Filtros, limite: int) -> tuple[Mapping[str, Any], ...]:
        raise AssertionError("pedir catálogos no debería exportar")

    async def estadisticas(self, filtros: Filtros) -> Mapping[str, Any]:
        raise AssertionError("pedir catálogos no debería calcular agregados")

    async def estado_fuentes(self) -> Sequence[Mapping[str, Any]]:
        raise AssertionError("pedir catálogos no debería consultar el estado de las fuentes")

    async def historial_sincronizaciones(self, por_fuente: int = 24) -> Sequence[Mapping[str, Any]]:
        raise AssertionError("pedir catálogos no debería consultar el historial de ciclos")

    async def estado_fuente(self, codigo: str) -> Mapping[str, Any] | None:
        raise AssertionError("pedir catálogos no debería consultar una fuente")

    async def ultima_ingesta_de(self, terminos: Sequence[str]) -> datetime | None:
        raise AssertionError("pedir catálogos no debería consultar ingestas de términos")


# --------------------------------------------------------------------------- #
# Se paga una vez
# --------------------------------------------------------------------------- #


async def test_la_primera_consulta_va_al_repositorio_y_se_guarda() -> None:
    cache = CacheFalsa()
    consultas = ConsultasEspia()

    datos = await obtener_catalogos(cache=cache, repositorio=consultas)

    assert datos == CATALOGOS
    assert consultas.veces == 1
    assert clave_catalogo(CATALOGO_DE_FILTROS, 0) in cache.guardadas


async def test_la_segunda_consulta_no_toca_el_repositorio() -> None:
    """Es el objetivo entero: el recorrido del histórico se paga una vez, no una por usuario."""
    cache = CacheFalsa()
    consultas = ConsultasEspia()

    await obtener_catalogos(cache=cache, repositorio=consultas)
    segunda = await obtener_catalogos(cache=cache, repositorio=consultas)

    assert segunda == CATALOGOS
    assert consultas.veces == 1


async def test_la_clave_lleva_la_generacion_para_poder_invalidarlos() -> None:
    cache = CacheFalsa()
    cache.guardadas[clave_generacion(GENERACION_GLOBAL)] = "7"

    await obtener_catalogos(cache=cache, repositorio=ConsultasEspia())

    assert clave_catalogo(CATALOGO_DE_FILTROS, 7) in cache.guardadas


async def test_subir_la_generacion_obliga_a_recalcular() -> None:
    """Los desplegables cambian cuando entra una contratación, y de eso avisa la generación."""
    cache = CacheFalsa()
    consultas = ConsultasEspia()

    await obtener_catalogos(cache=cache, repositorio=consultas)
    cache.guardadas[clave_generacion(GENERACION_GLOBAL)] = "1"
    await obtener_catalogos(cache=cache, repositorio=consultas)

    assert consultas.veces == 2


# --------------------------------------------------------------------------- #
# El caché nunca rompe la consulta
# --------------------------------------------------------------------------- #


async def test_un_cache_roto_no_deja_el_panel_sin_desplegables() -> None:
    """Perder el caché cuesta latencia, no corrección."""
    consultas = ConsultasEspia()

    datos = await obtener_catalogos(cache=CacheFalsa(falla=True), repositorio=consultas)

    assert datos == CATALOGOS
    assert consultas.veces == 1


async def test_una_entrada_ilegible_se_recalcula() -> None:
    cache = CacheFalsa()
    cache.guardadas[clave_catalogo(CATALOGO_DE_FILTROS, 0)] = "no es un objeto json"
    consultas = ConsultasEspia()

    datos = await obtener_catalogos(cache=cache, repositorio=consultas)

    assert datos == CATALOGOS
    assert consultas.veces == 1
