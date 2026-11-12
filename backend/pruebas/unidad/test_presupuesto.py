"""Presupuesto del proceso: de dónde sale, si incluye IVA y si la proforma cabe en él."""

from __future__ import annotations

from typing import Any

import pytest

from contratacion.dominio.documentos import calcular_proforma
from contratacion.dominio.errores import DatoInvalido
from contratacion.dominio.presupuesto import (
    comparar_con_presupuesto,
    dinero,
    elegir_presupuesto,
    exigir_dentro_del_presupuesto,
    extraer_presupuesto,
    normalizar_presupuesto,
    numero_de,
    presupuesto_de_ficha,
)
from contratacion.dominio.verificacion import verificar_proforma

# ── Extracción del texto ────────────────────────────────────────────────────────────────────────


def test_formato_ecuatoriano_y_sin_iva() -> None:
    hallado = extraer_presupuesto(
        "4. PRESUPUESTO REFERENCIAL: USD 1.234,56 (mil doscientos treinta y cuatro) no incluye IVA"
    )
    assert hallado is not None
    assert hallado["valor"] == 1234.56
    assert hallado["incluye_iva"] is False
    assert hallado["fuente"] == "tdr"
    assert "USD 1.234,56" in hallado["cita"]


def test_formato_con_coma_de_miles_y_mas_iva() -> None:
    hallado = extraer_presupuesto("El presupuesto referencial es de $ 5,600.00 más IVA.")
    assert hallado is not None and hallado["valor"] == 5600.0
    assert hallado["incluye_iva"] is False


def test_iva_incluido_y_moneda_detras() -> None:
    hallado = extraer_presupuesto("Presupuesto: 3500.00 dólares, IVA incluido.", "pliego")
    assert hallado is not None
    assert (hallado["valor"], hallado["incluye_iva"], hallado["fuente"]) == (3500.0, True, "pliego")


def test_sin_mencion_del_iva_queda_sin_dato() -> None:
    hallado = extraer_presupuesto("VALOR ESTIMADO: $ 980,00")
    assert hallado is not None and hallado["incluye_iva"] is None


def test_el_hueco_del_formulario_no_es_un_monto() -> None:
    # La garantía de más adelante no debe tomarse por el presupuesto.
    assert (
        extraer_presupuesto("VALOR ESTIMADO: $............ PLAZO: 30 días. Garantía $ 200,00")
        is None
    )
    assert extraer_presupuesto("PRESUPUESTO REFERENCIAL: $ 0,00") is None
    assert extraer_presupuesto("Presupuesto referencial: [por completar]") is None


def test_la_etiqueta_mas_fiable_gana_aunque_venga_despues() -> None:
    texto = "Monto de la garantía: $ 50,00. Presupuesto referencial: $ 2.000,00 sin IVA."
    hallado = extraer_presupuesto(texto)
    assert hallado is not None and hallado["valor"] == 2000.0


def test_no_confunde_partidas_ni_porcentajes() -> None:
    assert extraer_presupuesto("Presupuesto: partida 73.08.04, IVA 15%") is None
    assert extraer_presupuesto("Sin presupuesto publicado.") is None


def test_numeros() -> None:
    assert numero_de("1.234") == 1234
    assert numero_de("1.234,56") == 1234.56
    assert numero_de("1,234.56") == 1234.56
    assert numero_de("12,5") == 12.5
    assert numero_de("1.234.567") == 1234567
    assert dinero(1234.5) == "$1.234,50"


# ── Ficha y elección ────────────────────────────────────────────────────────────────────────────


def test_presupuesto_de_la_ficha() -> None:
    ocds = presupuesto_de_ficha({"presupuesto": "4500.5"})
    assert ocds is not None and ocds["valor"] == 4500.5 and ocds["fuente"] == "ficha"
    nco = presupuesto_de_ficha({"cantidad": "3.00", "valor_unitario": "120.00"})
    assert nco is not None and nco["valor"] == 360.0
    # El portal de ínfimas trae 0 casi siempre: no es un presupuesto.
    assert presupuesto_de_ficha({"cantidad": "0", "valor_unitario": "0.00"}) is None
    assert presupuesto_de_ficha({}) is None


def test_el_acta_manda_y_luego_la_ficha_y_luego_el_tdr() -> None:
    tdr = {"valor": 1000.0, "fuente": "tdr"}
    ficha = {"valor": 1100.0, "fuente": "ficha"}
    acta = {"valor": 1200.0, "fuente": "acta"}
    assert elegir_presupuesto([tdr, ficha, None])["valor"] == 1100.0  # type: ignore[index]
    assert elegir_presupuesto([tdr, ficha, acta])["valor"] == 1200.0  # type: ignore[index]
    assert elegir_presupuesto([None, tdr])["valor"] == 1000.0  # type: ignore[index]
    assert elegir_presupuesto([None, {"valor": 0, "fuente": "tdr"}]) is None


def test_lo_que_manda_el_navegador_se_revisa() -> None:
    assert normalizar_presupuesto({"valor": "abc"}) is None
    assert normalizar_presupuesto({"valor": -5}) is None
    assert normalizar_presupuesto("1000") is None
    limpio = normalizar_presupuesto({"valor": "800", "fuente": "inventada", "incluye_iva": "si"})
    assert limpio == {
        "valor": 800.0,
        "fuente": "otro",
        "etiqueta_fuente": "documento del proceso",
        "incluye_iva": None,
        "cita": "",
    }


# ── Validación ──────────────────────────────────────────────────────────────────────────────────


def _cifras(lineas: list[dict[str, Any]], iva: float = 15) -> dict[str, Any]:
    return calcular_proforma(lineas, iva)


def test_supera_sin_iva_es_error() -> None:
    lineas = [{"descripcion": "Silla", "cantidad": 10, "precio_unitario": 101}]
    presupuesto = {"valor": 1000.0, "fuente": "tdr", "etiqueta_fuente": "TDR", "incluye_iva": False}
    comparacion = comparar_con_presupuesto(_cifras(lineas), lineas, presupuesto)
    assert comparacion["supera"] is True
    assert comparacion["base"] == "sin IVA"
    assert "$1.010,00" in comparacion["mensaje"] and "$1.000,00" in comparacion["mensaje"]
    with pytest.raises(DatoInvalido, match="supera el presupuesto"):
        exigir_dentro_del_presupuesto(_cifras(lineas), lineas, presupuesto)


def test_sin_dato_de_iva_se_compara_el_subtotal() -> None:
    # 1.000 sin IVA son 1.150 con IVA: con el total saltaría por el impuesto, no por el precio.
    lineas = [{"descripcion": "Silla", "cantidad": 10, "precio_unitario": 100}]
    presupuesto = {"valor": 1000.0, "fuente": "tdr", "incluye_iva": None}
    comparacion = exigir_dentro_del_presupuesto(_cifras(lineas), lineas, presupuesto)
    assert comparacion["supera"] is False and comparacion["porcentaje"] == 100.0


def test_con_iva_incluido_se_compara_el_total() -> None:
    lineas = [{"descripcion": "Silla", "cantidad": 10, "precio_unitario": 100}]
    presupuesto = {"valor": 1100.0, "fuente": "tdr", "incluye_iva": True}
    comparacion = comparar_con_presupuesto(_cifras(lineas), lineas, presupuesto)
    assert comparacion["supera"] is True and comparacion["base"] == "con IVA"
    assert comparacion["comparado"] == 1150.0


def test_muy_por_debajo_es_aviso() -> None:
    lineas = [{"descripcion": "Silla", "cantidad": 1, "precio_unitario": 400}]
    comparacion = comparar_con_presupuesto(_cifras(lineas), lineas, {"valor": 1000.0})
    assert comparacion["supera"] is False
    assert [a["codigo"] for a in comparacion["avisos"]] == ["presupuesto_bajo"]


def test_total_escrito_como_precio_unitario() -> None:
    lineas = [{"descripcion": "Silla", "cantidad": 10, "precio_unitario": 900}]
    comparacion = comparar_con_presupuesto(_cifras(lineas), lineas, {"valor": 1000.0})
    assert comparacion["supera"] is True
    assert "precio_unitario" in [a["codigo"] for a in comparacion["avisos"]]


def test_sin_presupuesto_no_salta_nada() -> None:
    lineas = [{"descripcion": "Silla", "cantidad": 10, "precio_unitario": 900}]
    assert exigir_dentro_del_presupuesto(_cifras(lineas), lineas, None)["supera"] is False


def _proforma(precio: float, presupuesto: dict[str, Any] | None) -> dict[str, Any]:
    lineas = [{"descripcion": "Silla", "cantidad": 2, "precio_unitario": precio, "unidad": "u"}]
    cifras = _cifras(lineas)
    extras: dict[str, Any] = {
        "empresa": {"razon_social": "ACME", "ruc": "1790012345001", "email": "a@b.ec"},
        "fecha": "01/01/2026",
        "codigo": "NIC-1",
        "condiciones": {"validez": "30 días", "plazo_entrega": "5 días", "forma_pago": "contado"},
    }
    if presupuesto is not None:
        extras["presupuesto"] = presupuesto
    return {
        "tipo": "proforma",
        "entidad": "GAD",
        "objeto": "Sillas",
        "lineas": cifras["lineas"],
        "cifras": cifras,
        "extras": extras,
    }


def test_la_verificacion_marca_el_exceso_como_error() -> None:
    revision = verificar_proforma(_proforma(600, {"valor": 1000, "fuente": "acta"}))
    assert "presupuesto" in [e["codigo"] for e in revision["errores"]]
    assert "acta más reciente" in next(
        e["texto"] for e in revision["errores"] if e["codigo"] == "presupuesto"
    )
    dentro = verificar_proforma(_proforma(450, {"valor": 1000, "fuente": "tdr"}))
    assert "presupuesto" not in [e["codigo"] for e in dentro["errores"]]
    assert not [a for a in dentro["avisos"] if a["codigo"] == "presupuesto_bajo"]
    corta = verificar_proforma(_proforma(100, {"valor": 1000, "fuente": "tdr"}))
    assert "presupuesto_bajo" in [a["codigo"] for a in corta["avisos"]]
    sin = verificar_proforma(_proforma(100_000, None))
    assert "presupuesto" not in [e["codigo"] for e in sin["errores"]]
