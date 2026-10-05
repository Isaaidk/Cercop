"""Pruebas del CPC: cómo se lee la ficha de una necesidad y cómo se convierte en búsqueda.

Lo que se protege aquí es una decisión de negocio: buscar por CPC tiene que encontrar **solo** lo
que está clasificado así. Si el texto de búsqueda acabara incluyendo la descripción libre del
producto —«Lavado, engrasado y pulverizado de la Volqueta 5 kodiak chevrolet»—, el filtro volvería a
traer todo lo que menciona la palabra, que es exactamente el problema que el CPC viene a resolver.
Por eso hay una prueba que lo comprueba de forma explícita y no solo de pasada.

El otro grupo son los casos que el portal publica de verdad y que un analizador ingenuo rompería: la
ficha lleva más de una tabla, una celda puede contener su propia tabla, hay entidades HTML
(`&oacute;`) y saltos dentro de la descripción, y hay necesidades **sin** tabla de detalle.
"""

from __future__ import annotations

from contratacion.dominio.cpc import (
    ItemCpc,
    codigos_de,
    items_desde_crudos,
    resumen_cpc,
    texto_de_cpc,
)
from contratacion.infraestructura.adaptadores.salida.fuentes.nco_detalle import (
    parsear_items,
    token_de_enlace,
)

# Recorte fiel de una ficha real: primero una tabla que **no** es la del detalle, y después la
# buena. Va así a propósito: si el analizador se quedara con la primera tabla, esta prueba fallaría
# en lugar de pasar por casualidad.
FICHA = """
<div class="row"><table class="table"><tr><td>Documento</td><td>Pliego.pdf</td></tr></table></div>
<div class="row">
<h2 class="importante">Detalle del objeto de compra</h2>
<table class="table table-striped mt-4">
<thead>
<tr>
<th>No.</th><th colspan="2" style="text-align: center;">CPC</th>
    <th>Descripci&oacute;n del Producto</th>
    <th>Unidad</th>
    <th>Cantidad</th></tr>
    </thead>
    <tbody><tr>
        <td>1</td><td>871410032</td><td>LAVADO Y ENGRASADO DE AUTOMOTORES</td>
        <td class="multiline-text">Lavado, engrasado y pulverizado de la
Volqueta 5 kodiak chevrolet</td><td>Unidad</td>
        <td>6.00</td></tr><tr>
        <td>2</td><td>871410032</td><td>LAVADO Y ENGRASADO DE AUTOMOTORES</td>
        <td class="multiline-text">Lavado<br/>del TRACTO CAMI&Oacute;N</td><td>Unidad</td>
        <td>6.00</td></tr>
        </tbody>
        </table>
        </div>
"""


def _con_celda_anidada() -> str:
    """Ficha en la que la descripción de un ítem trae una tabla dentro de la celda.

    Es el caso que rompe un analizador que cuente `tr` sin mirar la profundidad: las filas de la
    tabla interna se colarían como ítems.
    """
    return """
<table>
<tr>
  <th>No.</th><th>CPC</th><th>Descripci&oacute;n del Producto</th>
  <th>Unidad</th><th>Cantidad</th></tr>
<tr><td>1</td><td>871410032</td><td>LAVADO Y ENGRASADO</td>
    <td>Servicio <table><tr><td>tabla interna</td></tr></table> de lavado</td>
    <td>Unidad</td><td>2.00</td></tr>
</table>
"""


# --------------------------------------------------------------------------- #
# Lectura de la tabla
# --------------------------------------------------------------------------- #


def test_lee_los_items_de_la_ficha() -> None:
    items = parsear_items(FICHA)
    assert len(items) == 2
    assert items[0] == ItemCpc(
        numero=1,
        codigo="871410032",
        descripcion_cpc="LAVADO Y ENGRASADO DE AUTOMOTORES",
        descripcion="Lavado, engrasado y pulverizado de la Volqueta 5 kodiak chevrolet",
        unidad="Unidad",
        cantidad="6.00",
    )


def test_elige_la_tabla_del_cpc_y_no_la_primera() -> None:
    """La ficha lleva varias tablas; la del detalle se reconoce por su encabezado."""
    items = parsear_items(FICHA)
    assert [item.codigo for item in items] == ["871410032", "871410032"]


def test_une_los_trozos_de_una_descripcion_partida() -> None:
    """La descripción llega con saltos de línea y con `<br/>` dentro de la celda."""
    segundo = parsear_items(FICHA)[1]
    assert segundo.descripcion == "Lavado del TRACTO CAMIÓN"


def test_ignora_las_filas_de_una_tabla_anidada() -> None:
    assert len(parsear_items(_con_celda_anidada())) == 1


def test_una_ficha_sin_tabla_no_da_items() -> None:
    """Hay necesidades publicadas sin detalle, y eso no puede impedir guardar la necesidad."""
    assert parsear_items("<html><body><p>Sin detalle</p></body></html>") == ()


def test_una_fila_incompleta_se_descarta_sin_arrastrar_las_demas() -> None:
    ficha = """
    <table>
    <tr><th>No.</th><th>CPC</th><th>Descripci&oacute;n</th><th>Unidad</th><th>Cantidad</th></tr>
    <tr><td>1</td><td>871410032</td><td>LAVADO</td><td>Descripcion</td><td>Unidad</td><td>1.00</td></tr>
    <tr><td>&nbsp;</td><td></td><td></td><td></td><td></td><td></td></tr>
    <tr><td>3</td><td>4911400111</td><td>PARTES</td><td>Otra</td><td>Unidad</td><td>2.00</td></tr>
    </table>
    """
    items = parsear_items(ficha)
    assert [item.codigo for item in items] == ["871410032", "4911400111"]


def test_lee_los_codigos_de_mas_de_nueve_digitos() -> None:
    """El portal publica códigos de 9 y de 10 dígitos; no se puede exigir una longitud fija."""
    ficha = """
    <table>
    <tr><th>No.</th><th>CPC</th><th>Descripci&oacute;n</th><th>Unidad</th><th>Cantidad</th></tr>
    <tr><td>1</td><td>4911400111</td><td>PARTES DE CAMIONES</td><td>Repuesto</td><td>Unidad</td>
        <td>1.00</td></tr>
    </table>
    """
    assert parsear_items(ficha)[0].codigo == "4911400111"


# --------------------------------------------------------------------------- #
# El identificador de la ficha
# --------------------------------------------------------------------------- #


def test_extrae_el_token_del_enlace_del_listado() -> None:
    """El enlace viene sin comillas, con una coma antes de `&op` y con un punto relativo delante."""
    enlace = "../NCO/NCORegistroDetalle.cpe?&id=grSiD1LzX7qbCiF0Da6Z_BZCRcgaOiJ_GV6fvExzmPI,&op=0"
    assert token_de_enlace(enlace) == "grSiD1LzX7qbCiF0Da6Z_BZCRcgaOiJ_GV6fvExzmPI"


def test_un_enlace_sin_token_no_inventa_uno() -> None:
    assert token_de_enlace(None) is None
    assert token_de_enlace("") is None
    assert token_de_enlace("../NCO/NCORegistroDetalle.cpe?&op=0") is None


# --------------------------------------------------------------------------- #
# El texto de búsqueda
# --------------------------------------------------------------------------- #


def test_el_texto_de_busqueda_lleva_codigo_y_nombre_del_cpc() -> None:
    items = (ItemCpc(codigo="871410032", descripcion_cpc="LAVADO Y ENGRASADO DE AUTOMOTORES"),)
    assert texto_de_cpc(items) == "871410032 lavado y engrasado de automotores"


def test_el_texto_de_busqueda_deja_fuera_la_descripcion_libre() -> None:
    """Es la razón de ser del filtro: la parte libre es la que trae el ruido."""
    items = (
        ItemCpc(
            codigo="929000014",
            descripcion_cpc="SERVICIOS DE CAPACITACION EN TEMAS ADMINISTRATIVOS",
            descripcion="TEMA: Prevención de lavado de activos y financiamiento del terrorismo",
        ),
    )
    texto = texto_de_cpc(items)
    assert "capacitacion" in texto
    assert "lavado" not in texto
    assert "terrorismo" not in texto


def test_el_texto_de_busqueda_no_repite_el_mismo_cpc() -> None:
    """Diecisiete líneas del mismo servicio son un CPC, no diecisiete."""
    items = tuple(
        ItemCpc(codigo="871410032", descripcion_cpc="LAVADO Y ENGRASADO DE AUTOMOTORES")
        for _ in range(17)
    )
    assert texto_de_cpc(items) == "871410032 lavado y engrasado de automotores"


def test_los_codigos_van_ordenados_y_sin_repetir() -> None:
    items = (
        ItemCpc(codigo="871410018", descripcion_cpc="UNO"),
        ItemCpc(codigo="431510128", descripcion_cpc="DOS"),
        ItemCpc(codigo="871410018", descripcion_cpc="UNO"),
        ItemCpc(codigo="", descripcion_cpc="sin codigo"),
    )
    assert codigos_de(items) == ["431510128", "871410018"]


def test_el_resumen_muestra_cada_cpc_una_vez() -> None:
    items = (
        ItemCpc(codigo="871410032", descripcion_cpc="LAVADO Y ENGRASADO DE AUTOMOTORES"),
        ItemCpc(codigo="871410032", descripcion_cpc="LAVADO Y ENGRASADO DE AUTOMOTORES"),
        ItemCpc(codigo="431510128", descripcion_cpc="REPUESTOS PARA MOTOR DIESEL"),
    )
    assert resumen_cpc(items) == (
        "871410032 LAVADO Y ENGRASADO DE AUTOMOTORES | 431510128 REPUESTOS PARA MOTOR DIESEL"
    )


def test_sin_items_no_hay_texto_ni_resumen() -> None:
    assert texto_de_cpc(()) == ""
    assert resumen_cpc(()) == ""
    assert codigos_de(()) == []


# --------------------------------------------------------------------------- #
# Lectura de lo ya guardado
# --------------------------------------------------------------------------- #


def test_reconstruye_los_items_guardados() -> None:
    guardados = [
        {"numero": 1, "codigo": "871410032", "descripcion_cpc": "LAVADO", "cantidad": "6.00"}
    ]
    items = items_desde_crudos(guardados)
    assert items == (
        ItemCpc(numero=1, codigo="871410032", descripcion_cpc="LAVADO", cantidad="6.00"),
    )


def test_descarta_lo_guardado_que_no_tiene_codigo() -> None:
    """Un ítem ilegible no puede impedir devolver la fila entera."""
    items = items_desde_crudos([{"codigo": "   "}, {"sin": "codigo"}, "no soy un objeto"])
    assert items == ()
