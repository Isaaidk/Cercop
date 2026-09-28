"""Pruebas de la serialización segura.

El requisito RNF-13 dice que ninguna respuesta puede contener `NaN` ni `Infinity`. Suena menor
hasta que se comprueba qué pasa: ninguno de los dos existe en el estándar JSON, así que un cliente
estricto falla al interpretar la respuesta entera. Y no hace falta un dato raro para producirlos:
una media sobre una lista vacía ya devuelve `NaN`.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from contratacion.dominio.serializacion import (
    a_json,
    cuerpo_json,
    de_json,
    es_no_finito,
    sanear,
)


def test_detecta_los_valores_no_finitos() -> None:
    assert es_no_finito(float("nan"))
    assert es_no_finito(float("inf"))
    assert es_no_finito(float("-inf"))
    assert not es_no_finito(0.0)
    assert not es_no_finito(1)


def test_reemplaza_nan_por_nulo() -> None:
    assert sanear(float("nan")) is None


def test_reemplaza_infinito_por_nulo() -> None:
    assert sanear(float("inf")) is None
    assert sanear(float("-inf")) is None


def test_sanea_dentro_de_listas_anidadas() -> None:
    """Los datos de la fuente son JSON anidado: una lista dentro de un objeto dentro de otra."""
    original = {"valores": [1.0, float("nan")], "meta": {"promedio": float("inf")}}
    assert sanear(original) == {"valores": [1.0, None], "meta": {"promedio": None}}


def test_conserva_los_numeros_normales() -> None:
    assert sanear({"a": 1, "b": 2.5, "c": -3}) == {"a": 1, "b": 2.5, "c": -3}


def test_convierte_fechas_a_texto_iso() -> None:
    assert sanear(datetime(2026, 9, 27, 10, 30, tzinfo=UTC)) == "2026-09-27T10:30:00+00:00"
    assert sanear(date(2026, 9, 27)) == "2026-09-27"


def test_convierte_identificadores_a_texto() -> None:
    identificador = uuid4()
    assert sanear(identificador) == str(identificador)


def test_convierte_decimal_a_numero() -> None:
    """`Decimal` no es serializable por defecto y el mapeo de montos lo produce."""
    assert sanear(Decimal("1234.56")) == 1234.56


def test_convierte_conjuntos_a_listas() -> None:
    assert sorted(sanear({3, 1, 2})) == [1, 2, 3]


def test_el_texto_json_se_puede_reconstruir() -> None:
    original = {"a": [1, 2], "b": {"c": None}}
    assert de_json(a_json(original)) == original


def test_un_valor_no_finito_nunca_llega_al_texto_json() -> None:
    """La red de seguridad: si algo se escapara del saneado, debe fallar aquí y no en el cliente."""
    texto = a_json({"promedio": float("nan")})
    assert "NaN" not in texto
    assert json.loads(texto) == {"promedio": None}


def test_el_cuerpo_de_respuesta_es_un_diccionario() -> None:
    assert cuerpo_json({"total": 3}) == {"total": 3}


def test_el_cuerpo_de_respuesta_limpia_los_valores_no_finitos() -> None:
    cuerpo = cuerpo_json({"total": float("inf"), "filas": [float("nan")]})
    assert cuerpo == {"total": None, "filas": [None]}


def test_el_texto_json_es_compacto() -> None:
    """Las respuestas viajan por red: los espacios de la sangría son bytes que paga el cliente."""
    assert a_json({"a": 1}) == '{"a":1}'


def test_conserva_los_acentos_sin_escaparlos() -> None:
    assert a_json({"nombre": "Gestión"}) == '{"nombre":"Gestión"}'


@pytest.mark.parametrize("valor", [True, False, 0, "", [], {}, None])
def test_los_valores_simples_sobreviven_intactos(valor: object) -> None:
    assert sanear(valor) == valor
