"""El lector no completa lo que el TDR no dice, y la proforma no inventa precios."""

from datetime import UTC, datetime

import pytest

from contratacion.dominio.documentos import (
    calcular_proforma,
    checklist,
    contrastar,
    es_descarga,
    extraer_secciones,
    orden_de_lectura,
    puntaje_secciones,
    resumir_ficha,
    resumir_secciones,
)
from contratacion.dominio.errores import DatoInvalido

_TDR = """
1. Objeto de contratación
Mantenimiento preventivo de impresoras del municipio.

2. Antecedentes
La unidad de tecnología no tiene personal propio.

3. Entregables
Informe mensual de intervenciones.
Repuestos instalados.

4. Plazos
Treinta días calendario.

5. Requisitos técnicos
Toner original del fabricante.
Visita quincenal.

6. Condiciones de participación
RUC activo.
"""


def test_extrae_solo_apartados_titulados() -> None:
    secciones = extraer_secciones(_TDR)
    assert "impresoras" in secciones["objeto"]
    assert "Informe mensual" in secciones["entregables"]
    assert "alcance" not in secciones
    resumen = resumir_secciones(secciones)
    assert resumen["entregar"]
    assert resumen["necesita"]
    assert "no se completa" in resumen["aviso"]


def test_el_menu_del_portal_no_cuenta_como_archivo() -> None:
    assert es_descarga("Buscador", "/ProcesoContratacion/compras/NCO/FrmNCOListado.cpe") is False
    assert es_descarga("Contacto Ciudadano", "https://sni.gob.ec/inicio") is False
    assert es_descarga("Pliego.pdf") is True
    enlace = "../GE/ExeGENBajarArchivoGeneral.cpe?Archivo=abc"
    assert es_descarga(enlace, enlace) is True


def test_el_tdr_puntua_mas_que_un_informe_con_solo_antecedentes() -> None:
    assert puntaje_secciones({"antecedentes": "texto"}) == 0
    assert puntaje_secciones({"objeto": "servicio", "plazos": "treinta dias"}) == 2


def test_el_pdf_del_tdr_se_lee_antes_que_una_imagen() -> None:
    orden = orden_de_lectura(["foto.png", "anexo.pdf", "TDR-pliego.pdf", "notas.txt"])
    assert orden[0] == "TDR-pliego.pdf"
    assert orden[1] == "anexo.pdf"
    assert orden[-1] == "foto.png"


def test_resumen_de_ficha_no_dice_que_el_tdr_no_trae_lo_que_no_publica_el_listado() -> None:
    fila = {
        "objeto": "Combustible para maquinaria",
        "fecha_publicacion": datetime(2026, 11, 9, 21, 11, tzinfo=UTC),
        "plazo": datetime(2026, 11, 10, 16, 12, tzinfo=UTC),
        "documentos": [],
        "presupuesto": None,
        "monto": None,
    }
    resumen = resumir_ficha(fila)
    assert resumen["fuente"] == "ficha"
    assert resumen["entregar"] == "" and resumen["condiciones"] == ""
    assert resumen["fechas"] == "Publicación 09/11/2026 16:11 · Límite 10/11/2026 11:12"
    assert resumen["presupuesto"] == ""


def test_checklist_sale_de_las_lineas_del_documento() -> None:
    items = checklist(extraer_secciones(_TDR))
    assert "Toner original del fabricante." in items
    assert "RUC activo." in items


_FORMULARIO = (
    "FECHA: 29 de octubre del 2026 ÁREA REQUIRENTE: Dirección de Operaciones TIPO DE PRODUCTO: "
    "Bien: ( X ) Obra: ( ) Servicios: ( ) Consultoría: ( ) NÚMERO: ATD-DO-ET-2026-009 "
    "PROCEDIMIENTO DE CONTRATACIÓN: ÍNFIMA CUANTÍA 1. R2 OBJETO DE LA CONTRATACIÓN: "
    '"ADQUISICIÓN DE MATERIALES PARA LA TOMA DE IMPRONTAS DEL CENTRO DE MATRICULACIÓN '
    'VEHÍCULAR". R3 DESCRIPCIÓN DE CPC: Código CPC.'
)


def test_checklist_no_toma_los_datos_del_formulario_como_requisitos() -> None:
    items = checklist({"requisitos_tecnicos": _FORMULARIO})
    assert not any(item.startswith(("FECHA", "ÁREA", "NÚMERO", "PROCEDIMIENTO")) for item in items)
    assert any(item.startswith("OBJETO DE LA CONTRATACIÓN:") for item in items)
    assert any(item.startswith("DESCRIPCIÓN DE CPC:") for item in items)
    assert not any(item.startswith("R2") or item.endswith(" R3") for item in items)


def test_proforma_rechaza_un_precio_vacio() -> None:
    with pytest.raises(DatoInvalido):
        calcular_proforma(
            [{"descripcion": "Toner", "cantidad": 2, "precio_unitario": None}],
            15,
        )


def test_proforma_calcula_con_el_precio_escrito() -> None:
    cifras = calcular_proforma(
        [{"descripcion": "Toner", "cantidad": 2, "precio_unitario": 10}],
        15,
    )
    assert cifras["subtotal"] == 20
    assert cifras["impuesto"] == 3
    assert cifras["total"] == 23


def test_contrastar_marca_el_entregable_que_no_esta() -> None:
    resultado = contrastar(
        ["Informe mensual de intervenciones", "Toner original"],
        [{"descripcion": "Suministro de toner original", "precio_unitario": 10}],
    )
    assert any("Toner" in texto for texto in resultado["cubiertos"])
    assert any("Informe" in texto for texto in resultado["no_cubiertos"])
