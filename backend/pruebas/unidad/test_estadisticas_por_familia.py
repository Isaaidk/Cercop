"""Pruebas de los totales por familia que llevan las pestañas del panel.

El panel muestra un número junto a «Ínfimas cuantías» y junto a «Ofertas». Ese número tiene que ser
el de **su** familia: antes las dos leían el total de la última consulta, y como abrir la pestaña de
ofertas cambia la familia que se consulta, el número de las ínfimas pasaba a mostrar el de las
ofertas. Lo que se comprueba aquí es que la traducción del conteo por fuente a totales por familia
es la correcta, que las dos familias salen **siempre** —también con cero— y que el conteo bruto no
se cuela en la respuesta.

Se prueba sin base de datos: el repositorio es un doble que devuelve el conteo por fuente ya
calculado. Lo que se verifica es la regla, no el SQL.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from contratacion.aplicacion.casos_uso.buscar_registros import obtener_estadisticas
from contratacion.dominio.busqueda import Filtros


class CacheFalsa:
    """Caché en memoria. Implementa el protocolo entero aunque la prueba no use todo."""

    def __init__(self) -> None:
        self.guardadas: dict[str, str] = {}

    @property
    def habilitada(self) -> bool:
        return True

    async def obtener(self, clave: str) -> str | None:
        return self.guardadas.get(clave)

    async def obtener_renovando(self, clave: str, ttl_seg: int) -> str | None:
        return await self.obtener(clave)

    async def guardar(self, clave: str, valor: str, ttl_seg: int) -> None:
        self.guardadas[clave] = valor

    async def eliminar(self, clave: str) -> None:
        self.guardadas.pop(clave, None)

    async def incrementar(self, clave: str) -> int:
        resultado = int(self.guardadas.get(clave, "0")) + 1
        self.guardadas[clave] = str(resultado)
        return resultado

    async def ping(self) -> bool:
        return True

    async def cerrar(self) -> None:
        return None


class ConsultasFalsas:
    """Repositorio que devuelve el conteo por fuente que se le indique, sin tocar la base.

    El resto de los métodos del protocolo se declaran y lanzan: un doble al que le falte uno no
    falla al escribirlo, falla el día que alguien lo usa.
    """

    def __init__(self, por_fuente_sin_familia: Sequence[Mapping[str, Any]]) -> None:
        self.por_fuente_sin_familia = tuple(por_fuente_sin_familia)
        self.filtros_vistos: Filtros | None = None

    async def buscar(self, filtros: Filtros) -> tuple[tuple[Mapping[str, Any], ...], int]:
        raise AssertionError("las estadísticas no buscan registros")

    async def catalogos(self) -> Mapping[str, Sequence[str]]:
        raise AssertionError("las estadísticas no piden catálogos")

    async def todos(self, filtros: Filtros, limite: int) -> tuple[Mapping[str, Any], ...]:
        raise AssertionError("las estadísticas no exportan")

    async def estadisticas(self, filtros: Filtros) -> Mapping[str, Any]:
        self.filtros_vistos = filtros
        return {
            "fuente": filtros.fuente,
            "por_fuente": [dict(fila) for fila in self.por_fuente_sin_familia],
            "por_fuente_sin_familia": [dict(fila) for fila in self.por_fuente_sin_familia],
            "serie_mensual": [],
            "por_provincia": [],
        }

    async def estado_fuentes(self) -> Sequence[Mapping[str, Any]]:
        raise AssertionError("las estadísticas no consultan el estado de las fuentes")

    async def historial_sincronizaciones(self, por_fuente: int = 24) -> Sequence[Mapping[str, Any]]:
        raise AssertionError("las estadísticas no consultan el historial de ciclos")

    async def estado_fuente(self, codigo: str) -> Mapping[str, Any] | None:
        raise AssertionError("las estadísticas no consultan una fuente")

    async def ultima_ingesta_de(self, terminos: Sequence[str]) -> datetime | None:
        raise AssertionError("las estadísticas no consultan ingestas de términos")


async def _pedir(por_fuente_sin_familia: Sequence[Mapping[str, Any]]) -> dict[str, object]:
    consultas = ConsultasFalsas(por_fuente_sin_familia)
    # Con permiso sobre las dos fuentes: sin ninguna vista concedida el caso de uso rechaza la
    # consulta antes de calcular nada, y lo que se prueba aquí es la traducción a familias.
    filtros = Filtros(fuentes_permitidas=("NCO", "OCDS"))
    return await obtener_estadisticas(filtros, cache=CacheFalsa(), repositorio=consultas)


async def test_cada_familia_usa_su_propio_conteo() -> None:
    datos = await _pedir([{"fuente": "NCO", "total": 2210}, {"fuente": "OCDS", "total": 53}])

    assert datos["por_categoria"] == [
        {"categoria": "infimas", "total": 2210},
        {"categoria": "ofertas", "total": 53},
    ]


async def test_las_dos_familias_salen_siempre_y_en_el_mismo_orden() -> None:
    """Con solo una fuente, la otra familia sale en cero en lugar de faltar.

    Que falte obligaría al panel a distinguir «no hay» de «no se pudo calcular», y las pestañas
    cambiarían de forma según los datos. El orden es el del dominio: ínfimas primero.
    """
    datos = await _pedir([{"fuente": "OCDS", "total": 53}])

    assert datos["por_categoria"] == [
        {"categoria": "infimas", "total": 0},
        {"categoria": "ofertas", "total": 53},
    ]


async def test_una_fuente_desconocida_no_se_cuenta_en_ninguna_familia() -> None:
    """Una fuente que todavía no está clasificada no engorda una pestaña que no le toca.

    Es el caso de una fuente nueva antes de decidir a qué familia pertenece: sus filas siguen
    apareciendo en `por_fuente`, pero no se le atribuyen a ninguna pestaña.
    """
    datos = await _pedir(
        [{"fuente": "SERCOP", "total": 40}, {"fuente": "NCO", "total": 7}],
    )

    assert datos["por_categoria"] == [
        {"categoria": "infimas", "total": 7},
        {"categoria": "ofertas", "total": 0},
    ]


async def test_el_conteo_bruto_no_aparece_en_la_respuesta() -> None:
    """`por_fuente_sin_familia` es el dato del que sale el total, no parte del contrato."""
    datos = await _pedir([{"fuente": "NCO", "total": 7}])

    assert "por_fuente_sin_familia" not in datos


async def test_sin_conteo_los_dos_totales_quedan_en_cero() -> None:
    """Un repositorio que no devuelva el conteo degrada a ceros; no rompe la respuesta."""
    datos = await _pedir([])

    assert datos["por_categoria"] == [
        {"categoria": "infimas", "total": 0},
        {"categoria": "ofertas", "total": 0},
    ]
