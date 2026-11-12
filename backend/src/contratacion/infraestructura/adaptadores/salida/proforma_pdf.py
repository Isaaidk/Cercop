"""PDF de la proforma, la cotización y la ficha técnica con el formato que piden las entidades.

Los datos mínimos salen de las formalidades que publica la entidad en el portal: destinatario con
RUC y dirección, objeto, detalle con cantidades y precios, subtotal, IVA y total, fecha de emisión,
vigencia, forma de pago, plazo, lugar de entrega, teléfono, dirección y correo del oferente, y el
bloque de firma. El uso de firma electrónica es discrecional (art. 47 del RGLOSNCP) y el recuadro de
abajo queda libre para el sello.

La ficha técnica lleva la identificación del bien (marca, modelo, país de origen, año) y la matriz
«requerido por la entidad / ofertado»: omitir una especificación es causal de rechazo.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, cast

from fpdf import FPDF

_AZUL = (37, 99, 235)
_AZUL_OSCURO = (30, 58, 138)
_TINTA = (19, 28, 51)
_GRIS = (71, 85, 105)
_LINEA = (203, 213, 225)
_FILA = (241, 245, 249)
_AMBAR = (180, 83, 9)

_ANCHO = 190.0
_ALTO_RENGLON = 4.4
_PUNTOS_POR_MM = 72 / 25.4
_ALTO_PAGINA = 297.0

# Recuadro de firma de la página: página (desde 0) y rectángulo en puntos PDF, origen abajo a la
# izquierda. La firma electrónica estampa su sello exactamente ahí.
Caja = tuple[int, tuple[float, float, float, float]]


def _caja(pagina: int, x: float, y: float, ancho: float, alto: float) -> Caja:
    """Pasa un rectángulo en milímetros (origen arriba a la izquierda) a puntos PDF."""
    k = _PUNTOS_POR_MM
    return pagina - 1, (
        round(x * k, 1),
        round((_ALTO_PAGINA - y - alto) * k, 1),
        round((x + ancho) * k, 1),
        round((_ALTO_PAGINA - y) * k, 1),
    )


_TIPOS = {
    "proforma": (
        "PROFORMA",
        "Documento con los efectos de oferta, conforme la normativa de ínfima cuantía del SERCOP",
        "esta proforma",
    ),
    "cotizacion": (
        "COTIZACIÓN",
        "Cotización para el estudio de mercado y la determinación del presupuesto referencial "
        "de la entidad, conforme la normativa del SERCOP",
        "esta cotización",
    ),
}


# Helvetica solo trae Latin-1. Las comillas y rayas tipográficas que vienen del TDR se cambian por
# su equivalente, y lo que no tenga equivalente se omite: un carácter suelto no puede tumbar el PDF.
_LATIN = str.maketrans(
    {
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u00ab": '"',
        "\u00bb": '"',
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u2013": "-",
        "\u2014": "-",
        "\u2015": "-",
        "\u2026": "...",
        "\u2022": "-",
        "\u00a0": " ",
        "\u202f": " ",
    }
)


def _renglones(pdf: FPDF, ancho: float, alto: float, texto: str) -> list[str]:
    """Los renglones en que se partiría el texto, sin dibujarlo (fpdf2 tipa un retorno ambiguo)."""
    return cast("list[str]", pdf.multi_cell(ancho, alto, texto, dry_run=True, output="LINES"))


def _imprimible(valor: Any) -> Any:
    if isinstance(valor, str):
        return valor.translate(_LATIN).encode("latin-1", "ignore").decode("latin-1")
    if isinstance(valor, dict):
        return {clave: _imprimible(item) for clave, item in valor.items()}
    if isinstance(valor, list):
        return [_imprimible(item) for item in valor]
    return valor


def _dinero(valor: Any) -> str:
    try:
        return f"$ {float(valor):,.2f}"
    except (TypeError, ValueError):
        return str(valor or "")


def _cantidad(valor: Any) -> str:
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return str(valor or "")
    return str(int(numero)) if numero.is_integer() else f"{numero:g}"


class _Documento(FPDF):
    def __init__(self, empresa: str, ruc: str, tipo: str) -> None:
        super().__init__(format="A4")
        self._empresa = empresa
        self._ruc = ruc
        self._tipo = tipo
        self.cajas: list[Caja] = []
        self.set_auto_page_break(auto=True, margin=22)
        self.set_margins(10, 16, 10)

    def header(self) -> None:
        if self.page_no() == 1:
            return
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(*_GRIS)
        self.cell(_ANCHO, 6, f"{self._empresa}  ·  {self._tipo}", align="L")
        self.ln(8)

    def footer(self) -> None:
        self.set_y(-14)
        self.set_draw_color(*_LINEA)
        self.line(10, self.get_y(), 200, self.get_y())
        self.set_font("Helvetica", "", 7.5)
        self.set_text_color(*_GRIS)
        ruc = f"  ·  RUC {self._ruc}" if self._ruc else ""
        self.cell(140, 6, f"{self._empresa}{ruc}")
        self.cell(50, 6, f"Página {self.page_no()} de {{nb}}", align="R")


def _parrafo(pdf: _Documento, texto: str, alto: float = 5, despues: float = 2) -> None:
    pdf.set_x(10)
    pdf.multi_cell(_ANCHO, alto, texto)
    pdf.ln(despues)


def _titulo_seccion(pdf: _Documento, texto: str) -> None:
    if pdf.get_y() > 258:
        pdf.add_page()
    pdf.ln(4)
    y = pdf.get_y()
    pdf.set_fill_color(*_AZUL_OSCURO)
    pdf.rect(10, y + 0.4, 1.8, 5.4, "F")
    pdf.set_xy(14, y)
    pdf.set_text_color(*_TINTA)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(_ANCHO - 4, 6, texto, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1.5)


def _fila_dato(pdf: _Documento, pares: list[tuple[str, str]], sombreada: bool) -> None:
    presentes = [(etiqueta, valor) for etiqueta, valor in pares if valor]
    if not presentes:
        return
    pdf.set_font("Helvetica", "", 9)
    # Dos datos por fila solo si los dos caben. Si uno es largo, va solo en su fila.
    caben_juntos = len(presentes) == 2 and all(
        pdf.get_string_width(valor) < _ANCHO / 2 - 46 for _, valor in presentes
    )
    grupos = [presentes] if caben_juntos else [[par] for par in presentes]
    for grupo in grupos:
        ancho = _ANCHO / len(grupo)
        renglones = [_renglones(pdf, ancho - 46, _ALTO_RENGLON, valor) for _, valor in grupo]
        alto = max(_ALTO_RENGLON * len(lineas) + 1.6 for lineas in renglones)
        if pdf.get_y() + alto > 280:
            pdf.add_page()
        y = pdf.get_y()
        pdf.set_fill_color(*(_FILA if sombreada else (255, 255, 255)))
        pdf.rect(10, y, _ANCHO, alto, "F")
        for indice, (etiqueta, valor) in enumerate(grupo):
            pdf.set_xy(10 + indice * ancho, y + 0.8)
            pdf.set_font("Helvetica", "B", 8)
            pdf.set_text_color(*_GRIS)
            pdf.cell(44, _ALTO_RENGLON, etiqueta)
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*_TINTA)
            pdf.multi_cell(ancho - 46, _ALTO_RENGLON, valor)
        pdf.set_y(y + alto)


def _bloque(pdf: _Documento, filas: list[list[tuple[str, str]]]) -> None:
    filas = [fila for fila in filas if any(valor for _, valor in fila)]
    if not filas:
        return
    pdf.set_draw_color(*_LINEA)
    for indice, pares in enumerate(filas):
        _fila_dato(pdf, pares, indice % 2 == 0)
    pdf.set_x(10)
    pdf.cell(_ANCHO, 0, border="T")
    pdf.ln(2)


def _viñetas(pdf: _Documento, filas: list[str]) -> None:
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*_TINTA)
    for fila in filas:
        pdf.set_x(12)
        pdf.multi_cell(_ANCHO - 2, 4.6, f"-  {fila}")
        pdf.ln(0.6)


_ALTO_FIRMA = 20.0


def _recuadro_firma(
    pdf: _Documento, x: float, y: float, ancho: float, alto: float, firmante: str
) -> None:
    """Recuadro para firmar dentro de la celda, con el nombre del firmante en la parte de abajo."""
    pdf.set_draw_color(*_LINEA)
    pdf.set_line_width(0.2)
    pdf.rect(x + 1.5, y + 1.2, ancho - 3, alto - 8.5, "D")
    pdf.cajas.append(_caja(pdf.page_no(), x + 1.5, y + 1.2, ancho - 3, alto - 8.5))
    pdf.set_xy(x + 1, y + alto - 7)
    pdf.set_font("Helvetica", "", 6)
    pdf.set_text_color(*_GRIS)
    pdf.multi_cell(ancho - 2, 2.8, firmante, align="C")
    pdf.set_text_color(*_TINTA)


def _cabecera_tabla(pdf: _Documento, anchos: tuple[float, ...], cabeceras: tuple[str, ...]) -> None:
    pdf.set_fill_color(*_AZUL_OSCURO)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_x(10)
    for ancho, texto in zip(anchos, cabeceras, strict=True):
        pdf.cell(ancho, 6.5, texto, align="C", fill=True)
    pdf.ln()


def _tabla(
    pdf: _Documento,
    anchos: tuple[float, ...],
    cabeceras: tuple[str, ...],
    filas: Sequence[tuple[str, ...]],
    *,
    alinear: tuple[str, ...],
    negrita: tuple[int, ...] = (),
    firma: str | None = None,
) -> None:
    """Tabla con celdas que crecen hacia abajo. Al cambiar de página repite la cabecera.

    Con `firma`, la última columna es un recuadro de firma por fila, con el nombre del firmante
    debajo. Cada requisito queda firmado a la par de su respuesta.
    """
    _cabecera_tabla(pdf, anchos, cabeceras)
    ultima = len(anchos) - 1
    for numero, celdas in enumerate(filas, start=1):
        pdf.set_font("Helvetica", "", 8.5)
        alto = 6.0
        for indice, (ancho, texto) in enumerate(zip(anchos, celdas, strict=True)):
            if firma and indice == ultima:
                continue
            pdf.set_font("Helvetica", "B" if indice in negrita else "", 8.5)
            renglones = _renglones(pdf, ancho - 2, _ALTO_RENGLON, texto)
            alto = max(alto, _ALTO_RENGLON * len(renglones) + 1.6)
        if firma:
            alto = max(alto, _ALTO_FIRMA)
        if pdf.get_y() + alto > 275:
            pdf.add_page()
            _cabecera_tabla(pdf, anchos, cabeceras)
        y = pdf.get_y()
        if numero % 2 == 0:
            pdf.set_fill_color(*_FILA)
            pdf.rect(10, y, _ANCHO, alto, "F")
        x = 10.0
        for indice, (ancho, texto) in enumerate(zip(anchos, celdas, strict=True)):
            if firma and indice == ultima:
                _recuadro_firma(pdf, x, y, ancho, alto, firma)
                x += ancho
                continue
            pdf.set_font("Helvetica", "B" if indice in negrita else "", 8.5)
            pdf.set_text_color(*_TINTA)
            pdf.set_xy(x + 1, y + 0.8)
            pdf.multi_cell(ancho - 2, _ALTO_RENGLON, texto, align=alinear[indice])
            x += ancho
        pdf.set_y(y + alto)
    pdf.set_draw_color(*_LINEA)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.set_text_color(*_TINTA)


def _membrete(pdf: _Documento, nombre: str, empresa: dict[str, Any]) -> None:
    pdf.set_fill_color(*_AZUL_OSCURO)
    pdf.rect(0, 0, 210, 34, "F")
    pdf.set_xy(10, 6)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(_ANCHO, 7, nombre.upper(), new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(10)
    pdf.set_font("Helvetica", "", 9)
    subtitulo = "  ·  ".join(
        parte
        for parte in (
            f"RUC {empresa['ruc']}" if empresa.get("ruc") else "",
            empresa.get("nombre_comercial") or "",
        )
        if parte
    )
    if subtitulo:
        pdf.cell(_ANCHO, 5, subtitulo, new_x="LMARGIN", new_y="NEXT")
        pdf.set_x(10)
    contacto = "  ·  ".join(
        str(empresa[clave])
        for clave in ("direccion", "ciudad", "telefono", "email")
        if empresa.get(clave)
    )
    if contacto:
        pdf.set_font("Helvetica", "", 8)
        pdf.multi_cell(_ANCHO, 4, contacto)
    pdf.set_y(40)


def _titulo_documento(pdf: _Documento, titulo: str, subtitulo: str) -> None:
    pdf.set_text_color(*_AZUL_OSCURO)
    # Un título propio puede ser largo («PROFORMA — ADQUISICIÓN DE … · NIC-…»): va en renglones.
    pdf.set_font("Helvetica", "B", 16 if len(titulo) <= 40 else 12)
    pdf.set_x(10)
    pdf.multi_cell(_ANCHO, 7 if len(titulo) <= 40 else 5.6, titulo, align="C")
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*_GRIS)
    pdf.set_x(20)
    pdf.multi_cell(_ANCHO - 20, 4, subtitulo, align="C")
    pdf.ln(3)


def _destinatario(pdf: _Documento, documento: dict[str, Any], extras: dict[str, Any]) -> None:
    _titulo_seccion(pdf, "DESTINATARIO")
    entidad = dict(extras.get("entidad") or {})
    _bloque(
        pdf,
        [
            [("Entidad:", str(documento.get("entidad") or ""))],
            *(
                [(etiqueta, valor)]
                for etiqueta, valor in (
                    ("RUC:", str(entidad.get("ruc") or "")),
                    ("Dirección:", str(entidad.get("direccion") or "")),
                    ("Teléfono:", str(entidad.get("telefono") or "")),
                    ("Correo:", str(entidad.get("correo") or "")),
                )
                if valor
            ),
            [("Fecha de emisión:", str(extras.get("fecha") or ""))],
        ],
    )
    if documento.get("objeto"):
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*_AZUL_OSCURO)
        _parrafo(pdf, "Objeto de contratación", alto=4.4, despues=0.6)
        pdf.set_font("Helvetica", "", 9.5)
        pdf.set_text_color(*_TINTA)
        _parrafo(pdf, str(documento["objeto"]), alto=4.8)


def _declaracion(pdf: _Documento, texto: str) -> None:
    _titulo_seccion(pdf, "DECLARACIÓN DEL OFERENTE")
    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(*_TINTA)
    _parrafo(pdf, texto, alto=4.2, despues=1)


def _firma(pdf: _Documento, nombre: str, empresa: dict[str, Any]) -> None:
    # El sello se estampa siempre en el mismo recuadro, abajo a la derecha (x ≥ 120 mm). El bloque
    # va a la izquierda, así que solo cambia de página si ya no cabe antes del pie (y = 280).
    nota = (
        "Firma de responsabilidad. En la ínfima cuantía la firma electrónica es exigible en la "
        "orden de compra o la factura; en la proforma es opcional. Si se firma, se hace con "
        "FirmaEC o con un certificado de una entidad acreditada, y cada recuadro lleva su sello."
    )
    pdf.set_font("Helvetica", "I", 7)
    filas = [f for f in (empresa.get("cargo"), empresa.get("cedula"), nombre) if f]
    alto = (
        2
        + (5 if empresa.get("representante") else 0)
        + 4.4 * len(filas)
        + 1
        + 3.3 * len(_renglones(pdf, 105, 3.3, nota))
    )
    pdf.ln(6)
    if pdf.get_y() + alto > 280:
        pdf.add_page()
    pdf.set_auto_page_break(auto=False)
    pdf.set_draw_color(*_AZUL_OSCURO)
    pdf.set_line_width(0.4)
    pdf.line(10, pdf.get_y(), 95, pdf.get_y())
    pdf.ln(2)
    pdf.set_text_color(*_TINTA)
    pdf.set_font("Helvetica", "B", 10)
    if empresa.get("representante"):
        _parrafo(pdf, str(empresa["representante"]), alto=4.6, despues=0.4)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*_GRIS)
    for fila in (
        empresa.get("cargo"),
        f"C.I. {empresa['cedula']}" if empresa.get("cedula") else "",
        nombre,
    ):
        if fila:
            _parrafo(pdf, str(fila), alto=4.2, despues=0.2)
    pdf.ln(1)
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_x(10)
    pdf.multi_cell(105, 3.3, nota)
    pdf.set_auto_page_break(auto=True, margin=22)

    # Mismo rectángulo que CAJA_FIRMA de la firma: al firmar, el sello lo cubre por completo.
    pdf.set_draw_color(*_AZUL_OSCURO)
    pdf.set_line_width(0.3)
    pdf.rect(120, 249, 80, 30)
    pdf.cajas.append(_caja(pdf.page_no(), 120, 249, 80, 30))
    pdf.set_xy(120, 244)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(*_GRIS)
    pdf.cell(80, 4, "Firma electrónica")


_INTEGRIDAD = (
    "1. Conozco formalmente el contenido, alcance y principios de la Política Nacional de "
    "Integridad Pública (PNIP). Garantizo que mi actuación en este procedimiento se ceñirá "
    "estrictamente a los valores de honestidad, legalidad, integridad, probidad y prevención de "
    "conflictos de interés, así como a las directrices e instrumentos que emita la Secretaría "
    "General de Integridad Pública, para promover la integridad y fortalecer la lucha contra la "
    "corrupción.",
    "2. En mi calidad de proveedor del Estado, no he ofrecido, entregado, prometido ni facilitado "
    "dinero, bienes, dádivas, favores ni ventajas indebidas de orden material o inmaterial a "
    "ningún servidor público, trabajador de la entidad contratante o persona del sector privado, "
    "con el objeto de influir, viciar u obtener un trato favorable en este o cualquier otro "
    "procedimiento de contratación en el que haya participado.",
    "3. No me encuentro incurso en ningún conflicto de intereses con los miembros de la Comisión "
    "Técnica y/o el delegado de la fase precontractual, ni con los servidores públicos que "
    "intervengan en la sustanciación de las fases y etapas de este procedimiento de contratación "
    "de {entidad}, garantizando que mi participación está libre de conductas que configuren "
    "tráfico de influencias, colusión o cualquier otro delito contra la administración pública.",
    "4. Toda la información y documentación consignada en este formulario y en mi oferta es "
    "veraz, exacta, completa y actualizada. Acepto que, si la entidad contratante, el Servicio "
    "Nacional de Contratación Pública o cualquier organismo de control constata falsedad o "
    "alteración en estos datos, o si se determinan motivadamente riesgos sustanciales para la "
    "seguridad integral del Estado conforme al Decreto Ejecutivo Nro. 328 del 12 de marzo de "
    "2026, esto constituirá una falta de idoneidad en materia de integridad pública. En "
    "consecuencia, acepto que dicha condición se calificará como incumplimiento de un requisito "
    "mínimo, dando lugar a la descalificación inmediata de la oferta en la etapa precontractual, "
    "o a la declaratoria de adjudicatario fallido o contratista incumplido, según corresponda, "
    "sin perjuicio de las acciones administrativas, civiles y penales pertinentes.",
)
_INTEGRIDAD_COMPROMISO = (
    "Así también me comprometo a poner en conocimiento y denunciar de manera inmediata ante la "
    "Fiscalía General del Estado, la Secretaría General de Integridad Pública, la máxima "
    "autoridad de la entidad contratante o cualquier otra autoridad competente, todo presunto "
    "delito contra la administración pública o acto de corrupción del cual llegue a tener "
    "conocimiento, a fin de que se adopten las acciones y medidas legales en contra de los "
    "presuntos infractores."
)


def _integridad(pdf: _Documento, documento: dict[str, Any], empresa: dict[str, Any]) -> None:
    """Anexo I de la Resolución R.E-SERCOP-2026-0005: Formulario de Perfil de Integridad.

    El texto es el del modelo oficial. Solo se rellenan los datos entre corchetes del modelo.
    """
    extras = documento.get("extras") or {}
    pdf.add_page()
    _titulo_documento(
        pdf,
        "FORMULARIO DE PERFIL DE INTEGRIDAD DEL PROVEEDOR",
        "Anexo I de la Resolución Nro. R.E-SERCOP-2026-0005, que se presenta junto con la oferta",
    )
    entidad = str(documento.get("entidad") or "la entidad contratante")
    razon = str(empresa.get("razon_social") or "")
    firmante = str(empresa.get("representante") or razon)
    ruc = str(empresa.get("ruc") or "")
    codigo = str(extras.get("codigo") or "")
    por_razon = f", por la razón social {razon}" if razon and firmante != razon else ""
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*_TINTA)
    _parrafo(
        pdf,
        f"Yo, {firmante or '[nombre completo]'}{por_razon}, portador del RUC No. "
        f"{ruc or '[RUC]'}, en atención a la convocatoria realizada por {entidad} para la "
        f"ejecución de «{documento.get('objeto') or '[objeto]'}», dentro del procedimiento de "
        f"contratación pública con el código {codigo or '[código del proceso]'}, al presentar mi "
        "oferta suscribo el presente Formulario de Perfil de Integridad del Proveedor, y "
        "declaro que:",
        alto=4.6,
        despues=2,
    )
    for texto in _INTEGRIDAD:
        pdf.set_font("Helvetica", "", 8.6)
        _parrafo(pdf, texto.format(entidad=entidad), alto=4.2, despues=1.6)
    pdf.set_font("Helvetica", "", 8.6)
    _parrafo(pdf, _INTEGRIDAD_COMPROMISO, alto=4.2, despues=4)

    if pdf.get_y() + 52 > 280:
        pdf.add_page()
    y = pdf.get_y() + 4
    pdf.set_draw_color(*_AZUL_OSCURO)
    pdf.set_line_width(0.3)
    pdf.rect(10, y, 80, 30)
    pdf.cajas.append(_caja(pdf.page_no(), 10, y, 80, 30))
    pdf.set_xy(10, y - 4)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(*_GRIS)
    pdf.cell(80, 4, "Firma del oferente o su representante legal")
    pdf.set_xy(100, y + 2)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*_TINTA)
    lugar_fecha = ", ".join(
        p for p in (str(empresa.get("ciudad") or ""), str(extras.get("fecha") or "")) if p
    )
    for etiqueta, valor in (
        ("Nombre:", firmante),
        ("C.C. / RUC:", ruc or str(empresa.get("cedula") or "")),
        ("Lugar y fecha:", lugar_fecha),
    ):
        pdf.set_x(100)
        pdf.multi_cell(100, 5, f"{etiqueta} {valor}", new_x="LMARGIN", new_y="NEXT")


# --- Modelo de la proforma del SOCE («Necesidades de contratación y recepción de proformas») -----
# Datos del proceso, datos del proveedor, detalle del objeto de compra con una columna por dato que
# pide la entidad (CPC, descripción, unidad, cantidad) y el valor que ofrece el proveedor.
_ANCHOS_ITEMS = (9.0, 36.0, 54.0, 15.0, 15.0, 24.0, 24.0, 13.0)
_CABECERAS_ITEMS = (
    "No.",
    "CPC",
    "Descripción del Producto",
    "Unidad",
    "Cantidad",
    "Valor Unitario Ofertado",
    "Valor Total",
    "",
)
_ALINEAR_ITEMS = ("C", "L", "L", "C", "R", "R", "R", "C")
_RENGLON_ITEMS = 3.9
_LIMITE_PAGINA = 270


def _precio(valor: Any) -> str:
    """Cinco decimales, como el formulario del SOCE («3020.00000»)."""
    try:
        return f"{float(valor):.5f}"
    except (TypeError, ValueError):
        return str(valor or "")


def _cantidad_dos(valor: Any) -> str:
    try:
        return f"{float(valor):.2f}"
    except (TypeError, ValueError):
        return str(valor or "")


def _dato_linea(pdf: _Documento, etiqueta: str, valor: Any) -> None:
    if not str(valor or "").strip():
        return
    pdf.set_x(10)
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.set_text_color(*_TINTA)
    pdf.cell(46, 5, etiqueta)
    pdf.set_font("Helvetica", "", 8.5)
    pdf.multi_cell(_ANCHO - 46, 5, str(valor), new_x="LMARGIN", new_y="NEXT")


def _datos_del_proceso(pdf: _Documento, documento: dict[str, Any], extras: dict[str, Any]) -> None:
    _titulo_seccion(pdf, "Datos del proceso")
    _dato_linea(pdf, "Entidad contratante:", documento.get("entidad"))
    _dato_linea(pdf, "Código del proceso:", extras.get("codigo"))
    _dato_linea(pdf, "Objeto de contratación:", documento.get("objeto"))
    _dato_linea(pdf, "Fecha de emisión:", extras.get("fecha"))


def _datos_del_proveedor(pdf: _Documento, empresa: dict[str, Any]) -> None:
    _titulo_seccion(pdf, "Datos del Proveedor")
    for etiqueta, clave in (
        ("RUC:", "ruc"),
        ("Razón Social:", "razon_social"),
        ("Correo electrónico:", "email"),
        ("Teléfono:", "telefono"),
        ("País:", "pais"),
        ("Provincia:", "provincia"),
        ("Cantón:", "canton"),
        ("Dirección:", "direccion"),
        ("Representante legal:", "representante"),
    ):
        _dato_linea(
            pdf,
            etiqueta,
            str(empresa.get(clave) or "").upper()
            if clave in {"razon_social", "provincia", "canton", "pais"}
            else empresa.get(clave),
        )


def _cabecera_items(pdf: _Documento) -> None:
    pdf.set_font("Helvetica", "B", 7.5)
    pdf.set_text_color(*_TINTA)
    pdf.set_draw_color(*_LINEA)
    pdf.set_line_width(0.2)
    alto = 11.0
    y = pdf.get_y()
    x = 10.0
    for ancho, texto in zip(_ANCHOS_ITEMS, _CABECERAS_ITEMS, strict=True):
        pdf.rect(x, y, ancho, alto)
        if texto:
            pdf.set_xy(x + 0.5, y + 1.4)
            pdf.multi_cell(ancho - 1, 3.6, texto, align="C")
        x += ancho
    pdf.set_y(y + alto)


def _fila_items(pdf: _Documento, celdas: tuple[str, ...]) -> None:
    pdf.set_font("Helvetica", "", 7.8)
    alto = 6.0
    for ancho, texto in zip(_ANCHOS_ITEMS, celdas, strict=True):
        if texto:
            renglones = _renglones(pdf, ancho - 2, _RENGLON_ITEMS, texto)
            alto = max(alto, _RENGLON_ITEMS * len(renglones) + 2.4)
    if pdf.get_y() + alto > _LIMITE_PAGINA:
        pdf.add_page()
        _cabecera_items(pdf)
    y = pdf.get_y()
    x = 10.0
    pdf.set_font("Helvetica", "", 7.8)
    pdf.set_text_color(*_TINTA)
    pdf.set_draw_color(*_LINEA)
    pdf.set_line_width(0.2)
    for ancho, texto, alinear in zip(_ANCHOS_ITEMS, celdas, _ALINEAR_ITEMS, strict=True):
        pdf.rect(x, y, ancho, alto)
        if texto:
            pdf.set_xy(x + 1, y + 1.2)
            pdf.multi_cell(ancho - 2, _RENGLON_ITEMS, texto, align=alinear)
        x += ancho
    pdf.set_y(y + alto)


def _fila_total(pdf: _Documento, etiqueta: str, valor: Any) -> None:
    ancho_etiqueta = sum(_ANCHOS_ITEMS[:6])
    if pdf.get_y() + 7 > _LIMITE_PAGINA:
        pdf.add_page()
    y = pdf.get_y()
    pdf.set_draw_color(*_LINEA)
    pdf.set_line_width(0.2)
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.set_text_color(*_TINTA)
    pdf.rect(10, y, ancho_etiqueta, 7)
    pdf.set_xy(10, y + 1.4)
    pdf.cell(ancho_etiqueta - 2, 4.2, etiqueta, align="R")
    pdf.rect(10 + ancho_etiqueta, y, _ANCHOS_ITEMS[6], 7)
    pdf.set_xy(10 + ancho_etiqueta, y + 1.4)
    pdf.cell(_ANCHOS_ITEMS[6] - 1, 4.2, _precio(valor), align="R")
    pdf.rect(10 + ancho_etiqueta + _ANCHOS_ITEMS[6], y, _ANCHOS_ITEMS[7], 7)
    pdf.set_xy(10 + ancho_etiqueta + _ANCHOS_ITEMS[6], y + 1.4)
    pdf.cell(_ANCHOS_ITEMS[7], 4.2, "USD.", align="C")
    pdf.set_y(y + 7)


def _detalle_de_compra(
    pdf: _Documento, lineas: list[dict[str, Any]], cifras: dict[str, Any]
) -> None:
    # El título y la cabecera no se quedan solos al pie de una página: llevan al menos una fila.
    if pdf.get_y() + 45 > _LIMITE_PAGINA:
        pdf.add_page()
    _titulo_seccion(pdf, "Detalle del objeto de compra")
    _cabecera_items(pdf)
    for numero, linea in enumerate(lineas, start=1):
        cpc = str(linea.get("cpc") or "")
        nombre = str(linea.get("cpc_nombre") or "")
        _fila_items(
            pdf,
            (
                str(numero),
                f"{cpc}\n{nombre}".strip(),
                str(linea.get("descripcion") or ""),
                str(linea.get("unidad") or ""),
                _cantidad_dos(linea.get("cantidad")),
                _precio(linea.get("precio_unitario")),
                _precio(linea.get("subtotal")),
                "USD.",
            ),
        )
    if not cifras:
        return
    if float(cifras.get("impuesto_porcentaje") or 0) > 0:
        _fila_total(pdf, "SUBTOTAL:", cifras.get("subtotal"))
        _fila_total(
            pdf, f"IVA {_cantidad(cifras.get('impuesto_porcentaje'))} %:", cifras.get("impuesto")
        )
    _fila_total(pdf, "TOTAL:", cifras.get("total"))


def _documentos_anexos(pdf: _Documento, anexos: list[str]) -> None:
    """«Documentos Anexos / Archivo para adjuntar su proforma», como en el formulario del SOCE."""
    if pdf.get_y() + 40 > _LIMITE_PAGINA:
        pdf.add_page()
    _titulo_seccion(pdf, "Documentos Anexos")
    pdf.set_draw_color(*_LINEA)
    pdf.set_line_width(0.2)
    y = pdf.get_y()
    pdf.rect(10, y, _ANCHO, 7)
    pdf.set_xy(12, y + 1.6)
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.set_text_color(*_TINTA)
    pdf.cell(120, 4.5, "ARCHIVO PARA ADJUNTAR SU PROFORMA")
    y += 7
    pdf.rect(10, y, _ANCHO, 7)
    pdf.set_xy(12, y + 1.6)
    pdf.cell(120, 4.5, "Descripción del Archivo")
    pdf.set_xy(150, y + 1.6)
    pdf.cell(48, 4.5, "Archivo", align="C")
    y += 7
    pdf.set_font("Helvetica", "", 8.5)
    for nombre in anexos:
        pdf.rect(10, y, _ANCHO, 7)
        pdf.set_xy(12, y + 1.6)
        pdf.cell(130, 4.5, nombre)
        pdf.set_xy(150, y + 1.6)
        pdf.cell(48, 4.5, "Adjunto a este documento", align="C")
        y += 7
    pdf.set_y(y)


def _vigencia(pdf: _Documento, validez: Any) -> None:
    texto = str(validez or "").strip()
    if not texto:
        return
    pdf.ln(4)
    if pdf.get_y() + 9 > _LIMITE_PAGINA:
        pdf.add_page()
    y = pdf.get_y()
    pdf.set_draw_color(*_LINEA)
    pdf.set_line_width(0.2)
    pdf.rect(10, y, _ANCHO, 8)
    pdf.set_text_color(*_TINTA)
    pdf.set_xy(12, y + 1.8)
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.cell(60, 4.5, "Vigencia de la Proforma")
    pdf.set_font("Helvetica", "", 8.5)
    dias = re.match(r"\s*(\d+)", texto)
    if dias:
        pdf.set_x(80)
        pdf.cell(30, 4.5, dias.group(1))
        pdf.cell(40, 4.5, "(días calendario)")
    else:
        pdf.set_x(80)
        pdf.cell(118, 4.5, texto)
    pdf.set_y(y + 8)


def _nuevo(documento: dict[str, Any], tipo: str) -> tuple[_Documento, str, dict[str, Any]]:
    extras = documento.get("extras") or {}
    empresa = extras.get("empresa") or {}
    nombre = str(empresa.get("razon_social") or documento.get("titulo") or tipo)
    pdf = _Documento(nombre, str(empresa.get("ruc") or ""), tipo)
    pdf.alias_nb_pages()
    pdf.add_page()
    _membrete(pdf, nombre, empresa)
    return pdf, nombre, empresa


def pdf_proforma(documento: dict[str, Any]) -> bytes:
    return armar_proforma(documento)[0]


def pdf_ficha(documento: dict[str, Any]) -> bytes:
    return armar_ficha(documento)[0]


def armar_proforma(documento: dict[str, Any]) -> tuple[bytes, list[Caja]]:
    """Proforma o cotización maquetada, con los recuadros de firma que dejó en cada página."""
    documento = _imprimible(documento)
    generico, subtitulo, este = _TIPOS.get(str(documento.get("tipo")), _TIPOS["proforma"])
    # Arriba va el título que escribió la persona (referente a la ínfima); sin él, el genérico.
    propio = " ".join(str(documento.get("titulo") or "").split())
    titulo = propio.upper() if propio else generico
    extras = documento.get("extras") or {}
    condiciones = extras.get("condiciones") or {}
    cifras = documento.get("cifras") or {}
    pdf, nombre, empresa = _nuevo(documento, generico.capitalize())

    _titulo_documento(pdf, titulo, subtitulo)
    _datos_del_proceso(pdf, documento, extras)
    _datos_del_proveedor(pdf, empresa)

    lineas = documento.get("lineas") or []
    if lineas:
        _detalle_de_compra(pdf, lineas, cifras)
    _vigencia(pdf, condiciones.get("validez"))
    con_integridad = documento.get("tipo") != "cotizacion" and extras.get("integridad") is not False
    anexos = ["Proforma"]
    if con_integridad:
        anexos.append("Formulario de Perfil de Integridad del Proveedor")
    _documentos_anexos(pdf, anexos)

    if extras.get("carta"):
        _titulo_seccion(pdf, "PRESENTACIÓN")
        pdf.set_font("Helvetica", "", 9.5)
        pdf.set_text_color(*_TINTA)
        for parrafo in str(extras["carta"]).split("\n"):
            if parrafo.strip():
                _parrafo(pdf, parrafo.strip(), alto=4.6, despues=1.2)

    condiciones_filas = [
        [
            ("Plazo de entrega:", str(condiciones.get("plazo_entrega") or "")),
            ("Lugar de entrega:", str(condiciones.get("lugar_entrega") or "")),
        ],
        [
            ("Forma de pago:", str(condiciones.get("forma_pago") or "")),
            ("Garantía:", str(condiciones.get("garantia") or "")),
        ],
    ]
    if any(valor for fila in condiciones_filas for _, valor in fila):
        _titulo_seccion(pdf, "CONDICIONES DE LA OFERTA")
        _bloque(pdf, condiciones_filas)

    for seccion, clave in (
        ("EXPERIENCIA DEL OFERENTE", "experiencia"),
        ("PERSONAL TÉCNICO", "personal"),
        ("EQUIPO DISPONIBLE", "equipo"),
    ):
        filas = [str(f) for f in extras.get(clave) or [] if str(f).strip()]
        if filas:
            _titulo_seccion(pdf, seccion)
            _viñetas(pdf, filas)

    cumplimiento = [
        fila
        for fila in extras.get("cumplimiento") or []
        if isinstance(fila, dict) and str(fila.get("requisito") or "").strip()
    ]
    if cumplimiento:
        _titulo_seccion(pdf, "CUMPLIMIENTO DE LOS TÉRMINOS DE REFERENCIA")
        _tabla(
            pdf,
            (10, 56, 70, 54),
            ("N.º", "Requisito del TDR", "Cómo cumple el oferente", "Firma electrónica"),
            [
                (
                    f"R{numero}",
                    str(fila["requisito"]).strip(),
                    str(fila.get("como_cumple") or "").strip() or "Sin respuesta",
                    "",
                )
                for numero, fila in enumerate(cumplimiento, start=1)
            ],
            alinear=("C", "L", "L", "C"),
            negrita=(0, 1),
            firma=str(empresa.get("representante") or nombre),
        )

    _declaracion(
        pdf,
        f"{nombre} declara que no se encuentra incursa en ninguna de las inhabilidades ni "
        "prohibiciones para contratar con el Estado previstas en la Ley Orgánica del Sistema "
        "Nacional de Contratación Pública, que conoce y acepta las condiciones establecidas por la "
        f"entidad contratante, y que los precios de {este} incluyen todos los costos, "
        "impuestos y obligaciones tributarias. La vigencia indicada se cuenta desde la fecha de "
        "emisión.",
    )
    _firma(pdf, nombre, empresa)
    # La cotización es un estudio de mercado, no una oferta: el formulario de integridad se
    # presenta con ofertas. Quien no lo quiera lo apaga con `integridad: false`.
    if documento.get("tipo") != "cotizacion" and extras.get("integridad") is not False:
        _integridad(pdf, documento, empresa)
    return bytes(pdf.output()), pdf.cajas


def armar_ficha(documento: dict[str, Any]) -> tuple[bytes, list[Caja]]:
    """Ficha técnica: identificación del bien y matriz de especificaciones requeridas/ofertadas."""
    documento = _imprimible(documento)
    extras = documento.get("extras") or {}
    linea = (documento.get("lineas") or [{}])[0]
    pdf, nombre, empresa = _nuevo(documento, "Ficha técnica")

    _titulo_documento(
        pdf,
        "FICHA TÉCNICA",
        "Especificaciones técnicas del bien o servicio ofertado frente a lo que requiere la "
        "entidad contratante, conforme la normativa del SERCOP",
    )
    _destinatario(pdf, documento, extras)

    _titulo_seccion(pdf, "IDENTIFICACIÓN DEL BIEN O SERVICIO")
    _bloque(
        pdf,
        [
            [("Producto o servicio:", str(linea.get("nombre") or linea.get("descripcion") or ""))],
            [
                ("Marca:", str(linea.get("marca") or "")),
                ("Modelo:", str(linea.get("modelo") or "")),
            ],
            [
                ("País de origen:", str(linea.get("pais_origen") or "")),
                ("Año de fabricación:", str(linea.get("anio_fabricacion") or "")),
            ],
            [("Código CPC:", str(linea.get("cpc") or ""))],
            [("Garantía técnica:", str(linea.get("garantia") or ""))],
        ],
    )

    especificaciones = [
        fila
        for fila in linea.get("especificaciones") or []
        if isinstance(fila, dict) and (fila.get("requerido") or fila.get("ofertado"))
    ] or [
        {"requerido": "", "ofertado": renglon.strip()}
        for renglon in str(linea.get("caracteristicas") or "").splitlines()
        if renglon.strip()
    ]
    if especificaciones:
        _titulo_seccion(pdf, "ESPECIFICACIONES TÉCNICAS")
        if any(fila.get("requerido") for fila in especificaciones):
            filas = []
            for numero, fila in enumerate(especificaciones, start=1):
                ofertado = str(fila.get("ofertado") or "").strip()
                filas.append(
                    (
                        f"E{numero}",
                        str(fila.get("requerido") or "").strip() or "-",
                        ofertado or "Sin especificar",
                        "Sí" if ofertado else "Pendiente",
                    )
                )
            _tabla(
                pdf,
                (12, 78, 78, 22),
                ("N.º", "Requerido por la entidad", "Ofertado", "Cumple"),
                filas,
                alinear=("C", "L", "L", "C"),
                negrita=(0, 3),
            )
            pendientes = sum(1 for fila in filas if fila[3] != "Sí")
            if pendientes:
                pdf.ln(1)
                pdf.set_font("Helvetica", "I", 8)
                pdf.set_text_color(*_AMBAR)
                _parrafo(pdf, f"{pendientes} especificación(es) sin respuesta.", alto=4, despues=0)
        else:
            _tabla(
                pdf,
                (12, 178),
                ("N.º", "Característica ofertada"),
                [
                    (f"E{numero}", str(fila["ofertado"]))
                    for numero, fila in enumerate(especificaciones, start=1)
                ],
                alinear=("C", "L"),
                negrita=(0,),
            )

    contacto = str(documento.get("contacto") or "")
    if contacto:
        _titulo_seccion(pdf, "CONTACTO PARA CONSULTAS TÉCNICAS")
        _bloque(pdf, [[("Contacto:", contacto)]])

    _declaracion(
        pdf,
        f"{nombre} declara bajo juramento que los bienes ofertados son nuevos, de primera calidad, "
        "no remanufacturados ni reconstruidos, que cumplen todas las especificaciones técnicas "
        "requeridas por la entidad contratante en los términos de referencia, y que la información "
        "de esta ficha técnica es verídica. En caso de servicios, declara que se prestarán con el "
        "personal y el equipo indicados en la oferta.",
    )
    _firma(pdf, nombre, empresa)
    return bytes(pdf.output()), pdf.cajas
