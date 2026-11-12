"""Texto de cualquier anexo que publica una ínfima: PDF, Word, Excel, texto o un ZIP con ellos.

Antes solo se leían PDF y .txt: un TDR en Word, el formulario de proforma en Excel o un ZIP con los
pliegos se ignoraban, y la proforma se armaba sin ese contexto. El cliente pidió que se lean todos
los archivos adjuntos a la ínfima.

- **PDF**: `pdf.py` (un escaneo sin texto no se interpreta aquí; el panel tiene OCR).
- **Word (.docx)**: el cuerpo, las tablas y también encabezados y pies, que es donde la entidad
  pone su RUC, dirección y teléfono.
- **Excel (.xlsx)**: cada fila con sus celdas separadas por «|» (formularios de precios, listas de
  ítems con cantidades).
- **ZIP**: se abre una sola vez (sin ZIP dentro de ZIP), con topes de archivos y de tamaño
  descomprimido para que un archivo malicioso no llene la memoria.
- **.doc, .xls y .rar**: formatos que no se pueden leer sin programas externos; se avisa con un
  mensaje que dice qué hacer.
"""

from __future__ import annotations

import html
import io
import re
import zipfile
from pathlib import PurePosixPath

from contratacion.dominio.errores import DatoInvalido
from contratacion.infraestructura.adaptadores.salida.pdf import texto_de_pdf

TOPE_TEXTO = 200_000
_TOPE_MIEMBROS = 30
_TOPE_DESCOMPRIMIDO = 40 * 1024 * 1024
_TOPE_FILAS = 400
_TOPE_HOJAS = 10
# Un Word o un Excel es un ZIP por dentro, y antes solo se acotaba cada parte por separado: un .docx
# con mil encabezados de 40 MB pasaba el filtro y se descomprimían 40 GB, y un .xlsx se abría con
# openpyxl sin mirar cuánto ocupaba descomprimido (la tabla de textos compartidos se carga entera).
# Ahora se mira el total declarado de **todo** el paquete antes de leer nada, y el número de partes.
# El tamaño declarado es fiable: `zipfile` deja de descomprimir al llegar a él.
_TOPE_PARTES_OFIMATICA = 2_000

_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_RAR = b"Rar!"
_LEGIBLES = (".pdf", ".docx", ".xlsx", ".txt", ".csv")

_PARRAFO = re.compile(r"</w:p>|<w:br[^>]*/>|<w:cr[^>]*/>")
_CELDA = re.compile(r"</w:tc>")
_TAB = re.compile(r"<w:tab[^>]*/>")
_ETIQUETA = re.compile(r"<[^>]+>")


class FormatoNoLegible(DatoInvalido):
    """El archivo existe pero su formato no se puede leer aquí."""


def _xml_a_texto(xml: str) -> str:
    xml = _CELDA.sub(" | ", xml)
    xml = _TAB.sub("\t", xml)
    xml = _PARRAFO.sub("\n", xml)
    texto = html.unescape(_ETIQUETA.sub("", xml))
    lineas = (" ".join(linea.split()) for linea in texto.splitlines())
    return "\n".join(linea.strip(" |") for linea in lineas if linea.strip(" |"))


def _orden_word(nombre: str) -> tuple[int, str]:
    # Encabezados primero (membrete de la entidad), luego el cuerpo, luego los pies.
    if "/header" in nombre:
        return (0, nombre)
    if nombre.endswith("document.xml"):
        return (1, nombre)
    return (2, nombre)


def _exigir_paquete_acotado(paquete: zipfile.ZipFile, que: str) -> None:
    """Rechaza un Word o un Excel que descomprimido pasaría del tope (bomba ZIP)."""
    miembros = paquete.infolist()
    if len(miembros) > _TOPE_PARTES_OFIMATICA:
        raise FormatoNoLegible(f"El {que} tiene demasiadas partes para leerlo aquí.")
    if sum(info.file_size for info in miembros) > _TOPE_DESCOMPRIMIDO:
        raise FormatoNoLegible(f"El {que} es demasiado grande para leerlo aquí.")


def texto_de_docx(contenido: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(contenido)) as libro:
            _exigir_paquete_acotado(libro, "archivo Word")
            partes = sorted(
                (
                    nombre
                    for nombre in libro.namelist()
                    if re.fullmatch(r"word/(document|header\d*|footer\d*)\.xml", nombre)
                ),
                key=_orden_word,
            )
            textos = []
            for nombre in partes:
                if libro.getinfo(nombre).file_size > _TOPE_DESCOMPRIMIDO:
                    continue
                textos.append(_xml_a_texto(libro.read(nombre).decode("utf-8", errors="replace")))
    except zipfile.BadZipFile as error:
        raise FormatoNoLegible("El archivo Word está dañado y no se puede leer.") from error
    return "\n".join(texto for texto in textos if texto)


def texto_de_xlsx(contenido: bytes) -> str:
    from openpyxl import load_workbook  # carga perezosa: solo se paga si llega un Excel

    try:
        with zipfile.ZipFile(io.BytesIO(contenido)) as paquete:
            _exigir_paquete_acotado(paquete, "archivo Excel")
    except zipfile.BadZipFile as error:
        raise FormatoNoLegible("El archivo Excel está dañado y no se puede leer.") from error

    try:
        libro = load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
    except Exception as error:  # openpyxl lanza tipos distintos según el daño
        raise FormatoNoLegible("El archivo Excel está dañado y no se puede leer.") from error
    lineas: list[str] = []
    try:
        for hoja in libro.worksheets[:_TOPE_HOJAS]:
            lineas.append(f"Hoja: {hoja.title}")
            for numero, fila in enumerate(hoja.iter_rows(values_only=True)):
                if numero >= _TOPE_FILAS:
                    break
                celdas = [" ".join(str(valor).split()) for valor in fila if valor not in (None, "")]
                if celdas:
                    lineas.append(" | ".join(celdas))
    finally:
        libro.close()
    return "\n".join(lineas)


def _miembro_seguro(nombre: str) -> bool:
    ruta = PurePosixPath(nombre.replace("\\", "/"))
    return not ruta.is_absolute() and ".." not in ruta.parts and not nombre.endswith("/")


def texto_de_zip(contenido: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(contenido)) as paquete:
            miembros = [
                info
                for info in paquete.infolist()
                if _miembro_seguro(info.filename)
                and info.filename.lower().endswith(_LEGIBLES)
                and not PurePosixPath(info.filename).name.startswith(("~$", "."))
            ][:_TOPE_MIEMBROS]
            if sum(info.file_size for info in miembros) > _TOPE_DESCOMPRIMIDO:
                raise FormatoNoLegible("El ZIP es demasiado grande para leerlo aquí.")
            textos = []
            for info in miembros:
                nombre = PurePosixPath(info.filename).name
                try:
                    texto = texto_de_archivo(nombre, paquete.read(info), dentro_de_zip=True)
                except DatoInvalido:
                    continue
                if texto.strip():
                    textos.append(f"=== {nombre} ===\n{texto}")
    except zipfile.BadZipFile as error:
        raise FormatoNoLegible("El ZIP está dañado y no se puede abrir.") from error
    if not textos:
        raise FormatoNoLegible("El ZIP no trae PDF, Word ni Excel con texto que se pueda leer.")
    return "\n\n".join(textos)


def texto_de_archivo(nombre: str, contenido: bytes, *, dentro_de_zip: bool = False) -> str:
    """El texto del archivo, según lo que es de verdad (por sus primeros bytes) y su nombre."""
    bajo = nombre.lower()
    if contenido.startswith(b"%PDF"):
        texto = texto_de_pdf(contenido)
    elif contenido.startswith(b"PK"):
        try:
            with zipfile.ZipFile(io.BytesIO(contenido)) as paquete:
                nombres = set(paquete.namelist())
        except zipfile.BadZipFile as error:
            raise FormatoNoLegible("El archivo está dañado y no se puede abrir.") from error
        if "word/document.xml" in nombres:
            texto = texto_de_docx(contenido)
        elif "xl/workbook.xml" in nombres:
            texto = texto_de_xlsx(contenido)
        elif dentro_de_zip:
            raise FormatoNoLegible("ZIP dentro de ZIP: no se abre.")
        else:
            texto = texto_de_zip(contenido)
    elif contenido.startswith(_OLE):
        raise FormatoNoLegible(
            "Es un Word o Excel antiguo (.doc o .xls). Ábrelo y guárdalo como PDF para leerlo."
        )
    elif contenido.startswith(_RAR):
        raise FormatoNoLegible("Es un archivo .rar. Descomprímelo y sube los PDF que trae.")
    elif bajo.endswith((".txt", ".csv")):
        texto = contenido.decode("utf-8", errors="replace")
    else:
        raise FormatoNoLegible("No se reconoce el formato del archivo.")
    return texto[:TOPE_TEXTO]
