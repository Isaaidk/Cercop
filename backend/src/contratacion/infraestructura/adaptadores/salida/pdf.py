"""Texto de un PDF. No guarda el archivo y no interpreta una página escaneada."""

from __future__ import annotations

import io

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from contratacion.dominio.errores import DatoInvalido

_PAGINAS = 40


def texto_de_pdf(contenido: bytes) -> str:
    try:
        lector = PdfReader(io.BytesIO(contenido))
    except PdfReadError as error:
        raise DatoInvalido("El archivo no se puede leer como PDF.") from error
    trozos = []
    for pagina in lector.pages[:_PAGINAS]:
        trozos.append(pagina.extract_text() or "")
    return "\n".join(trozos).strip()
