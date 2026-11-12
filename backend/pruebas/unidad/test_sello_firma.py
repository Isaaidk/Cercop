"""El sello de la firma copia el de FirmaEC: QR con su formato y nombre en Courier negrita."""

from __future__ import annotations

from datetime import UTC, datetime

from pypdf import PdfReader

from contratacion.infraestructura.adaptadores.salida.firma import sello_firmaec, texto_qr


def test_el_qr_lleva_el_formato_de_firmaec() -> None:
    texto = texto_qr(
        "HECTOR PAUL ULLOA SANDOVAL",
        "Proforma",
        "Quito",
        datetime(2026, 9, 21, 13, 33, 49, tzinfo=UTC),
    )
    lineas = texto.split("\n")
    assert lineas[0] == "FIRMADO POR: HECTOR PAUL ULLOA SANDOVAL"
    assert lineas[1] == "RAZON: Proforma"
    assert lineas[2] == "LOCALIZACION: Quito"
    assert lineas[3] == "FECHA: 2026-09-21T08:33:49.000-05:00"
    assert lineas[4] == "VALIDAR CON: www.firmadigital.gob.ec"
    # No dice que se firmó con FirmaEC: sería falso.
    assert "FirmaEC" not in lineas[5]


def test_el_sello_es_una_pagina_con_el_texto_de_firmaec() -> None:
    import io

    pdf = sello_firmaec("HECTOR PAUL ULLOA SANDOVAL", "FIRMADO POR: X")
    texto = PdfReader(io.BytesIO(pdf)).pages[0].extract_text()
    assert "Validar únicamente en FirmaEC." in texto
    assert "Firmado electrónicamente por:" in texto
    assert "HECTOR PAUL ULLOA" in texto and "SANDOVAL" in texto


def test_un_nombre_largo_no_se_sale_del_sello() -> None:
    pdf = sello_firmaec("MARIA DE LOS ANGELES FERNANDEZ DE CORDOVA Y ALVARADO", "x")
    assert PdfReader(__import__("io").BytesIO(pdf)).pages[0].extract_text()
