"""La plantilla real del cliente (QA ciclo 3): logo, títulos combinados, cabecera en la fila 4
y tres hojas ÍNFIMAS / OFERTAS / PARTICIPACION.

Lo que se reprodujo: la plantilla se aceptaba al subirla, pero la exportación moría con
«'MergedCell' object attribute 'value' is read-only» en cuanto la hoja traía alguna celda combinada
debajo de los títulos (una fila de ejemplo, un pie), y una «Tabla» de Excel se quedaba con su
rango original. Estas pruebas fijan el comportamiento: se sube, se rellena debajo de la cabecera y
el diseño —logo y títulos combinados— se conserva.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Any

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.drawing.image import Image
from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.table import Table

from contratacion.aplicacion.casos_uso.analizar_plantilla import analizar
from contratacion.aplicacion.casos_uso.exportar_registros import construir_libro
from contratacion.aplicacion.plantillas import revisar_plantilla
from contratacion.dominio.busqueda import Categoria, Filtros

PIL = pytest.importorskip("PIL.Image")

CABECERA = (
    "Tipo de compra",
    "Código",
    "Fecha de publicación",
    "Provincia",
    "Cantón",
    "Objeto de compra",
    "Límite de proformas",
    "Razón social",
    "Días para proforma",
)
AHORA = datetime(2026, 11, 18, 15, 0, tzinfo=UTC)


def _plantilla(*, combinadas_en_datos: bool = False, con_tabla: bool = False) -> bytes:
    libro = Workbook()
    libro.active.title = "ÍNFIMAS"
    libro.create_sheet("OFERTAS")
    libro.create_sheet("PARTICIPACION")
    for hoja in libro.worksheets:
        for fila, texto in enumerate(
            (
                "PUBLICACIONES 2026",
                "NECESIDADES DE CONTRATACIÓN Y RECEPCIÓN DE PROFORMAS",
                "Ínfimas Cuantías",
            ),
            start=1,
        ):
            hoja.cell(fila, 2, texto).font = Font(bold=True, size=14)
            hoja.merge_cells(start_row=fila, start_column=2, end_row=fila, end_column=9)
        for columna, titulo in enumerate(CABECERA, start=1):
            celda = hoja.cell(4, columna, titulo)
            celda.fill = PatternFill("solid", start_color="0B2E4F")
        logo = io.BytesIO()
        PIL.new("RGB", (120, 60), (11, 46, 79)).save(logo, "PNG")
        logo.seek(0)
        hoja.add_image(Image(logo), "A1")
    if combinadas_en_datos:
        libro["ÍNFIMAS"].merge_cells("A6:B6")
        libro["ÍNFIMAS"].merge_cells("F8:F10")
    if con_tabla:
        libro["ÍNFIMAS"].add_table(Table(displayName="Infimas", ref="A4:I10"))
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()


def _filas(cantidad: int) -> list[dict[str, Any]]:
    return [
        {
            "fuente": "NCO",
            "codigo": f"NIC-1790000000001-2026-{numero:05d}",
            "tipo_necesidad": "Ínfimas Cuantías",
            "entidad": "GAD MUNICIPAL",
            "objeto_compra": "Mantenimiento preventivo",
            "provincia": "PICHINCHA",
            "canton": "QUITO",
            "fecha_publicacion": datetime(2026, 11, 1, tzinfo=UTC),
            "fecha_limite_proformas": "2026-11-25 10:00:00",
            "items": [],
        }
        for numero in range(cantidad)
    ]


def _exportar(plantilla: bytes, cantidad: int = 30) -> Any:
    contenido = construir_libro(
        _filas(cantidad),
        filtros=Filtros(categoria=Categoria.INFIMAS, fuentes_permitidas=("NCO",)),
        generado_en=AHORA,
        plantilla=plantilla,
    )
    return load_workbook(io.BytesIO(contenido))


def test_la_plantilla_del_cliente_se_acepta_al_subirla() -> None:
    revisar_plantilla("PLANTILLA ÍNFIMAS 2026.xlsx", _plantilla())


def test_el_analisis_encuentra_la_cabecera_en_la_fila_cuatro() -> None:
    informe = analizar(_plantilla()).como_diccionario()
    hoja = next(h for h in informe["hojas"] if h["hoja"] == "ÍNFIMAS")
    assert hoja["fila_de_encabezado"] == 4
    assert hoja["primera_fila_de_datos"] == 5
    assert len(hoja["columnas_reconocidas"]) == len(CABECERA)


def test_los_datos_van_debajo_de_la_cabecera_y_el_diseno_se_conserva() -> None:
    libro = _exportar(_plantilla())
    hoja = libro["ÍNFIMAS"]

    assert hoja["B1"].value == "PUBLICACIONES 2026"
    assert "B1:I1" in {str(rango) for rango in hoja.merged_cells.ranges}
    assert len(hoja._images) == 1  # el logo sigue ahí
    assert [c.value for c in hoja[4]] == list(CABECERA)
    assert hoja["B5"].value == "NIC-1790000000001-2026-00000"
    assert hoja["B34"].value == "NIC-1790000000001-2026-00029"
    assert hoja["I5"].value  # días para proforma
    assert libro.sheetnames == ["ÍNFIMAS", "OFERTAS", "PARTICIPACION"]


def test_celdas_combinadas_debajo_de_la_cabecera_no_rompen_la_exportacion() -> None:
    hoja = _exportar(_plantilla(combinadas_en_datos=True))["ÍNFIMAS"]

    assert hoja["B6"].value == "NIC-1790000000001-2026-00001"
    assert hoja["F9"].value == "Mantenimiento preventivo"
    # Los títulos combinados de arriba siguen combinados.
    assert "B2:I2" in {str(rango) for rango in hoja.merged_cells.ranges}


def test_la_tabla_de_excel_se_estira_hasta_la_ultima_fila() -> None:
    hoja = _exportar(_plantilla(con_tabla=True))["ÍNFIMAS"]
    assert hoja.tables["Infimas"].ref == "A4:I34"
