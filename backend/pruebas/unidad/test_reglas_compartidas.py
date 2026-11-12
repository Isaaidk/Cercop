"""Las reglas que viven también en JavaScript dan lo mismo aquí.

`compartido/reglas_consultas.json` lo leen esta prueba y
`frontend/tests/reglasCompartidas.test.mjs`.
Si una regla cambia en un lado y no en el otro, una de las dos falla.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from contratacion.dominio.consulta_ruc import propuesta_desde_sri
from contratacion.dominio.historial import contrato_de, resumir_historial, termino_de_busqueda

CASOS: dict[str, Any] = json.loads(
    (Path(__file__).resolve().parents[3] / "compartido" / "reglas_consultas.json").read_text(
        encoding="utf-8"
    )
)


def _con(release: dict[str, Any], cpc: str, fecha: str) -> dict[str, Any]:
    """El mismo proceso con otro CPC y otra fecha."""
    copia: dict[str, Any] = json.loads(json.dumps(release))
    copia["date"] = f"{fecha}T00:00:00-05:00"
    copia["awards"][0]["items"][0]["classification"]["id"] = cpc
    return copia


def test_termino_de_busqueda() -> None:
    for entrada, esperado in CASOS["termino_de_busqueda"]:
        assert termino_de_busqueda(entrada) == esperado, entrada


def test_propuesta_del_sri() -> None:
    caso = CASOS["sri"]
    esperado = caso["esperado"]
    propuesta = propuesta_desde_sri(caso["contribuyente"], caso["establecimientos"])
    for clave, valor in esperado["identidad"].items():
        assert propuesta["identidad"][clave] == valor, clave
    assert propuesta["identidad"]["direccion"].startswith(esperado["direccion_empieza"])
    assert propuesta["representante"] == esperado["representante"]
    assert propuesta["cobertura"] == esperado["cobertura"]
    assert propuesta["avisos"] == esperado["avisos"]


def test_persona_natural_y_rimpe() -> None:
    caso = CASOS["sri_natural_rimpe"]
    identidad = propuesta_desde_sri(caso["contribuyente"], caso["establecimientos"])["identidad"]
    for clave, valor in caso["esperado"].items():
        assert identidad[clave] == valor, clave


def test_contrato_por_ruc() -> None:
    caso = CASOS["ocds"]
    contrato = contrato_de(caso["record"], caso["ruc"])
    assert contrato is not None
    esperado = caso["esperado_contrato"]
    assert contrato["cpc"] == esperado["cpc"]
    assert contrato["monto"] == esperado["monto"]
    assert contrato["productos"] == esperado["productos"]
    assert contrato_de(caso["record_homonimo"], caso["ruc"]) is None


def test_resumen_del_historial() -> None:
    caso = CASOS["ocds"]
    base = caso["record"]["releases"][0]
    contratos = []
    for cpc, fecha in caso["resumen"]["registros"]:
        contrato = contrato_de({"releases": [_con(base, cpc, fecha)]}, caso["ruc"])
        assert contrato is not None
        contratos.append(contrato)
    resumen = resumir_historial(caso["ruc"], contratos, total=30, revisados=3, termino="X")
    esperado = caso["resumen"]["esperado"]
    assert resumen["cpc"][0] == esperado["cpc_primero"]
    assert [fila["anio"] for fila in resumen["experiencia"]] == esperado["anios"]
    assert resumen["experiencia"][0]["objeto"] == esperado["objeto_primero"]
    assert resumen["verificados"] == esperado["verificados"]
