"""Bajar un anexo de la ficha con su extensión real y el nombre que le dio la entidad.

El fallo que se protege: «INFORME DE NECESIDAD» (un .docx) se guardaba como `contrataciones.xlsx`.
Tres causas encadenadas: el tipo se deducía del *nombre* del anexo —el texto de la ficha, sin
extensión— y salía `application/octet-stream`; el nombre servido no tenía extensión; y, como lleva
espacios, Starlette solo escribía `filename*=` y el panel, que leía `filename=`, ponía su nombre por
defecto. Aquí se prueban la detección por contenido, el nombre de descarga y la cabecera.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote
from uuid import uuid4

from contratacion.aplicacion.casos_uso.atender_tdr import (
    MENSAJE_MANTENIMIENTO,
    MENSAJE_SIN_PORTAL,
    enlace_al_portal,
    mensaje_de_error,
    mime_real,
    nombre_de_descarga,
)
from contratacion.infraestructura.adaptadores.entrada.http.routers.tdr import archivo, disposicion
from contratacion.infraestructura.adaptadores.salida.archivos.tdr import (
    MIME_DOCX,
    MIME_XLSX,
    extension_de,
    tipo_de_archivo,
    tipo_por_contenido,
)
from contratacion.infraestructura.adaptadores.salida.fuentes.nco_detalle import parsear_documentos


def _zip(partes: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as paquete:
        for nombre, contenido in partes.items():
            paquete.writestr(nombre, contenido)
    return buffer.getvalue()


DOCX = _zip({"[Content_Types].xml": b"<Types/>", "word/document.xml": b"<w:document/>"})
XLSX = _zip({"[Content_Types].xml": b"<Types/>", "xl/workbook.xml": b"<workbook/>"})
ODT = _zip({"mimetype": b"application/vnd.oasis.opendocument.text", "content.xml": b"<x/>"})
ZIP = _zip({"anexo1.pdf": b"%PDF-1.4", "anexo2.pdf": b"%PDF-1.4"})
OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 504
DOC = OLE + "WordDocument".encode("utf-16-le")
XLS = OLE + "Workbook".encode("utf-16-le")


# --------------------------------------------------------------------------- #
# Tipo por contenido
# --------------------------------------------------------------------------- #


def test_reconoce_los_tipos_por_sus_bytes() -> None:
    assert tipo_por_contenido(b"%PDF-1.7\n...") == "application/pdf"
    # Basura antes de la firma (la norma la admite en el primer KB).
    assert tipo_por_contenido(b"\r\n\xef\xbb\xbf%PDF-1.4") == "application/pdf"
    assert tipo_por_contenido(DOCX) == MIME_DOCX
    assert tipo_por_contenido(XLSX) == MIME_XLSX
    assert tipo_por_contenido(ODT) == "application/vnd.oasis.opendocument.text"
    assert tipo_por_contenido(ZIP) == "application/zip"
    assert tipo_por_contenido(DOC) == "application/msword"
    assert tipo_por_contenido(XLS) == "application/vnd.ms-excel"
    assert tipo_por_contenido(b"\x89PNG\r\n\x1a\n....") == "image/png"
    assert tipo_por_contenido(b"\xff\xd8\xff\xe0JFIF") == "image/jpeg"
    assert tipo_por_contenido(b"Rar!\x1a\x07\x00") == "application/vnd.rar"


def test_lo_que_no_reconoce_queda_generico() -> None:
    assert tipo_por_contenido(b"") == "application/octet-stream"
    assert tipo_por_contenido(b"hola, soy texto") == "application/octet-stream"
    # Un ZIP roto no tumba la detección.
    assert tipo_por_contenido(b"PK\x03\x04roto") == "application/zip"
    assert tipo_por_contenido(OLE) == "application/octet-stream"


def test_tipo_de_archivo_en_disco(tmp_path: Path) -> None:
    ruta = tmp_path / "abc"
    ruta.write_bytes(DOCX)
    assert tipo_de_archivo(ruta) == MIME_DOCX
    assert tipo_de_archivo(tmp_path / "no-existe") == "application/octet-stream"


def test_mime_real_prefiere_el_contenido_al_nombre_y_a_lo_guardado(tmp_path: Path) -> None:
    ruta = tmp_path / "x"
    ruta.write_bytes(DOCX)
    # Filas viejas guardaban el tipo deducido del nombre: se corrige al servir.
    assert mime_real(ruta, "INFORME DE NECESIDAD", "application/octet-stream") == MIME_DOCX
    assert mime_real(ruta, "TDR.pdf", "application/pdf") == MIME_DOCX
    ruta.write_bytes(b"no se sabe")
    assert mime_real(ruta, "TDR.pdf", "") == "application/pdf"
    assert mime_real(ruta, "TDR", "image/png") == "image/png"
    assert mime_real(ruta, "TDR", "") == "application/octet-stream"


def test_extension_de() -> None:
    assert extension_de(MIME_DOCX) == ".docx"
    assert extension_de("application/pdf; charset=binary") == ".pdf"
    assert extension_de("application/octet-stream") == ""


# --------------------------------------------------------------------------- #
# Nombre con el que se guarda
# --------------------------------------------------------------------------- #


def test_nombre_de_descarga_usa_el_nombre_de_la_entidad_y_la_extension_real() -> None:
    assert nombre_de_descarga("INFORME DE NECESIDAD", MIME_DOCX) == "INFORME DE NECESIDAD.docx"
    assert nombre_de_descarga("TDR.pdf", "application/pdf") == "TDR.pdf"
    assert nombre_de_descarga("TDR.PDF", "application/pdf") == "TDR.PDF"
    # La extensión escrita no coincide con el contenido: manda el contenido.
    assert nombre_de_descarga("Anexo.pdf", MIME_DOCX) == "Anexo.docx"
    assert nombre_de_descarga("foto.jpeg", "image/jpeg") == "foto.jpeg"
    # Un punto que no es extensión no se toca.
    assert nombre_de_descarga("Informe v1.2", "application/pdf") == "Informe v1.2.pdf"
    # Tipo desconocido: el nombre tal cual, sin inventar extensión.
    assert nombre_de_descarga("Anexo 3", "application/octet-stream") == "Anexo 3"


def test_nombre_de_descarga_limpia_lo_que_no_admite_un_sistema_de_archivos() -> None:
    assert nombre_de_descarga('Acta: 1/2 "final"', "application/pdf") == "Acta 1 2 final.pdf"
    assert nombre_de_descarga("  Términos   de referencia  ", "application/pdf") == (
        "Términos de referencia.pdf"
    )
    # El nombre era la dirección del portal: nombre genérico, con la extensión real.
    assert nombre_de_descarga("../GE/ExeGENBajarArchivoGeneral.cpe?Archivo=x", MIME_DOCX) == (
        "documento.docx"
    )
    assert nombre_de_descarga("", "application/pdf") == "documento.pdf"
    largo = nombre_de_descarga("A" * 400, "application/pdf")
    assert largo.endswith(".pdf") and len(largo) <= 124


def test_la_cabecera_lleva_el_nombre_en_ascii_y_en_utf8() -> None:
    cabecera = disposicion("inline", "Términos de referencia.docx")
    assert cabecera.startswith("inline; ")
    assert 'filename="Terminos de referencia.docx"' in cabecera
    utf8 = cabecera.split("filename*=UTF-8''", 1)[1]
    assert unquote(utf8) == "Términos de referencia.docx"


# --------------------------------------------------------------------------- #
# La ruta de descarga, de punta a punta
# --------------------------------------------------------------------------- #


class _Actor:
    def exigir_permiso(self, permiso: str) -> None:
        del permiso


class _Tdr:
    def __init__(self, fila: dict[str, Any]) -> None:
        self.fila = fila

    async def uno(self, documento_id: Any) -> dict[str, Any]:
        return self.fila


async def test_la_ruta_sirve_el_docx_con_su_extension_y_tipo(tmp_path: Path) -> None:
    huella = hashlib.sha256(DOCX).hexdigest()
    ruta = tmp_path / huella
    ruta.write_bytes(DOCX)
    registro_id = uuid4()
    fila = {
        "registro_id": registro_id,
        "estado": "listo",
        "nombre": "INFORME DE NECESIDAD",
        "mime": "application/octet-stream",  # como lo dejaba el worker antes del arreglo
        "ruta": str(ruta),
        "sha256": huella,
    }
    respuesta = await archivo(
        registro_id, uuid4(), cast(Any, _Actor()), cast(Any, _Tdr(fila)), cast(Any, None)
    )
    assert respuesta.media_type == MIME_DOCX
    cabecera = respuesta.headers["content-disposition"]
    assert 'filename="INFORME DE NECESIDAD.docx"' in cabecera
    assert "filename*=UTF-8''INFORME%20DE%20NECESIDAD.docx" in cabecera


# --------------------------------------------------------------------------- #
# Avisos y enlaces al portal
# --------------------------------------------------------------------------- #


def test_errores_de_red_se_explican_y_ofrecen_el_portal() -> None:
    assert mensaje_de_error("ConnectTimeout: timed out") == MENSAJE_SIN_PORTAL
    assert mensaje_de_error("HTTPStatusError: 503") == MENSAJE_SIN_PORTAL
    assert mensaje_de_error("") == MENSAJE_SIN_PORTAL
    assert mensaje_de_error("PortalEnMantenimiento: aviso") == MENSAJE_MANTENIMIENTO
    assert mensaje_de_error("El archivo supera 25 MB.") == "El archivo supera 25 MB."


def test_enlace_al_portal_solo_del_portal() -> None:
    url = enlace_al_portal("../GE/ExeGENBajarArchivoGeneral.cpe?Archivo=abc")
    assert url.startswith("https://www.compraspublicas.gob.ec/ProcesoContratacion/compras/GE/")
    assert enlace_al_portal("https://compraspublicas.gob.ec.atacante.com/x") == ""
    assert enlace_al_portal("http://www.compraspublicas.gob.ec/x") == ""
    assert enlace_al_portal("javascript:alert(1)") == ""
    assert enlace_al_portal("") == ""


# --------------------------------------------------------------------------- #
# Ficha: fecha y descripción de cada archivo
# --------------------------------------------------------------------------- #


def test_la_ficha_guarda_la_fecha_y_la_descripcion_de_la_entidad() -> None:
    html = """
    <table>
    <tr><td>Descripci&oacute;n del Archivo</td><td>Archivo</td><td>Fecha</td></tr>
    <tr><td>Anexo</td>
        <td><a href="../GE/ExeGENBajarArchivoGeneral.cpe?Archivo=a1">TDR_mantenimiento.pdf</a></td>
        <td>14/11/2026 10:30</td></tr>
    <tr><td>INFORME DE NECESIDAD</td>
        <td><a href="../GE/ExeGENBajarArchivoGeneral.cpe?Archivo=a2"><img src="b.gif"></a></td>
        <td>2026-11-15</td></tr>
    </table>
    """
    documentos = parsear_documentos(html)
    assert documentos[0]["nombre"] == "TDR_mantenimiento.pdf"
    assert documentos[0]["descripcion"] == "Anexo"
    assert documentos[0]["fecha"] == "2026-11-14T10:30:00"
    assert documentos[1]["nombre"] == "INFORME DE NECESIDAD"
    assert "descripcion" not in documentos[1]
    assert documentos[1]["fecha"] == "2026-11-15"


def test_sin_columna_de_fecha_no_se_inventa() -> None:
    html = """
    <table><tr><td> Formato de proforma </td><td>
      <a href="../GE/ExeGENBajarArchivoGeneral.cpe?Archivo=x"><img src="x.gif"></a></td></tr>
    </table>
    """
    (documento,) = parsear_documentos(html)
    assert documento["nombre"] == "Formato de proforma"
    assert "fecha" not in documento


def test_el_nombre_puede_venir_despues_del_icono() -> None:
    html = """
    <table><tr><td><a href="../GE/ExeGENBajarArchivoGeneral.cpe?Archivo=x"><img></a></td>
    <td>Especificaciones t&eacute;cnicas</td></tr></table>
    """
    (documento,) = parsear_documentos(html)
    assert documento["nombre"] == "Especificaciones técnicas"
