"""DOCX y PDF de una proforma o una ficha, armados en memoria."""

from __future__ import annotations

import io
import textwrap
import zipfile
from typing import Any


def _xml(texto: str) -> str:
    return str(texto).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def docx(parrafos: list[str]) -> bytes:
    cuerpo = "".join(f"<w:p><w:r><w:t>{_xml(linea)}</w:t></w:r></w:p>" for linea in parrafos)
    documento = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{cuerpo}</w:body></w:document>"
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
    if bloque:
        lineas += ["", "CONDICIONES", *bloque]
    for titulo, clave in (
        ("EXPERIENCIA", "experiencia"),
        ("PERSONAL", "personal"),
        ("EQUIPO", "equipo"),
    ):
        filas = [str(f) for f in extras.get(clave) or [] if str(f).strip()]
        if filas:
            lineas += ["", titulo, *[f"• {f}" for f in filas]]
    cumplimiento = [
        f for f in extras.get("cumplimiento") or [] if isinstance(f, dict) and f.get("requisito")
    ]
    if cumplimiento:
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
    return lineas
