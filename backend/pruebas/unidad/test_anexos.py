"""Anexos para la proforma: TDR, pliegos y solo la última acta."""

from __future__ import annotations

from contratacion.dominio.anexos import ACTA, PLIEGO, TDR, clasificar, elegir_anexos, principal


def test_clasifica_por_nombre() -> None:
    assert clasificar("TDR_mantenimiento.pdf") == TDR
    assert clasificar("Términos de Referencia.docx") == TDR
    assert clasificar("PLIEGO-SIE-2026.pdf") == PLIEGO
    assert clasificar("Acta de preguntas y aclaraciones.pdf") == ACTA
    assert clasificar("Especificaciones técnicas.pdf") == "especificaciones"
    assert clasificar("foto.jpg") == "otro"


def test_solo_queda_la_ultima_acta_por_fecha_publicada() -> None:
    elegidos = elegir_anexos(
        [
            {"nombre": "Acta 1.pdf", "fecha": "2026-03-01T10:00:00"},
            {"nombre": "TDR.pdf"},
            {"nombre": "Acta 2.pdf", "fecha": "2026-03-10T10:00:00"},
            {"nombre": "Acta 3.pdf", "fecha": "2026-03-05T10:00:00"},
        ]
    )
    nombres = [d["nombre"] for d in elegidos]
    assert nombres == ["TDR.pdf", "Acta 2.pdf"]


def test_sin_fecha_publicada_usa_la_fecha_o_el_numero_del_nombre() -> None:
    por_fecha = elegir_anexos(
        [{"nombre": "acta_14-03-2026.pdf"}, {"nombre": "acta_02-04-2026.pdf"}]
    )
    assert [d["nombre"] for d in por_fecha] == ["acta_02-04-2026.pdf"]

    por_numero = elegir_anexos([{"nombre": "Acta 10.pdf"}, {"nombre": "Acta 9.pdf"}])
    assert [d["nombre"] for d in por_numero] == ["Acta 10.pdf"]


def test_sin_nada_mas_vale_la_ultima_publicada() -> None:
    elegidos = elegir_anexos(
        [{"nombre": "Acta.pdf", "enlace": "a"}, {"nombre": "Acta.pdf", "enlace": "b"}]
    )
    assert [d["enlace"] for d in elegidos] == ["b"]


def test_orden_y_principal() -> None:
    documentos = [
        {"nombre": "Formulario.pdf"},
        {"nombre": "Acta apertura.pdf"},
        {"nombre": "Pliego.pdf"},
        {"nombre": "TDR.pdf"},
    ]
    assert [d["tipo"] for d in elegir_anexos(documentos)] == ["tdr", "pliego", "acta", "otro"]
    assert principal(documentos)["nombre"] == "TDR.pdf"
    assert principal([{"nombre": "Pliego.pdf"}])["nombre"] == "Pliego.pdf"
    assert principal([{"nombre": "Acta.pdf"}]) is None


def test_el_acta_corrige_plazo_y_cantidad_y_se_marca() -> None:
    from contratacion.dominio.anexos import combinar_secciones, marca_de_acta

    tdr = {"tipo": TDR, "nombre": "TDR.pdf"}
    pliego = {"tipo": PLIEGO, "nombre": "Pliego.pdf"}
    acta = {"tipo": ACTA, "nombre": "Acta aclaraciones 2026-03-14.pdf"}
    secciones, cambios = combinar_secciones(
        [
            (tdr, {"objeto": "Sillas", "plazo_entrega": "30 días", "cantidad": "10"}),
            (pliego, {"objeto": "Otro objeto", "forma_pago": "Contra entrega"}),
            (acta, {"plazo_entrega": "15 días", "cantidad": "10.", "alcance": "Solo Quito"}),
        ]
    )
    assert secciones["objeto"] == "Sillas"  # el primero manda
    assert secciones["forma_pago"] == "Contra entrega"  # el pliego rellena huecos
    assert secciones["plazo_entrega"] == "Según acta del 14/03/2026: 15 días"
    assert secciones["cantidad"] == "10"  # el acta dice lo mismo: no se marca
    assert secciones["alcance"] == "Solo Quito"
    assert cambios == ["plazo_entrega"]
    assert marca_de_acta({"nombre": "Acta.pdf"}) == "Según el acta más reciente"
    assert marca_de_acta({"nombre": "Acta.pdf", "fecha": "2026-05-02T10:00"}).endswith("02/05/2026")
