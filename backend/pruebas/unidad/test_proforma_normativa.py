"""La proforma sale completa, verificada y firmada en cada recuadro."""

from __future__ import annotations

import asyncio
import io
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, pkcs12
from cryptography.x509.oid import NameOID
from pypdf import PdfReader

from contratacion.dominio.documentos import checklist, extraer_campos, extraer_secciones
from contratacion.dominio.errores import DatoInvalido
from contratacion.dominio.oferta import borrador_plantilla
from contratacion.dominio.verificacion import ruc_valido, verificar_proforma
from contratacion.infraestructura.adaptadores.salida.firma import firmar_pdf
from contratacion.infraestructura.adaptadores.salida.proforma_pdf import armar_proforma

_FORMULARIO = (
    "FECHA: 29 de octubre del 2026 ÁREA REQUIRENTE: Dirección de Operaciones NÚMERO: "
    "ATD-DO-ET-2026-009 PROCEDIMIENTO DE CONTRATACIÓN: ÍNFIMA CUANTÍA 1. R2 OBJETO DE LA "
    'CONTRATACIÓN: "ADQUISICIÓN DE MATERIALES PARA IMPRONTAS". R3 DESCRIPCIÓN DE CPC: 3699. '
    "PLAZO DE ENTREGA: 15 días calendario. FORMA DE PAGO: contra entrega, 100 % con factura. "
    "LUGAR DE ENTREGA: Bodega central, Quito. GARANTÍA: 12 meses. "
    "VIGENCIA DE LA PROFORMA: 30 días. CANTIDAD: 20 unidades."
)

_EMPRESA = {
    "razon_social": "Isaac y Asociados S.A.",
    "ruc": "1792146739001",
    "representante": "Isaac Pérez",
    "email": "ventas@isaac.ec",
    "telefono": "0999999999",
    "direccion": "Av. Amazonas N31",
    "ciudad": "Quito",
}


def _proforma(**cambios: object) -> dict[str, Any]:
    base = {
        "tipo": "proforma",
        "titulo": "Proforma",
        "entidad": "Agencia de Tránsito",
        "objeto": "Materiales para improntas",
        "impuesto_porcentaje": 15,
        "lineas": [
            {
                "descripcion": "Tinta",
                "cantidad": 2,
                "unidad": "unidad",
                "precio_unitario": 10,
                "subtotal": 20,
            }
        ],
        "cifras": {"subtotal": 20, "impuesto": 3, "impuesto_porcentaje": 15, "total": 23},
        "extras": {
            "empresa": _EMPRESA,
            "fecha": "10/11/2026",
            "codigo": "NCO-0001-2026",
            "condiciones": {
                "validez": "30 días",
                "plazo_entrega": "15 días",
                "forma_pago": "contra entrega",
                "lugar_entrega": "Quito",
                "garantia": "12 meses",
            },
            "cumplimiento": [
                {"requisito": f"Requisito número {n}", "como_cumple": "Se acepta."}
                for n in range(1, 4)
            ],
        },
    }
    return {**base, **cambios}


def test_el_formulario_aplanado_se_separa_en_campos() -> None:
    campos = extraer_campos(_FORMULARIO)
    assert campos["objeto"] == "ADQUISICIÓN DE MATERIALES PARA IMPRONTAS"
    assert campos["plazo_entrega"] == "15 días calendario"
    assert campos["forma_pago"] == "contra entrega, 100 % con factura"
    assert campos["lugar_entrega"] == "Bodega central, Quito"
    assert campos["garantia"] == "12 meses"
    assert campos["vigencia_proforma"] == "30 días"
    assert campos["cantidad"] == "20 unidades"
    assert campos["numero"] == "ATD-DO-ET-2026-009"
    assert "fecha" not in campos


def test_una_etiqueta_en_medio_de_una_frase_no_es_un_campo() -> None:
    prosa = "El contratista cumplirá el plazo de entrega: f) personal; y la forma de pago: g)."
    assert extraer_campos(prosa) == {}
    assert extraer_campos("Texto previo\nPlazo de entrega: 10 días")["plazo_entrega"] == "10 días"


def test_un_texto_sin_etiquetas_no_inventa_campos() -> None:
    assert extraer_campos("Texto corrido sin ningún formulario ni nada parecido.") == {}


def test_el_formulario_aplanado_da_secciones_y_requisitos() -> None:
    secciones = extraer_secciones(_FORMULARIO)
    assert secciones["plazo_entrega"].startswith("15 días")
    textos = checklist(secciones)
    assert any(t.startswith("Forma de pago:") for t in textos)
    assert any(t.startswith("Plazo de entrega:") for t in textos)


def test_el_borrador_toma_las_condiciones_del_formulario() -> None:
    borrador = borrador_plantilla(
        secciones=extraer_secciones(_FORMULARIO), perfil={}, entidad="ANT", objeto=""
    )
    condiciones = borrador["condiciones"]
    assert condiciones["plazo_entrega"] == "15 días calendario"
    assert condiciones["forma_pago"].startswith("contra entrega")
    assert condiciones["validez"] == "30 días"


def test_ruc() -> None:
    assert ruc_valido("1792146739001")
    assert not ruc_valido("1792146739")
    assert not ruc_valido("1792146739000")
    assert not ruc_valido("9992146739001")
    assert not ruc_valido("17921467390AB")


def test_una_proforma_completa_esta_lista() -> None:
    revision = verificar_proforma(_proforma())
    assert revision["estado"] == "lista", revision["errores"]
    assert revision["errores"] == []


def test_lo_que_falta_se_dice_y_bloquea() -> None:
    extras = _proforma()["extras"]
    extras = {
        **extras,
        "empresa": {**_EMPRESA, "ruc": "123"},
        "condiciones": {"validez": "30 días"},
    }
    revision = verificar_proforma(_proforma(extras=extras, entidad=""))
    codigos = {fila["codigo"] for fila in revision["errores"]}
    assert {"ruc", "entidad", "plazo_entrega", "forma_pago"} <= codigos
    assert revision["estado"] == "incompleta"


def test_precio_cero_e_iva_raro() -> None:
    lineas = [{"descripcion": "Tinta", "cantidad": 1, "unidad": "u", "precio_unitario": 0}]
    revision = verificar_proforma(
        _proforma(
            lineas=lineas,
            cifras={"subtotal": 0, "impuesto": 0, "impuesto_porcentaje": 12, "total": 0},
        )
    )
    assert any(f["codigo"] == "precio" for f in revision["errores"])
    assert any(f["codigo"] == "iva" for f in revision["avisos"])


def test_el_pdf_deja_un_recuadro_por_requisito_mas_el_final_y_el_anexo() -> None:
    contenido, cajas = armar_proforma(_proforma())
    # 3 requisitos + firma final + formulario de integridad.
    assert len(cajas) == 5
    texto = "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(contenido)).pages)
    assert "PERFIL DE INTEGRIDAD" in texto
    assert "NCO-0001-2026" in texto
    for pagina, (x1, y1, x2, y2) in cajas:
        assert 0 <= pagina < len(PdfReader(io.BytesIO(contenido)).pages)
        assert 0 <= x1 < x2 <= 595 and 0 <= y1 < y2 <= 842


def test_la_cotizacion_y_el_apagado_no_llevan_el_anexo() -> None:
    _, con = armar_proforma(_proforma())
    _, cotizacion = armar_proforma(_proforma(tipo="cotizacion"))
    _, apagado = armar_proforma(_proforma(extras={**_proforma()["extras"], "integridad": False}))
    assert len(cotizacion) == len(apagado) == len(con) - 1


def _certificado(dias: int = 30) -> bytes:
    llave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nombre = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "MARIA FERNANDA ANDRADE")])
    ahora = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(nombre)
        .issuer_name(nombre)
        .public_key(llave.public_key())
        .serial_number(1)
        .not_valid_before(ahora - timedelta(days=1))
        .not_valid_after(ahora + timedelta(days=dias))
        .sign(llave, hashes.SHA256())
    )
    return pkcs12.serialize_key_and_certificates(
        b"p", llave, cert, None, BestAvailableEncryption(b"clave")
    )


def test_cada_recuadro_queda_firmado() -> None:
    contenido, cajas = armar_proforma(_proforma())
    firmado, datos = asyncio.run(
        firmar_pdf(contenido, _certificado(), "clave", motivo="Oferta", cajas=cajas)
    )
    assert datos["firmas"] == len(cajas) == 5
    lector = PdfReader(io.BytesIO(firmado))
    campos = lector.get_fields() or {}
    firmas = [n for n in campos if n.startswith("FirmaElectronica")]
    assert len(firmas) == 5
    # Cada firma está en la página de su recuadro.
    paginas = {
        anot.get_object().get("/T"): indice
        for indice, pagina in enumerate(lector.pages)
        for anot in pagina.get("/Annots") or []
        if anot.get_object().get("/FT") == "/Sig"
    }
    assert sorted(paginas.values()) == sorted(p for p, _ in cajas)


def test_la_clave_equivocada_no_firma() -> None:
    contenido, cajas = armar_proforma(_proforma())
    with pytest.raises(DatoInvalido):
        asyncio.run(firmar_pdf(contenido, _certificado(), "otra", motivo="x", cajas=cajas))


def test_un_certificado_vencido_no_firma() -> None:
    contenido, cajas = armar_proforma(_proforma())
    with pytest.raises(DatoInvalido):
        asyncio.run(firmar_pdf(contenido, _certificado(dias=-1), "clave", motivo="x", cajas=cajas))
