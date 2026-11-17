"""Texto UTF-8 que el portal entrega leído como Latin-1/Windows-1252."""

from __future__ import annotations

from contratacion.dominio.cpc import items_desde_crudos
from contratacion.dominio.texto import reparar_codificacion


def test_repara_el_texto_doblemente_codificado() -> None:
    assert reparar_codificacion("CONTRATACIÃ\x93N LOGÃ\x8dSTICA") == "CONTRATACIÓN LOGÍSTICA"
    assert reparar_codificacion("CONTRATACIÃ“N") == "CONTRATACIÓN"
    assert reparar_codificacion("â\x80\x9cEXPOFERIAâ\x80\x9d") == "“EXPOFERIA”"


def test_no_toca_el_texto_sano() -> None:
    for sano in ("", "niño acción ÁÉÍÓÚ ñ", "Señal: 50 °C · 3/4", "CPC 962900116"):
        assert reparar_codificacion(sano) == sano


def test_los_items_guardados_salen_reparados() -> None:
    (item,) = items_desde_crudos([{"codigo": "962900116", "descripcion": "DÃ\x8dA DEL ARTESANO"}])
    assert item.descripcion == "DÍA DEL ARTESANO"
