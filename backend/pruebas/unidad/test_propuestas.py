"""«Propuestas para ti»: qué ínfimas se sugieren, por qué, y que la lista sea completa."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.casos_uso.ver_propuestas import ver_propuestas
from contratacion.dominio.acceso import Vista
from contratacion.dominio.errores import DatoInvalido, SinPermiso
from contratacion.dominio.propuestas import (
    Zona,
    condiciones_cpc,
    cpc_que_coinciden,
    evaluar,
    lugar_en_zona,
    ordenar,
    restringir_a_provincia,
    resumen_criterios,
    zonas_desde_perfil,
)
from contratacion.dominio.radar import (
    CriteriosComerciales,
    cpc_del_perfil,
    criterios_desde_perfil,
)

AHORA = datetime.now(UTC)


def _criterios(**extra: Any) -> CriteriosComerciales:
    base: dict[str, Any] = {"cpc": ("73210", "8715"), "palabras": ("toner",)}
    base.update(extra)
    return CriteriosComerciales(**base)


def _infima(**extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": 1,
        "codigo": "NIC-1-2026-1",
        "objeto": "Alquiler de equipos de sonido",
        "entidad": "Municipio",
        "provincia": "PICHINCHA",
        "canton": "DISTRITO METROPOLITANO DE QUITO",
        "cpc_codigos": ["732100011"],
        "presupuesto": None,
        "documentos": [],
        "plazo": AHORA + timedelta(days=2),
        "texto": "",
    }
    base.update(extra)
    return base


# --- CPC ---------------------------------------------------------------------------------------


def test_el_cpc_coincide_por_el_inicio_en_los_dos_sentidos() -> None:
    assert cpc_que_coinciden(("73210",), ["732100011"]) == ["73210"]
    assert cpc_que_coinciden(("73210",), ["7321"]) == ["73210"]
    assert cpc_que_coinciden(("73210.00.1",), ["732100011"]) == ["73210.00.1"]


def test_un_cpc_en_medio_de_otro_codigo_no_cuenta() -> None:
    # El radar acepta «73210» dentro de «1732105»; una propuesta no: sería otra familia.
    assert cpc_que_coinciden(("73210",), ["1732105"]) == []


def test_codigos_demasiado_cortos_no_coinciden() -> None:
    assert cpc_que_coinciden(("73",), ["732100011"]) == []
    assert cpc_que_coinciden(("73210",), ["73"]) == []


def test_las_condiciones_de_sql_dicen_lo_mismo_que_la_regla() -> None:
    codigos, inicios = condiciones_cpc(("73210", "12"))
    assert codigos == ["73210"]
    assert inicios == ["7321", "73210"]


def test_los_cpc_del_rup_y_de_la_experiencia_entran_en_los_criterios() -> None:
    perfil = {
        "ofertas": [{"nombre": "SERVICIOS DE GRABACION DE SONIDO", "descripcion": "CPC 96111"}],
        "experiencia": [{"objeto": "Mantenimiento", "cpc": "8715"}],
    }
    assert cpc_del_perfil(perfil) == ["96111", "8715"]
    criterios = criterios_desde_perfil(perfil, ["73210", "96111"])
    assert criterios.cpc == ("73210", "96111", "8715")
    # «CPC 96111» ya no se queda como palabra: no aparecería en ningún objeto.
    assert all("CPC" not in palabra for palabra in criterios.palabras)


# --- Ubicación ---------------------------------------------------------------------------------


def test_la_cobertura_se_compara_por_pares_provincia_y_canton() -> None:
    zonas = (Zona("Pichincha"), Zona("Guayas", "Guayaquil"))
    assert lugar_en_zona(zonas, "PICHINCHA", "CAYAMBE") == "En tu provincia"
    assert lugar_en_zona(zonas, "GUAYAS", "GUAYAQUIL") == "En tu cantón (Guayaquil)"
    assert lugar_en_zona(zonas, "GUAYAS", "DURAN") is None
    assert lugar_en_zona(zonas, "AZUAY", "CUENCA") is None


def test_quito_es_el_distrito_metropolitano() -> None:
    zonas = (Zona("Pichincha", "Quito"),)
    assert lugar_en_zona(zonas, "PICHINCHA", "DISTRITO METROPOLITANO DE QUITO") is not None
    assert lugar_en_zona(zonas, "PICHINCHA", "CAYAMBE") is None


def test_sin_cobertura_no_se_excluye_nada() -> None:
    assert lugar_en_zona((), "AZUAY", "CUENCA") == ""


def test_las_zonas_no_se_repiten_y_el_filtro_deja_una_provincia() -> None:
    perfil = {
        "cobertura": [
            {"provincia": "Pichincha", "canton": "Quito"},
            {"provincia": "Pichincha", "canton": "Quito"},
            {"provincia": "Guayas", "canton": ""},
        ]
    }
    zonas = zonas_desde_perfil(perfil)
    assert zonas == (Zona("Pichincha", "Quito"), Zona("Guayas", ""))
    assert restringir_a_provincia(zonas, "guayas") == (Zona("Guayas", ""),)
    # Fuera de la cobertura se busca igual en esa provincia: quien la elige la pide a propósito.
    assert restringir_a_provincia(zonas, "Azuay") == (Zona("Azuay"),)


# --- Evaluación y motivos ----------------------------------------------------------------------


def test_una_infima_que_encaja_dice_por_que() -> None:
    propuesta = evaluar(_criterios(), (Zona("Pichincha"),), _infima())
    assert propuesta is not None
    assert "Tu CPC 73210 coincide" in propuesta["motivos"]
    assert "En tu provincia" in propuesta["motivos"]
    assert propuesta["cpc_coinciden"] == ["73210"]
    assert 0 < propuesta["puntos"] <= 100


def test_por_palabras_tambien_entra() -> None:
    fila = _infima(cpc_codigos=["999999"], objeto="Compra de toner para impresoras")
    propuesta = evaluar(_criterios(), (), fila)
    assert propuesta is not None
    assert "Menciona: toner" in propuesta["motivos"]


def test_sin_cpc_ni_palabras_no_entra() -> None:
    fila = _infima(cpc_codigos=["111111"], objeto="Compra de cemento")
    assert evaluar(_criterios(), (), fila) is None


def test_fuera_de_la_zona_no_entra() -> None:
    assert evaluar(_criterios(), (Zona("Guayas"),), _infima()) is None


def test_presupuesto_desconocido_no_excluye_y_fuera_de_rango_si() -> None:
    criterios = _criterios(presupuesto_max=7000.0)
    sin_monto = evaluar(criterios, (), _infima(presupuesto=None))
    assert sin_monto is not None
    assert "Dentro de tu presupuesto" not in sin_monto["motivos"]
    dentro = evaluar(criterios, (), _infima(presupuesto=3000))
    assert dentro is not None
    assert "Dentro de tu presupuesto" in dentro["motivos"]
    assert evaluar(criterios, (), _infima(presupuesto=9000)) is None


def test_los_ordenes() -> None:
    a = {"puntos": 90, "plazo": AHORA + timedelta(days=5), "presupuesto": None}
    b = {"puntos": 60, "plazo": AHORA + timedelta(days=1), "presupuesto": 5000.0}
    c = {"puntos": 70, "plazo": AHORA + timedelta(days=3), "presupuesto": 9000.0}
    assert ordenar([a, b, c], "coincidencia") == [a, c, b]
    assert ordenar([a, b, c], "cierre") == [b, c, a]
    assert ordenar([a, b, c], "presupuesto") == [c, b, a]


def test_el_resumen_se_lee_en_una_linea() -> None:
    criterios = _criterios(cpc=tuple(str(70000 + n) for n in range(6)), presupuesto_max=7000.0)
    resumen = resumen_criterios(criterios, (Zona("Pichincha", "Quito"),))
    assert resumen["texto"] == "6 CPC · lo que ofreces · Pichincha · hasta $7.000"
    assert resumen["total_cpc"] == 6


# --- Caso de uso -------------------------------------------------------------------------------


class _Perfil:
    def __init__(self, ficha: dict[str, Any]) -> None:
        self.ficha = ficha

    async def leer(self, negocio_id: Any) -> dict[str, Any]:
        return self.ficha


class _Cpc:
    def __init__(self, textos: list[str]) -> None:
        self.textos = textos

    async def listar(self, *, negocio_id: Any) -> tuple[Any, ...]:
        return tuple(SimpleNamespace(texto=texto) for texto in self.textos)


class _Infimas:
    def __init__(self, filas: list[dict[str, Any]]) -> None:
        self.filas = filas
        self.llamadas: list[dict[str, Any]] = []

    async def infimas_abiertas(self, **parametros: Any) -> list[dict[str, Any]]:
        self.llamadas.append(parametros)
        return self.filas


class _Cache:
    def __init__(self) -> None:
        self.datos: dict[str, str] = {}

    @property
    def habilitada(self) -> bool:
        return True

    async def obtener(self, clave: str) -> str | None:
        return self.datos.get(clave)

    async def guardar(self, clave: str, valor: str, ttl_seg: int) -> None:
        self.datos[clave] = valor


ACTOR = Actor(usuario_id=uuid4(), negocio_id=uuid4(), rol="usuario_negocio")
FICHA = {"cobertura": [{"provincia": "Pichincha", "canton": ""}], "presupuesto_max": 7000}


async def _llamar(infimas: _Infimas, cache: _Cache, **extra: Any) -> dict[str, Any]:
    parametros: dict[str, Any] = {
        "vistas": frozenset({Vista.NECESIDADES}),
        "perfil": _Perfil(extra.pop("ficha", FICHA)),
        "cpc": _Cpc(extra.pop("cpc", ["73210"])),
        "infimas": infimas,
        "cache": cache,
    }
    parametros.update(extra)
    return await ver_propuestas(ACTOR, **parametros)


async def test_pagina_todo_y_lo_guarda_en_cache() -> None:
    filas = [_infima(id=n, codigo=f"NIC-{n}") for n in range(25)]
    filas.append(_infima(id=99, codigo="NIC-99", provincia="GUAYAS"))
    infimas, cache = _Infimas(filas), _Cache()

    primera = await _llamar(infimas, cache, tamano=10)
    assert primera["total"] == 25
    assert len(primera["propuestas"]) == 10
    assert primera["completo"] is True
    assert primera["criterios"]["texto"] == "1 CPC · Pichincha · hasta $7.000"
    assert infimas.llamadas[0]["provincias"] == ("Pichincha",)
    assert infimas.llamadas[0]["incluir_sin_plazo"] is False

    tercera = await _llamar(infimas, cache, tamano=10, pagina=3)
    assert len(tercera["propuestas"]) == 5
    assert len(infimas.llamadas) == 1, "la segunda página sale del caché"


async def test_sin_cpc_ni_productos_lo_dice_claro() -> None:
    infimas = _Infimas([_infima()])
    respuesta = await _llamar(infimas, _Cache(), ficha={}, cpc=[])
    assert respuesta["propuestas"] == []
    assert "RUP" in respuesta["motivo"]
    assert infimas.llamadas == []


async def test_sin_la_vista_de_infimas_no_hay_propuestas() -> None:
    with pytest.raises(SinPermiso):
        await _llamar(_Infimas([]), _Cache(), vistas=frozenset({Vista.OFERTAS}))


async def test_orden_desconocido_se_rechaza() -> None:
    with pytest.raises(DatoInvalido):
        await _llamar(_Infimas([]), _Cache(), orden="azar")
