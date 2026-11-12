"""Firma PAdES de un PDF con el certificado .p12/.pfx del usuario.

Sirve para FirmaEC, Security Data, ANF, Banco Central o cualquier certificado en PKCS#12. El archivo
y la clave viven solo en memoria durante la petición: no se guardan, no se registran y no se
devuelven. Lo que se audita es el titular y el emisor del certificado.
"""

from __future__ import annotations

import asyncio
import io
import tempfile
import textwrap
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import qrcode  # type: ignore[import-untyped]  # sin anotaciones de tipos publicadas
from fpdf import FPDF
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.layout import AxisAlignment, InnerScaling, SimpleBoxLayoutRule
from pyhanko.sign import fields, signers
from pyhanko.sign.signers.pdf_signer import PdfSigner
from pyhanko.stamp import StaticStampStyle

from contratacion.dominio.errores import DatoInvalido

TOPE_CERTIFICADO = 64 * 1024
# Las firmas en paralelo son CPU pura; más de cuatro a la vez solo alargan la cola de todos.
_TURNOS = asyncio.Semaphore(4)
# Recuadro de la última página, en puntos PDF con origen abajo a la izquierda. La proforma dibuja
# el mismo rectángulo: 120 mm desde la izquierda, 18 mm del borde inferior, 80 x 30 mm.
CAJA_FIRMA = (340, 51, 567, 136)
# Un PDF con un recuadro por requisito firma cada uno. Más de esto no es una proforma.
MAX_RECUADROS = 60
# Ecuador continental no cambia de hora: la fecha del QR va con -05:00, como la de FirmaEC.
_HORA_ECUADOR = timezone(timedelta(hours=-5))

# Medidas del sello en puntos, en la proporción del de FirmaEC (110 x 36 pt) a escala 3. pyHanko lo
# encoge para que quepa en cada recuadro sin deformarlo.
_ANCHO_SELLO = 330.0
_ALTO_SELLO = 108.0
_LADO_QR = 108.0
_X_TEXTO = 112.0


def texto_qr(titular: str, motivo: str, lugar: str, momento: datetime) -> str:
    """El contenido del QR, con el mismo formato que FirmaEC.

    Comprobado contra un PDF firmado con FirmaEC (2026-09): «FIRMADO POR / RAZON / LOCALIZACION /
    FECHA / VALIDAR CON», una línea cada uno. La última línea dice con qué se firmó: aquí es
    CercoApp, no FirmaEC, porque decir otra cosa sería falso.
    """
    fecha = momento.astimezone(_HORA_ECUADOR).isoformat(timespec="milliseconds")
    return (
        f"FIRMADO POR: {titular}\n"
        f"RAZON: {motivo}\n"
        f"LOCALIZACION: {lugar}\n"
        f"FECHA: {fecha}\n"
        "VALIDAR CON: www.firmadigital.gob.ec\n"
        "Firmado digitalmente con CercoApp"
    )


def _latin1(texto: str) -> str:
    """Las fuentes base del PDF (Courier) solo cubren latin-1; lo demás se cambia por «?»."""
    return texto.encode("latin-1", "replace").decode("latin-1")


def sello_firmaec(titular: str, contenido_qr: str) -> bytes:
    """Una página PDF con el sello: QR a la izquierda y el texto en Courier a la derecha.

    Copia el de FirmaEC: «Validar únicamente en FirmaEC.», «Firmado electrónicamente por:» y el
    nombre en Courier negrita, más grande y partido en renglones.
    """
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=0, box_size=8)
    qr.add_data(contenido_qr)
    qr.make(fit=True)
    imagen = qr.make_image(fill_color="black", back_color="white").get_image()

    pdf = FPDF(unit="pt", format=(_ANCHO_SELLO, _ALTO_SELLO))
    pdf.set_margins(0, 0, 0)
    pdf.set_auto_page_break(False)
    pdf.add_page()
    pdf.image(imagen, x=0, y=0, w=_LADO_QR, h=_LADO_QR)

    nombre = _latin1(" ".join(str(titular or "").upper().split()) or "FIRMANTE")
    # Courier mide 0,6 del tamaño por letra: con el ancho libre se sabe cuántas caben por renglón.
    libre = _ANCHO_SELLO - _X_TEXTO
    tamano = 20.0
    renglones = textwrap.wrap(nombre, max(8, int(libre / (tamano * 0.6))))
    while len(renglones) > 3 and tamano > 12:
        tamano -= 2
        renglones = textwrap.wrap(nombre, max(8, int(libre / (tamano * 0.6))))
    pequeno = 11.0
    alto_texto = 2 * pequeno * 1.15 + len(renglones) * tamano * 1.05
    y = max(0.0, (_ALTO_SELLO - alto_texto) / 2)

    pdf.set_font("Courier", size=pequeno)
    for linea in ("Validar únicamente en FirmaEC.", "Firmado electrónicamente por:"):
        pdf.set_xy(_X_TEXTO, y)
        pdf.cell(libre, pequeno * 1.15, _latin1(linea))
        y += pequeno * 1.15
    pdf.set_font("Courier", style="B", size=tamano)
    for linea in renglones:
        pdf.set_xy(_X_TEXTO, y)
        pdf.cell(libre, tamano * 1.05, linea)
        y += tamano * 1.05
    return bytes(pdf.output())


def _estilo_desde(ruta: Path) -> StaticStampStyle:
    return StaticStampStyle.from_pdf_file(
        str(ruta),
        border_width=0,
        background_opacity=1,
        background_layout=SimpleBoxLayoutRule(
            x_align=AxisAlignment.ALIGN_MIN,
            y_align=AxisAlignment.ALIGN_MID,
            inner_content_scaling=InnerScaling.SHRINK_TO_FIT,
        ),
    )


def _nombre(nombre: Any) -> str:
    try:
        return str(nombre.native.get("common_name") or nombre.human_friendly)
    except AttributeError:
        return ""


def _firmar(
    pdf: bytes,
    certificado: bytes,
    clave: str,
    motivo: str,
    lugar: str,
    cajas: list[tuple[int, tuple[float, float, float, float]]],
) -> tuple[bytes, dict[str, Any]]:
    try:
        firmante = signers.SimpleSigner.load_pkcs12_data(
            certificado, other_certs=[], passphrase=clave.encode("utf-8")
        )
    except Exception as error:  # pyHanko/cryptography lanzan tipos distintos según la falla
        raise DatoInvalido(
            "No se pudo abrir el certificado. Revisa que sea un .p12 o .pfx y que la clave "
            "sea la correcta."
        ) from error
    if firmante is None or firmante.signing_cert is None:
        raise DatoInvalido("El archivo no trae un certificado de firma.")
    cert = firmante.signing_cert
    vence = cert["tbs_certificate"]["validity"]["not_after"].native
    if vence < datetime.now(UTC):
        raise DatoInvalido(
            f"El certificado venció el {vence.strftime('%d/%m/%Y')}. Renueva tu firma electrónica."
        )
    titular = _nombre(cert.subject)
    # El sello es el mismo en todos los recuadros: se dibuja una vez, con la hora de la firma.
    carpeta = tempfile.TemporaryDirectory(prefix="sello-")
    ruta_sello = Path(carpeta.name) / "sello.pdf"
    ruta_sello.write_bytes(
        sello_firmaec(titular, texto_qr(titular, motivo[:120], lugar[:80], datetime.now(UTC)))
    )
    estilo = _estilo_desde(ruta_sello)
    # Cada recuadro lleva su propia firma PAdES, una encima de otra como revisiones del mismo
    # archivo. Si alguien altera el documento después, todas dejan de validar.
    actual = pdf
    for numero, (pagina, caja) in enumerate(cajas, start=1):
        campo = f"FirmaElectronica{numero}"
        datos = signers.PdfSignatureMetadata(
            field_name=campo,
            reason=motivo[:120],
            location=lugar[:80] or None,
            name=titular or None,
            subfilter=fields.SigSeedSubFilter.PADES,
        )
        # pyHanko calcula la alineación con enteros: una caja con decimales rompe el diseño.
        x1, y1, x2, y2 = (round(valor) for valor in caja)
        entera = (x1, y1, x2, y2)
        firmador = PdfSigner(
            datos,
            firmante,
            stamp_style=estilo,
            # pyHanko calcula la alineación con enteros: una caja con decimales rompe el diseño.
            new_field_spec=fields.SigFieldSpec(campo, on_page=pagina, box=entera),
        )
        escritor = IncrementalPdfFileWriter(io.BytesIO(actual), strict=False)
        try:
            actual = firmador.sign_pdf(escritor).getvalue()
        except Exception:
            carpeta.cleanup()
            raise
    carpeta.cleanup()
    return actual, {
        "titular": titular,
        "emisor": _nombre(cert.issuer),
        "vence": vence.date().isoformat(),
        "serie": str(cert.serial_number),
        "firmas": len(cajas),
    }


async def firmar_pdf(
    pdf: bytes,
    certificado: bytes,
    clave: str,
    *,
    motivo: str,
    lugar: str = "",
    cajas: list[tuple[int, tuple[float, float, float, float]]] | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """Firma el PDF en cada recuadro de `cajas` (página desde 0, rectángulo en puntos).

    Sin `cajas` firma el recuadro final de la última página, como antes.
    """
    if not certificado or len(certificado) > TOPE_CERTIFICADO:
        raise DatoInvalido("El certificado debe ser un archivo .p12 o .pfx de menos de 64 KB.")
    if not clave:
        raise DatoInvalido("Escribe la clave de tu firma electrónica.")
    recuadros: list[tuple[int, tuple[float, float, float, float]]] = (
        list(cajas) if cajas else [(-1, CAJA_FIRMA)]
    )
    if len(recuadros) > MAX_RECUADROS:
        raise DatoInvalido(
            f"El documento tiene {len(recuadros)} recuadros de firma y el tope es {MAX_RECUADROS}."
        )
    async with _TURNOS:
        return await asyncio.to_thread(_firmar, pdf, certificado, clave, motivo, lugar, recuadros)
