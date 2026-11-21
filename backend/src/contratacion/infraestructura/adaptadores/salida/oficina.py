"""DOCX y PDF de una proforma o una ficha, armados en memoria."""

from __future__ import annotations

import io
import textwrap
import zipfile
from typing import Any

from contratacion.dominio.paginas_finales import (
    ADHIERE,
    FORMATO_INFIMA,
    formato_de,
    paginas_activas,
    texto_compromiso,
    totales_iva,
)


def _xml(texto: str) -> str:
    return str(texto).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def docx(parrafos: list[str]) -> bytes:
    cuerpo = "".join(f"<w:p><w:r><w:t>{_xml(linea)}</w:t></w:r></w:p>" for linea in parrafos)
    return _paquete(cuerpo)


def _paquete(cuerpo: str) -> bytes:
    """El .docx mínimo (tipos, relaciones y documento) con el cuerpo WordprocessingML dado."""
    documento = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{cuerpo}"
        # A4 con márgenes de 2 cm, como el modelo de la entidad.
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" '
        'w:header="567" w:footer="567" w:gutter="0"/></w:sectPr>'
        "</w:body></w:document>"
    )
    tipos = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    relaciones = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        "</Relationships>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archivo:
        archivo.writestr("[Content_Types].xml", tipos)
        archivo.writestr("_rels/.rels", relaciones)
        archivo.writestr("word/document.xml", documento)
    return buffer.getvalue()


def _pdf(texto: str) -> str:
    limpio = texto.encode("cp1252", errors="replace").decode("cp1252")
    return limpio.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def pdf(parrafos: list[str]) -> bytes:
    """Un PDF de texto. Varias páginas si la lista no cabe en una."""
    lineas: list[str] = []
    for parrafo in parrafos:
        for renglon in str(parrafo).splitlines() or [""]:
            limpio = renglon.lstrip()
            sangria = " " * (len(renglon) - len(limpio))
            if limpio[:1] and limpio[:1] in "•0123456789":
                sangria += "   "
            lineas.extend(textwrap.wrap(renglon, width=92, subsequent_indent=sangria) or [""])
    # 48 renglones desde y=800 dejan libre el pie, donde va el sello de la firma electrónica.
    paginas = [lineas[i : i + 48] for i in range(0, max(len(lineas), 1), 48)]
    objetos: list[bytes] = []
    objetos.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{3 + indice * 2} 0 R" for indice in range(len(paginas)))
    objetos.append(f"<< /Type /Pages /Count {len(paginas)} /Kids [{kids}] >>".encode())
    for indice, pagina in enumerate(paginas):
        comandos = ["BT /F1 11 Tf 50 800 Td 14 TL"]
        for linea in pagina:
            comandos.append(f"({_pdf(linea[:110])}) '")
        comandos.append("ET")
        flujo = "\n".join(comandos).encode("cp1252", errors="replace")
        objetos.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                f"/Contents {4 + indice * 2} 0 R "
                f"/Resources << /Font << /F1 {3 + len(paginas) * 2} 0 R >> >> >>"
            ).encode()
        )
        objetos.append(f"<< /Length {len(flujo)} >>\nstream\n".encode() + flujo + b"\nendstream")
    objetos.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    salida = io.BytesIO()
    salida.write(b"%PDF-1.4\n")
    desplazamientos = [0]
    for numero, objeto in enumerate(objetos, start=1):
        desplazamientos.append(salida.tell())
        salida.write(f"{numero} 0 obj\n".encode())
        salida.write(objeto)
        salida.write(b"\nendobj\n")
    inicio = salida.tell()
    salida.write(f"xref\n0 {len(objetos) + 1}\n".encode())
    salida.write(b"0000000000 65535 f \n")
    for desplazamiento in desplazamientos[1:]:
        salida.write(f"{desplazamiento:010d} 00000 n \n".encode())
    salida.write(
        f"trailer << /Size {len(objetos) + 1} /Root 1 0 R >>\nstartxref\n{inicio}\n%%EOF".encode()
    )
    return salida.getvalue()


def _dato(etiqueta: str, valor: Any) -> list[str]:
    texto = str(valor or "").strip()
    return [f"{etiqueta}: {texto}"] if texto else []


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


def parrafos_de(documento: dict[str, Any]) -> list[str]:
    """El texto que se imprime. Lo que no está no se imprime; los importes ya vienen calculados."""
    extras = documento.get("extras") or {}
    empresa = extras.get("empresa") or {}
    lineas: list[str] = []
    if empresa.get("razon_social"):
        lineas.append(str(empresa["razon_social"]).upper())
        lineas += _dato("RUC", empresa.get("ruc"))
        direccion = ", ".join(str(empresa[c]) for c in ("direccion", "ciudad") if empresa.get(c))
        lineas += _dato("Dirección", direccion)
        contacto = " · ".join(str(empresa[c]) for c in ("telefono", "email") if empresa.get(c))
        lineas += _dato("Contacto", contacto)
        lineas.append("")
    lineas += [documento.get("titulo") or "Documento", ""]
    lineas += _dato("Fecha", extras.get("fecha"))
    lineas += _dato("Entidad", documento.get("entidad"))
    entidad = extras.get("entidad") or {}
    lineas += _dato("RUC de la entidad", entidad.get("ruc"))
    lineas += _dato("Dirección de la entidad", entidad.get("direccion"))
    lineas += _dato("Teléfono de la entidad", entidad.get("telefono"))
    lineas += _dato("Correo de la entidad", entidad.get("correo"))
    lineas += _dato("Sitio web de la entidad", entidad.get("web"))
    lineas += _dato("Objeto", documento.get("objeto"))
    lineas += _dato("Contacto", documento.get("contacto"))
    if extras.get("carta"):
        lineas += ["", str(extras["carta"])]
    lineas.append("")

    cifras = documento.get("cifras") or {}
    if documento.get("tipo") != "ficha" and documento.get("lineas"):
        lineas.append("DETALLE DE LA OFERTA")
    for numero, linea in enumerate(documento.get("lineas") or [], start=1):
        if documento.get("tipo") == "ficha":
            lineas.append("IDENTIFICACIÓN DEL BIEN O SERVICIO")
            lineas += _dato("Producto o servicio", linea.get("nombre") or linea.get("descripcion"))
            for etiqueta, clave in (
                ("Marca", "marca"),
                ("Modelo", "modelo"),
                ("País de origen", "pais_origen"),
                ("Año de fabricación", "anio_fabricacion"),
                ("Código CPC", "cpc"),
                ("Garantía técnica", "garantia"),
            ):
                lineas += _dato(etiqueta, linea.get(clave))
            especificaciones = [
                f
                for f in linea.get("especificaciones") or []
                if isinstance(f, dict) and (f.get("requerido") or f.get("ofertado"))
            ]
            if especificaciones:
                lineas += ["", "ESPECIFICACIONES TÉCNICAS"]
                for n, fila in enumerate(especificaciones, start=1):
                    if fila.get("requerido"):
                        lineas.append(f"E{n}. Requerido: {fila['requerido']}")
                        lineas.append(f"    Ofertado: {fila.get('ofertado') or 'Sin especificar'}")
                    else:
                        lineas.append(f"E{n}. {fila.get('ofertado')}")
            else:
                lineas += _dato("Características", linea.get("caracteristicas"))
            lineas += [
                "",
                "DECLARACIÓN: los bienes ofertados son nuevos, de primera calidad, no "
                "remanufacturados, y cumplen las especificaciones técnicas del TDR.",
            ]
            continue
        unidad = f" {linea['unidad']}" if linea.get("unidad") else ""
        cpc = f"[CPC {linea['cpc']}] " if linea.get("cpc") else ""
        detalle = f"{_cantidad(linea.get('cantidad'))}{unidad}"
        lineas.append(
            f"{numero}. {cpc}{linea.get('descripcion')} — {detalle}"
            f" x {_dinero(linea.get('precio_unitario'))} = {_dinero(linea.get('subtotal'))}"
        )
    if cifras:
        lineas += [
            "",
            f"Subtotal: {_dinero(cifras.get('subtotal'))}",
            f"IVA {_cantidad(cifras.get('impuesto_porcentaje'))}%: "
            f"{_dinero(cifras.get('impuesto'))}",
            f"TOTAL: {_dinero(cifras.get('total'))}",
        ]

    condiciones = extras.get("condiciones") or {}
    bloque = (
        _dato("Plazo de entrega", condiciones.get("plazo_entrega"))
        + _dato("Lugar de entrega", condiciones.get("lugar_entrega"))
        + _dato("Forma de pago", condiciones.get("forma_pago"))
        + _dato("Garantía", condiciones.get("garantia"))
        + _dato("Validez de la oferta", condiciones.get("validez"))
    )
    # Una ficha no tiene páginas finales; una proforma, las que eligió la persona.
    activas = (
        paginas_activas(documento)
        if documento.get("tipo") != "ficha"
        else {pagina: True for pagina in ("respaldo", "cumplimiento")}
    )
    if activas.get("respaldo"):
        bloque += _dato("Alcance", extras.get("alcance"))
    if bloque:
        lineas += ["", "CONDICIONES", *bloque]
    respaldo = [r.strip() for r in str(extras.get("detalle_condiciones") or "").splitlines()]
    if any(respaldo) and activas.get("respaldo"):
        lineas += ["", "DETALLE DE LAS CONDICIONES SEGÚN EL TDR", *[r for r in respaldo if r]]
    for titulo, clave in (
        ("EXPERIENCIA", "experiencia"),
        ("PERSONAL", "personal"),
        ("EQUIPO", "equipo"),
    ):
        filas = [str(f) for f in extras.get(clave) or [] if str(f).strip()]
        if filas and activas.get("respaldo"):
            lineas += ["", titulo, *[f"• {f}" for f in filas]]
    cumplimiento = [
        f for f in extras.get("cumplimiento") or [] if isinstance(f, dict) and f.get("requisito")
    ]
    if cumplimiento and activas.get("cumplimiento"):
        lineas += ["", "CUMPLIMIENTO DE LOS TÉRMINOS DE REFERENCIA"]
        for n, fila in enumerate(cumplimiento, start=1):
            lineas.append(f"R{n}. {fila['requisito']}")
            if fila.get("como_cumple"):
                lineas.append(f"    {fila['como_cumple']}")

    lineas += ["", "", "______________________________"]
    if empresa.get("representante"):
        lineas.append(str(empresa["representante"]))
        lineas += [str(empresa["cargo"])] if empresa.get("cargo") else []
        lineas += _dato("C.I.", empresa.get("cedula"))
    lineas += [str(empresa["razon_social"])] if empresa.get("razon_social") else []
    if activas.get("compromiso"):
        lineas += [
            "",
            "CARTA DE COMPROMISO",
            texto_compromiso(
                str(empresa.get("razon_social") or ""),
                str(empresa.get("ruc") or ""),
                str(documento.get("entidad") or "").upper(),
                str(documento.get("objeto") or ""),
            ),
            "",
            "______________________________",
            str(empresa.get("razon_social") or ""),
            *_dato("RUC", empresa.get("ruc")),
        ]
    return lineas


# --- Word con el modelo de proforma de ínfima cuantía -------------------------------------------
# Mismo orden y mismos rótulos que el PDF (`proforma_pdf._armar_infima`): el Word es para quien
# prefiere retocar la proforma antes de firmarla, así que lleva tablas de verdad, no texto suelto.
_ANCHOS_WORD = (567, 3289, 1134, 1361, 1588, 1701)  # twips; suman 9640 (17 cm)
_CELESTE_WORD = "D9E2EC"
_AZUL_WORD = "2563EB"
_FONDO_FIRMA_WORD = "EFF6FF"


def _run(texto: str, *, negrita: bool = False, tamano: int = 20, color: str = "") -> str:
    propiedades = ("<w:b/>" if negrita else "") + (f'<w:color w:val="{color}"/>' if color else "")
    propiedades += f'<w:sz w:val="{tamano}"/>'
    return f'<w:r><w:rPr>{propiedades}</w:rPr><w:t xml:space="preserve">{_xml(texto)}</w:t></w:r>'


def _p(*runs: str, alinear: str = "", despues: int = 60) -> str:
    jc = f'<w:jc w:val="{alinear}"/>' if alinear else ""
    return f'<w:p><w:pPr><w:spacing w:after="{despues}"/>{jc}</w:pPr>{"".join(runs)}</w:p>'


def _etiqueta(etiqueta: str, valor: Any) -> str:
    return _p(_run(f"{etiqueta} ", negrita=True), _run(str(valor or "").strip()))


def _salto_de_pagina() -> str:
    return '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'


_BORDE = '<w:{lado} w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
_BORDES = "".join(
    _BORDE.format(lado=lado) for lado in ("top", "left", "bottom", "right", "insideH", "insideV")
)


def _celda(
    texto: str,
    ancho: int,
    *,
    negrita: bool = False,
    relleno: str = "",
    alinear: str = "left",
    span: int = 1,
    sin_borde: bool = False,
) -> str:
    propiedades = f'<w:tcW w:w="{ancho}" w:type="dxa"/>'
    if span > 1:
        propiedades += f'<w:gridSpan w:val="{span}"/>'
    if sin_borde:
        propiedades += (
            "<w:tcBorders>"
            + "".join(f'<w:{lado} w:val="nil"/>' for lado in ("top", "left", "bottom"))
            + "</w:tcBorders>"
        )
    if relleno:
        propiedades += f'<w:shd w:val="clear" w:color="auto" w:fill="{relleno}"/>'
    parrafos = "".join(
        _p(_run(renglon, negrita=negrita, tamano=18), alinear=alinear, despues=0)
        for renglon in (str(texto).split("\n") or [""])
    )
    return f"<w:tc><w:tcPr>{propiedades}</w:tcPr>{parrafos}</w:tc>"


def _tabla(filas: list[str], anchos: tuple[int, ...]) -> str:
    rejilla = "".join(f'<w:gridCol w:w="{ancho}"/>' for ancho in anchos)
    return (
        f'<w:tbl><w:tblPr><w:tblW w:w="{sum(anchos)}" w:type="dxa"/>'
        f"<w:tblBorders>{_BORDES}</w:tblBorders></w:tblPr>"
        f"<w:tblGrid>{rejilla}</w:tblGrid>{''.join(filas)}</w:tbl>"
    )


def _fila(*celdas: str) -> str:
    return f"<w:tr>{''.join(celdas)}</w:tr>"


def _moneda(valor: Any) -> str:
    try:
        return f"$ {float(valor):,.2f}"
    except (TypeError, ValueError):
        return str(valor or "")


def _unitario(valor: Any) -> str:
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return str(valor or "")
    if round(numero, 2) == numero:
        return f"$ {numero:,.2f}"
    return "$ " + f"{numero:,.5f}".rstrip("0")


def _recuadro_firma() -> str:
    """El único recuadro de la firma electrónica, resaltado como en el PDF."""
    borde = "".join(
        f'<w:{lado} w:val="single" w:sz="12" w:space="0" w:color="{_AZUL_WORD}"/>'
        for lado in ("top", "left", "bottom", "right")
    )
    vacios = "".join(_p(_run(" "), despues=0) for _ in range(4))
    rotulo = _p(
        _run("Firma electrónica del oferente", negrita=True, tamano=14, color=_AZUL_WORD),
        alinear="center",
        despues=0,
    )
    return (
        '<w:tbl><w:tblPr><w:tblW w:w="4252" w:type="dxa"/>'
        f"<w:tblBorders>{borde}</w:tblBorders></w:tblPr>"
        '<w:tblGrid><w:gridCol w:w="4252"/></w:tblGrid><w:tr><w:tc><w:tcPr>'
        f'<w:tcW w:w="4252" w:type="dxa"/><w:shd w:val="clear" w:color="auto" '
        f'w:fill="{_FONDO_FIRMA_WORD}"/></w:tcPr>{vacios}{rotulo}</w:tc></w:tr></w:tbl>'
    )


def _firma_word(empresa: dict[str, Any], *, con_representante: bool) -> list[str]:
    partes = [_p(_run(" ")), _p(_run("Atentamente,")), _recuadro_firma(), _p(_run(" "))]
    if con_representante and empresa.get("representante"):
        partes.append(_etiqueta("Representante legal:", empresa.get("representante")))
    partes += [
        _etiqueta("Razón Social:", empresa.get("razon_social")),
        _etiqueta("RUC:", empresa.get("ruc")),
    ]
    return partes


def _titulo_word(texto: str) -> str:
    return _p(_run(texto, negrita=True, tamano=28), alinear="center", despues=240)


def _subtitulo_word(texto: str) -> str:
    return _p(_run(texto, negrita=True, tamano=21), despues=80)


def docx_infima(documento: dict[str, Any]) -> bytes:
    """Word de la proforma con el modelo de ínfima cuantía y las páginas finales elegidas."""
    from contratacion.infraestructura.adaptadores.salida.proforma_pdf import (
        INTEGRIDAD,
        INTEGRIDAD_COMPROMISO,
        texto_declaracion,
        titulo_impreso,
    )

    extras = documento.get("extras") or {}
    empresa = extras.get("empresa") or {}
    entidad = extras.get("entidad") or {}
    condiciones = extras.get("condiciones") or {}
    cifras = documento.get("cifras") or {}
    titulo, este = titulo_impreso(documento)
    numero = str(extras.get("numero") or "").strip()
    cuerpo: list[str] = [_titulo_word(f"{titulo} N° {numero}" if numero else titulo)]
    cuerpo += [
        _etiqueta("Cliente:", str(documento.get("entidad") or "").upper()),
        _etiqueta("Dirección:", entidad.get("direccion")),
        _etiqueta("RUC:", entidad.get("ruc")),
        _etiqueta("Fecha:", extras.get("fecha")),
        _p(_run(" ")),
    ]
    direccion = ", ".join(
        str(p)
        for p in (
            empresa.get("direccion"),
            empresa.get("canton") or empresa.get("ciudad"),
            empresa.get("provincia"),
        )
        if p
    )
    cuerpo += [
        _etiqueta("Proveedor (Razón Social):", empresa.get("razon_social")),
        _etiqueta("RUC:", empresa.get("ruc")),
        _etiqueta("Teléfono:", empresa.get("telefono")),
        _etiqueta("Dirección:", direccion),
        _etiqueta("Correo electrónico:", empresa.get("email")),
        _p(_run(" ")),
    ]
    cabeceras = (
        "N°",
        "DESCRIPCIÓN",
        "CANTIDAD",
        "UNIDAD DE MEDIDA",
        "VALOR UNITARIO",
        "VALOR TOTAL",
    )
    filas = [
        _fila(
            *(
                _celda(t, a, negrita=True, relleno=_CELESTE_WORD, alinear="center")
                for t, a in zip(cabeceras, _ANCHOS_WORD, strict=True)
            )
        )
    ]
    alinear = ("center", "left", "center", "center", "right", "right")
    for posicion, linea in enumerate(documento.get("lineas") or [], start=1):
        textos = (
            str(posicion),
            str(linea.get("descripcion") or ""),
            _cantidad(linea.get("cantidad")),
            str(linea.get("unidad") or ""),
            _unitario(linea.get("precio_unitario")),
            _moneda(linea.get("subtotal")),
        )
        filas.append(
            _fila(
                *(
                    _celda(t, a, alinear=lado)
                    for t, a, lado in zip(textos, _ANCHOS_WORD, alinear, strict=True)
                )
            )
        )
    if cifras:
        vacio = sum(_ANCHOS_WORD[:4])
        for rotulo, valor in totales_iva(cifras):
            filas.append(
                _fila(
                    _celda("", vacio, span=4, sin_borde=True),
                    _celda(rotulo, _ANCHOS_WORD[4], negrita=True),
                    _celda(
                        _moneda(valor), _ANCHOS_WORD[5], negrita=rotulo == "TOTAL", alinear="right"
                    ),
                )
            )
    cuerpo.append(_tabla(filas, _ANCHOS_WORD))
    cuerpo.append(_p(_run(" ")))

    def o_adhiere(*claves: str) -> str:
        for clave in claves:
            if str(condiciones.get(clave) or "").strip():
                return str(condiciones[clave]).strip()
        return ADHIERE

    cuerpo += [
        _etiqueta("Forma de Pago:", o_adhiere("forma_pago")),
        _etiqueta("Vigencia de la Oferta:", condiciones.get("validez")),
        _etiqueta("Plazo de entrega:", o_adhiere("plazo_entrega", "plazo_ejecucion")),
        _etiqueta("Garantía:", condiciones.get("garantia")),
        _etiqueta("Lugar de entrega:", o_adhiere("lugar_entrega")),
    ]
    cuerpo += _firma_word(empresa, con_representante=False)

    activas = paginas_activas(documento)
    if activas["respaldo"]:
        cuerpo += [_salto_de_pagina(), _titulo_word("DOCUMENTO DE RESPALDO DE LA PROFORMA")]
        cuerpo.append(_subtitulo_word("DATOS DEL PROCESO"))
        for etiqueta, dato in (
            ("Código del proceso:", extras.get("codigo")),
            ("Código de necesidad:", extras.get("necesidad")),
            ("Proforma N°:", extras.get("numero")),
            ("Objeto de contratación:", documento.get("objeto")),
            ("Teléfono de la entidad:", entidad.get("telefono")),
            ("Correo de la entidad:", entidad.get("correo")),
            ("Sitio web de la entidad:", entidad.get("web")),
        ):
            if str(dato or "").strip():
                cuerpo.append(_etiqueta(etiqueta, dato))
        con_cpc = [
            (n, linea)
            for n, linea in enumerate(documento.get("lineas") or [], start=1)
            if linea.get("cpc")
        ]
        if con_cpc:
            cuerpo.append(_subtitulo_word("CPC DE CADA ÍTEM"))
            for n, linea in con_cpc:
                nombre = str(linea.get("cpc_nombre") or "").strip()
                cuerpo.append(
                    _p(_run(f"{n}. CPC {linea['cpc']}{f' - {nombre}' if nombre else ''}"))
                )
        for etiqueta, dato in (
            ("Plazo de ejecución:", condiciones.get("plazo_ejecucion")),
            ("Alcance:", extras.get("alcance")),
        ):
            if str(dato or "").strip():
                cuerpo.append(_etiqueta(etiqueta, dato))
        detalle = [r.strip() for r in str(extras.get("detalle_condiciones") or "").splitlines()]
        if any(detalle):
            cuerpo.append(_subtitulo_word("DETALLE DE LAS CONDICIONES SEGÚN EL TDR"))
            cuerpo += [_p(_run(r)) for r in detalle if r]
        if str(extras.get("carta") or "").strip():
            cuerpo.append(_subtitulo_word("PRESENTACIÓN"))
            cuerpo += [_p(_run(r.strip())) for r in str(extras["carta"]).split("\n") if r.strip()]
        for titulo_lista, clave in (
            ("EXPERIENCIA DEL OFERENTE", "experiencia"),
            ("PERSONAL TÉCNICO", "personal"),
            ("EQUIPO DISPONIBLE", "equipo"),
        ):
            lista = [str(f) for f in extras.get(clave) or [] if str(f).strip()]
            if lista:
                cuerpo.append(_subtitulo_word(titulo_lista))
                cuerpo += [_p(_run(f"-  {f}")) for f in lista]
    cumplimiento = [
        f
        for f in extras.get("cumplimiento") or []
        if isinstance(f, dict) and str(f.get("requisito") or "").strip()
    ]
    hay_hoja = False
    if activas["cumplimiento"] and cumplimiento:
        anchos = (850, 3700, 5090)
        cuerpo += [
            _salto_de_pagina(),
            _subtitulo_word("CUMPLIMIENTO DE LOS TÉRMINOS DE REFERENCIA"),
        ]
        filas_c = [
            _fila(
                *(
                    _celda(t, a, negrita=True, relleno=_CELESTE_WORD, alinear="center")
                    for t, a in zip(
                        ("N.º", "Requisito del TDR", "Cómo cumple el oferente"), anchos, strict=True
                    )
                )
            )
        ]
        for n, fila in enumerate(cumplimiento, start=1):
            filas_c.append(
                _fila(
                    _celda(f"R{n}", anchos[0], alinear="center"),
                    _celda(str(fila["requisito"]).strip(), anchos[1]),
                    _celda(
                        str(fila.get("como_cumple") or "").strip() or "Sin respuesta", anchos[2]
                    ),
                )
            )
        cuerpo.append(_tabla(filas_c, anchos))
        hay_hoja = True
    if activas["declaracion"]:
        if not hay_hoja:
            cuerpo.append(_salto_de_pagina())
        nombre = str(empresa.get("razon_social") or documento.get("titulo") or "El oferente")
        cuerpo += [
            _p(_run(" ")),
            _subtitulo_word("DECLARACIÓN DEL OFERENTE"),
            _p(_run(texto_declaracion(nombre, este))),
        ]
    if activas["compromiso"]:
        lugar_fecha = ", ".join(str(p) for p in (empresa.get("ciudad"), extras.get("fecha")) if p)
        cuerpo += [_salto_de_pagina(), _titulo_word("CARTA DE COMPROMISO")]
        if lugar_fecha:
            cuerpo.append(_p(_run(lugar_fecha), alinear="right", despues=240))
        cuerpo.append(
            _p(
                _run(
                    texto_compromiso(
                        str(empresa.get("razon_social") or ""),
                        str(empresa.get("ruc") or ""),
                        str(documento.get("entidad") or "").upper(),
                        str(documento.get("objeto") or ""),
                    ),
                    tamano=21,
                ),
                alinear="both",
            )
        )
        cuerpo += _firma_word(empresa, con_representante=True)
    if activas["integridad"]:
        entidad_nombre = str(documento.get("entidad") or "la entidad contratante")
        razon = str(empresa.get("razon_social") or "")
        firmante = str(empresa.get("representante") or razon)
        por_razon = f", por la razón social {razon}" if razon and firmante != razon else ""
        cuerpo += [
            _salto_de_pagina(),
            _titulo_word("FORMULARIO DE PERFIL DE INTEGRIDAD DEL PROVEEDOR"),
            _p(
                _run(
                    f"Yo, {firmante or '[nombre completo]'}{por_razon}, portador del RUC No. "
                    f"{empresa.get('ruc') or '[RUC]'}, en atención a la convocatoria realizada por "
                    f"{entidad_nombre} para la ejecución de "
                    f"«{documento.get('objeto') or '[objeto]'}», "
                    "dentro del procedimiento de contratación pública con el código "
                    f"{extras.get('codigo') or '[código del proceso]'}, al presentar mi oferta "
                    "suscribo el presente Formulario de Perfil de Integridad del Proveedor, y "
                    "declaro que:"
                ),
                alinear="both",
            ),
            *(_p(_run(t.format(entidad=entidad_nombre)), alinear="both") for t in INTEGRIDAD),
            _p(_run(INTEGRIDAD_COMPROMISO), alinear="both"),
            *_firma_word(empresa, con_representante=True),
        ]
    return _paquete("".join(cuerpo))


def docx_documento(documento: dict[str, Any]) -> bytes:
    """El Word que se descarga: el modelo de ínfima o el texto del formato SOCE / la ficha."""
    if documento.get("tipo") != "ficha" and formato_de(documento) == FORMATO_INFIMA:
        return docx_infima(documento)
    return docx(parrafos_de(documento))
