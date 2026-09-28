"""Pruebas de la exigencia de vistas al leer.

El control de vistas se guardaba desde hacía fases, pero no se exigía. Estas pruebas defienden las
tres propiedades que lo hacen efectivo y que son fáciles de romper sin que nada falle a la vista:

1. **Una lista vacía de fuentes significa ninguna, no todas.** Interpretarla como «sin restricción»
   convertiría a un usuario al que se le acaban de retirar las vistas en uno con acceso completo,
   y el fallo sería silencioso.
2. **El permiso forma parte de la clave de caché.** Sin eso, un usuario con dos vistas cachea la
   página completa y otro con una sola recibe esa misma página: una fuga entre niveles de permiso
   que el aislamiento entre negocios no detecta, porque los dos son del mismo negocio.
3. **Sin fuentes no se consulta.** La negativa ocurre antes de tocar la base, así que no se puede
   «casi» leer y luego descartar.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from contratacion.aplicacion.casos_uso.buscar_registros import MENSAJE_SIN_FUENTES, buscar
from contratacion.dominio.acceso import Vista, fuentes_para_vistas
from contratacion.dominio.busqueda import Filtros, clave_resultados, huella_filtros
from contratacion.dominio.errores import SinPermiso

# --------------------------------------------------------------------------- #
# Traducción de permisos a fuentes
# --------------------------------------------------------------------------- #


def test_necesidades_da_acceso_a_la_fuente_de_necesidades() -> None:
    assert fuentes_para_vistas([Vista.NECESIDADES]) == ("NCO",)


def test_contrataciones_da_acceso_a_la_fuente_de_procesos() -> None:
    assert fuentes_para_vistas([Vista.CONTRATACIONES]) == ("OCDS",)


def test_las_dos_vistas_juntas_dan_las_dos_fuentes() -> None:
    assert fuentes_para_vistas([Vista.NECESIDADES, Vista.CONTRATACIONES]) == ("NCO", "OCDS")


def test_una_vista_sin_datos_no_concede_ninguna_fuente() -> None:
    """«Ofertas» existe en el catálogo, pero todavía no tiene datos detrás."""
    assert fuentes_para_vistas([Vista.OFERTAS]) == ()


def test_las_graficas_no_conceden_datos_de_registros() -> None:
    """Quien solo tiene gráficas ve agregados, no los expedientes uno a uno."""
    assert fuentes_para_vistas([Vista.GRAFICAS]) == ()


def test_sin_vistas_no_hay_ninguna_fuente() -> None:
    """Y sobre todo: no significa «todas»."""
    assert fuentes_para_vistas([]) == ()


def test_el_orden_de_las_fuentes_es_estable() -> None:
    assert fuentes_para_vistas([Vista.CONTRATACIONES, Vista.NECESIDADES]) == fuentes_para_vistas(
        [Vista.NECESIDADES, Vista.CONTRATACIONES]
    )


# --------------------------------------------------------------------------- #
# El permiso en la clave de caché
# --------------------------------------------------------------------------- #


def test_el_permiso_forma_parte_de_la_huella() -> None:
    """Es la prueba más importante de este archivo.

    Dos usuarios del mismo negocio, con permisos distintos, no pueden compartir entrada de caché.
    Si la huella no incluyera las fuentes permitidas, el que solo ve Necesidades recibiría la
    página que cacheó el que ve todo, y el aislamiento entre negocios no lo detectaría porque
    ambos son del mismo negocio legítimamente.
    """
    solo_necesidades = Filtros(fuentes_permitidas=("NCO",))
    ambas = Filtros(fuentes_permitidas=("NCO", "OCDS"))

    assert huella_filtros(solo_necesidades) != huella_filtros(ambas)
    assert clave_resultados(solo_necesidades, 1) != clave_resultados(ambas, 1)


def test_el_mismo_permiso_comparte_entrada() -> None:
    """Lo contrario también importa: si no, el caché no serviría de nada."""
    unos = Filtros(terminos=("obras",), fuentes_permitidas=("NCO",))
    otros = Filtros(terminos=("obras",), fuentes_permitidas=("NCO",))
    assert clave_resultados(unos, 3) == clave_resultados(otros, 3)


def test_sin_fuentes_permitidas_la_clave_es_distinta_de_todas() -> None:
    assert huella_filtros(Filtros()) != huella_filtros(Filtros(fuentes_permitidas=("NCO", "OCDS")))


# --------------------------------------------------------------------------- #
# La negativa ocurre antes de consultar
# --------------------------------------------------------------------------- #


class CacheFalsa:
    """Caché en memoria, con un contador para saber si se llegó a guardar."""

    def __init__(self) -> None:
        self.guardadas: dict[str, str] = {}

    async def obtener(self, clave: str) -> str | None:
        return self.guardadas.get(clave)

    async def guardar(self, clave: str, valor: str, ttl_seg: int) -> None:
        self.guardadas[clave] = valor

    async def eliminar(self, clave: str) -> None:
        self.guardadas.pop(clave, None)

    async def incrementar(self, clave: str) -> int:
        return 0

    async def ping(self) -> bool:
        return True

    async def cerrar(self) -> None:
        return None


class ConsultasEspia:
    """Repositorio de lectura que cuenta cuántas veces se le consultó."""

    def __init__(self) -> None:
        self.consultas = 0

    async def buscar(self, filtros: Filtros) -> tuple[tuple[Mapping[str, Any], ...], int]:
        self.consultas += 1
        return (), 0

    async def todos(self, filtros: Filtros, limite: int) -> tuple[Mapping[str, Any], ...]:
        # Lo usa la exportación. Cuenta como consulta igual que `buscar`, porque para el permiso y
        # el aislamiento es la misma lectura del histórico: una prueba que no la contara dejaría
        # pasar una exportación que no debería haber llegado a la base.
        self.consultas += 1
        return ()

    async def catalogos(self) -> Mapping[str, Sequence[str]]:
        return {}

    async def estadisticas(self, filtros: Filtros) -> Mapping[str, Any]:
        self.consultas += 1
        return {}

    async def estado_fuentes(self) -> Sequence[Mapping[str, Any]]:
        return ()

    async def estado_fuente(self, codigo: str) -> Mapping[str, Any] | None:
        return None

    async def ultima_ingesta_de(self, terminos: Sequence[str]) -> None:
        return None


async def test_sin_fuentes_permitidas_la_busqueda_se_niega_sin_consultar() -> None:
    consultas = ConsultasEspia()

    with pytest.raises(SinPermiso) as fallo:
        await buscar(
            Filtros(terminos=("obras",), fuentes_permitidas=()),
            cache=CacheFalsa(),
            repositorio=consultas,
        )

    assert str(fallo.value) == MENSAJE_SIN_FUENTES
    assert consultas.consultas == 0, "no se puede consultar para luego descartar"


async def test_con_fuentes_permitidas_la_busqueda_procede() -> None:
    consultas = ConsultasEspia()
    cache = CacheFalsa()

    pagina = await buscar(
        Filtros(terminos=("obras",), fuentes_permitidas=("NCO",)),
        cache=cache,
        repositorio=consultas,
    )

    assert consultas.consultas == 1
    assert not pagina.desde_cache


async def test_la_segunda_consulta_igual_se_sirve_del_cache() -> None:
    consultas = ConsultasEspia()
    cache = CacheFalsa()
    filtros = Filtros(terminos=("obras",), fuentes_permitidas=("NCO",))

    await buscar(filtros, cache=cache, repositorio=consultas)
    segunda = await buscar(filtros, cache=cache, repositorio=consultas)

    assert consultas.consultas == 1, "la segunda lectura no debe tocar la base"
    assert segunda.desde_cache


async def test_un_permiso_distinto_no_reutiliza_la_pagina_cacheada() -> None:
    """El caso real: el primero ve dos fuentes y el segundo solo una."""
    consultas = ConsultasEspia()
    cache = CacheFalsa()

    await buscar(
        Filtros(terminos=("obras",), fuentes_permitidas=("NCO", "OCDS")),
        cache=cache,
        repositorio=consultas,
    )
    await buscar(
        Filtros(terminos=("obras",), fuentes_permitidas=("NCO",)),
        cache=cache,
        repositorio=consultas,
    )

    assert consultas.consultas == 2, "ninguno de los dos puede recibir la página del otro"
