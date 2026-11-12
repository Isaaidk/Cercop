"""El texto del TDR que ve el cliente sale limpio, sin perder montos, plazos ni nombres.

Los ejemplos son reales: así llegaban los apartados antes de la limpieza.
"""

from contratacion.dominio.documentos import (
    POR_COMPLETAR,
    checklist,
    cortar,
    extraer_secciones,
    limpiar_texto,
    resumir_secciones,
)


def test_los_huecos_del_formulario_quedan_como_un_solo_marcador() -> None:
    texto = limpiar_texto("ACEPTACIÓN: ……………………... con RUC …………………. : certifica que acepta")
    assert texto == f"ACEPTACIÓN: {POR_COMPLETAR} con RUC {POR_COMPLETAR}: certifica que acepta"


def test_el_monto_en_blanco_no_se_confunde_con_un_monto_real() -> None:
    texto = limpiar_texto(
        "el valor es de $............ (………. CON 00/100 DOLARES) y $1.250,50 total"
    )
    assert texto == (
        f"el valor es de ${POR_COMPLETAR} ({POR_COMPLETAR} CON 00/100 DOLARES) y $1.250,50 total"
    )


def test_huecos_seguidos_no_repiten_el_marcador() -> None:
    assert limpiar_texto("Firma: ____ …… ____") == f"Firma: {POR_COMPLETAR}"


def test_una_elipsis_de_verdad_se_respeta() -> None:
    assert limpiar_texto("toner, papel, etc... según el anexo") == (
        "toner, papel, etc... según el anexo"
    )


def test_el_encabezado_de_la_tabla_pegado_se_resume_y_se_unen_las_letras() -> None:
    texto = limpiar_texto(
        "VIGENCIA: I T E M CPC DESCRIPCIÓN UNIDAD DE MEDIDA CANTIDAD V.UNITARIO V.TOTAL "
        "SUBTOTAL IVA 15% TOTAL ADMINISTRADOR DEL CONTRATO: Ing. Pérez"
    )
    assert "I T E M" not in texto
    assert texto.startswith("VIGENCIA: [tabla de ítems")
    assert texto.endswith("ADMINISTRADOR DEL CONTRATO: Ing. Pérez")


def test_letras_espaciadas_se_unen() -> None:
    assert limpiar_texto("T É R M I N O S de referencia") == "TÉRMINOS de referencia"


def test_palabra_partida_se_une_solo_si_la_mitad_no_puede_ser_palabra() -> None:
    assert limpiar_texto("en el mi smo lugar") == "en el mismo lugar"
    # «software», «smart» o «la gran» son palabras: no se tocan.
    assert limpiar_texto("de software tipo smart y la gran obra") == (
        "de software tipo smart y la gran obra"
    )


def test_cada_vineta_en_su_linea_sin_romper_un_guion_normal() -> None:
    texto = limpiar_texto(
        "Requisitos: - La garantía técnica de un año. - El soporte en sitio (de ser el caso). "
        "Entrega en Quito - Ecuador"
    )
    assert texto.split("\n") == [
        "Requisitos:",
        "- La garantía técnica de un año.",
        "- El soporte en sitio (de ser el caso). Entrega en Quito - Ecuador",
    ]
    assert limpiar_texto("Entrega • Bodega central • Horario") == (
        "Entrega\n• Bodega central\n• Horario"
    )


def test_corta_en_el_fin_de_frase_y_no_a_media_palabra() -> None:
    texto = "Primera frase completa. " * 10 + "Segunda parte que se corta so"
    corto = cortar(texto, 120)
    assert len(corto) <= 120
    assert corto.endswith("completa…")
    assert not corto.endswith("so")
    sin_puntos = cortar("palabra " * 40, 50)
    assert sin_puntos.endswith("palabra…")


def test_limpiar_dos_veces_no_cambia_nada() -> None:
    for original in (
        "ACEPTACIÓN: …………… con RUC ……. :",
        "Requisitos: - La garantía. - El soporte.",
        "Texto largo. " * 300,
    ):
        una = limpiar_texto(original, 600)
        assert limpiar_texto(una, 600) == una


def test_los_apartados_extraidos_salen_limpios() -> None:
    tdr = (
        "FORMA DE PAGO: contra entrega, el valor de $........ se paga en 30 días "
        "LUGAR DE ENTREGA: Bodega del mi smo edificio"
    )
    secciones = extraer_secciones(tdr)
    assert (
        secciones["forma_pago"]
        == f"contra entrega, el valor de ${POR_COMPLETAR} se paga en 30 días"
    )
    assert secciones["lugar_entrega"] == "Bodega del mismo edificio"
    assert resumir_secciones(secciones)["pago"] == secciones["forma_pago"]


def test_un_campo_que_es_solo_un_hueco_no_se_guarda() -> None:
    assert "garantia" not in extraer_secciones("GARANTÍA: ………………… PLAZO DE ENTREGA: 15 días")


def test_las_lecturas_viejas_se_limpian_al_resumir() -> None:
    resumen = resumir_secciones({"objeto": "Compra de ……………… para el mi smo edificio"})
    assert resumen["necesita"] == f"Compra de {POR_COMPLETAR} para el mismo edificio"


def test_checklist_une_el_parentesis_suelto_y_quita_la_vineta() -> None:
    items = checklist(
        {"requisitos_tecnicos": "- La garantía técnica de un año. (de ser el caso). - RUC activo."}
    )
    assert "La garantía técnica de un año. (de ser el caso)." in items
    assert "RUC activo." in items
    assert not any(item.startswith("(") or item.startswith("-") for item in items)
