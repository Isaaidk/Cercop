"""Borrador de oferta: plantilla, faltantes y limpieza de lo que devuelve la IA."""

from __future__ import annotations

import re
import zlib

from contratacion.dominio.oferta import (
    borrador_plantilla,
    datos_empresa,
    faltantes,
    limpiar_respuesta,
)
from contratacion.infraestructura.adaptadores.salida.oficina import parrafos_de, pdf
from contratacion.infraestructura.adaptadores.salida.proforma_pdf import pdf_ficha, pdf_proforma

PERFIL = {
    "razon_social": "SERVIANDES CIA. LTDA.",
    "ruc": "1792345678001",
    "email_contacto": "ventas@serviandes.ec",
    "telefono": "02 245 6789",
    "direccion": "Av. 10 de Agosto",
    "ciudad": "Quito",
    "contactos": [
        {
            "tipo": "representante_legal",
            "nombre": "María Andrade",
            "cargo": "Gerente",
            "principal": True,
        }
    ],
    "ofertas": [
        {"tipo": "producto", "nombre": "Combustible diésel", "descripcion": "Despacho a domicilio"},
        {"tipo": "servicio", "nombre": "Limpieza de oficinas", "descripcion": "Diaria"},
    ],
    "experiencia": [
        {"entidad": "GAD Rumiñahui", "objeto": "Abastecimiento de combustible", "anio": 2025}
    ],
}
SECCIONES = {
    "objeto": "Servicio de abastecimiento de combustible diésel para la flota.",
    "plazos": "El plazo de entrega es de 30 días desde la orden de compra.",
    "condiciones": "El pago se realizará contra entrega, previa factura.",
}


def test_cada_requisito_del_tdr_sale_respondido() -> None:
    from contratacion.dominio.documentos import contrastar
    from contratacion.dominio.oferta import responder_requisito

    plazo = "Aceptación expresa del plazo de ejecución y de las condiciones de entrega estipuladas."
    no_aplica = (
        "Cumplimiento del personal técnico mínimo, cuando aplique. N/A El Artesano debe "
        "presentar el carnet artesanal."
    )
    condiciones = {"plazo_entrega": "10 días", "lugar_entrega": "la entidad"}
    assert "10 días" in responder_requisito(
        plazo, condiciones=condiciones, empresa={"razon_social": "Serviandes"}, perfil={}
    )
    assert responder_requisito(
        no_aplica, condiciones=condiciones, empresa={}, perfil={}
    ).startswith("No aplica")
    campo = responder_requisito(
        'OBJETO DE LA CONTRATACIÓN: "ADQUISICIÓN DE MATERIALES"',
        condiciones=condiciones,
        empresa={"razon_social": "Isaac y asociados"},
        perfil={},
    )
    assert campo == (
        "Isaac y asociados cumple con lo que el TDR establece en «Objeto de la contratación»."
    )
    respuesta = responder_requisito(plazo, condiciones=condiciones, empresa={}, perfil={})
    resultado = contrastar(
        [plazo],
        [{"descripcion": "Mantenimiento", "precio_unitario": 10}],
        cumplimiento=[{"requisito": plazo, "como_cumple": respuesta}],
    )
    assert resultado["no_cubiertos"] == []


def test_plantilla_usa_catalogo_que_el_tdr_menciona() -> None:
    borrador = borrador_plantilla(
        secciones=SECCIONES, perfil=PERFIL, entidad="GAD Quito", objeto=""
    )
    descripciones = [linea["descripcion"] for linea in borrador["lineas"]]
    assert any("diésel" in texto for texto in descripciones)
    assert not any("Limpieza" in texto for texto in descripciones)
    assert all(linea["precio_unitario"] is None for linea in borrador["lineas"])
    assert "30 días" in borrador["condiciones"]["plazo_entrega"]
    assert "contra entrega" in borrador["condiciones"]["forma_pago"]
    assert "1792345678001" in borrador["carta"]
    assert borrador["faltantes"] == []


def test_sin_datos_no_inventa_y_lista_faltantes() -> None:
    borrador = borrador_plantilla(secciones={}, perfil={}, entidad="", objeto="Toner")
    assert borrador["empresa"] == {}
    assert borrador["lineas"][0]["descripcion"] == "Toner"
    etiquetas = {f["etiqueta"] for f in faltantes({})}
    assert {"RUC", "Correo de contacto", "Representante legal"} <= etiquetas


def test_datos_empresa_omite_lo_vacio() -> None:
    assert "sitio_web" not in datos_empresa(PERFIL)
    assert datos_empresa(PERFIL)["representante"] == "María Andrade"


def test_limpieza_quita_precios_y_respeta_identidad() -> None:
    base = borrador_plantilla(secciones=SECCIONES, perfil=PERFIL, entidad="GAD", objeto="")
    respuesta = {
        "carta": "Ofrecemos todo por $ 1.500,00 USD.",
        "lineas": [
            {
                "descripcion": "Diésel premium a 3 dólares",
                "cantidad": "200",
                "unidad": "galón",
                "precio_unitario": 2.5,
            }
        ],
        "plazo_entrega": "5 días",
        "cumplimiento": [{"requisito": "RUC activo", "como_cumple": "RUC 1792345678001 activo"}],
        "faltantes": ["Certificado de calidad"],
        "empresa": {"ruc": "9999999999999"},
    }
    limpio = limpiar_respuesta(respuesta, base, modelo="prueba")
    assert "1.500" not in limpio["carta"]
    assert limpio["lineas"][0]["precio_unitario"] is None
    assert limpio["lineas"][0]["cantidad"] == 200
    assert limpio["empresa"]["ruc"] == "1792345678001"
    assert limpio["condiciones"]["plazo_entrega"] == "5 días"
    assert any(f["etiqueta"] == "Certificado de calidad" for f in limpio["faltantes"])


def test_documento_impreso_omite_vacios_y_envuelve_texto() -> None:
    documento = {
        "titulo": "Proforma",
        "tipo": "proforma",
        "entidad": "GAD Quito",
        "objeto": "",
        "contacto": "",
        "lineas": [
            {
                "descripcion": "Diésel",
                "cantidad": 2,
                "unidad": "galón",
                "precio_unitario": 3,
                "subtotal": 6,
            }
        ],
        "cifras": {"subtotal": 6, "impuesto": 0.9, "impuesto_porcentaje": 15, "total": 6.9},
        "extras": {
            "empresa": datos_empresa(PERFIL),
            "carta": "palabra " * 80,
            "condiciones": {"plazo_entrega": "5 días", "garantia": ""},
        },
    }
    texto = parrafos_de(documento)
    assert "Objeto: —" not in texto and not any(t.startswith("Objeto:") for t in texto)
    assert "Plazo de entrega: 5 días" in texto
    assert not any(t.startswith("Garantía") for t in texto)
    assert "1. Diésel — 2 galón x $ 3.00 = $ 6.00" in texto
    assert pdf(texto).startswith(b"%PDF-1.4")


def _texto_pdf(contenido: bytes) -> str:
    flujos = re.findall(rb"stream\r?\n(.*?)\r?\nendstream", contenido, re.S)
    return b"".join(zlib.decompress(f) for f in flujos).decode("latin-1")


def test_cotizacion_y_ficha_salen_con_su_titulo_y_numeradas() -> None:
    base = {
        "entidad": "GAD Quito",
        "objeto": "Compra de tóner",
        "contacto": "",
        "extras": {
            "empresa": datos_empresa(PERFIL),
            "cumplimiento": [{"requisito": "Entrega en 5 días", "como_cumple": "Aceptamos"}],
        },
    }
    cotizacion = _texto_pdf(
        pdf_proforma(
            {
                **base,
                "tipo": "cotizacion",
                "lineas": [
                    {"descripcion": "Tóner", "cantidad": 1, "precio_unitario": 2, "subtotal": 2}
                ],
                "cifras": {"subtotal": 2, "impuesto": 0.3, "impuesto_porcentaje": 15, "total": 2.3},
            }
        )
    )
    assert "COTIZACI" in cotizacion and "(R1)" in cotizacion
    assert "Firma" in cotizacion  # columna de firma por requisito
    # Las comillas tipográficas del TDR no caben en Helvetica: se imprimen como comillas normales.
    con_comillas = _texto_pdf(
        pdf_proforma(
            {
                **base,
                "tipo": "proforma",
                "objeto": "\u201ctoner\u201d \u2014 nuevo",
            }
        )
    )
    assert '"toner"' in con_comillas

    ficha = {
        **base,
        "tipo": "ficha",
        "lineas": [
            {
                "nombre": "Tóner HP",
                "marca": "HP",
                "pais_origen": "México",
                "especificaciones": [
                    {"requerido": "Rendimiento 3000 páginas", "ofertado": "3100 páginas"},
                    {"requerido": "Original", "ofertado": ""},
                ],
            }
        ],
    }
    impresa = _texto_pdf(pdf_ficha(ficha))
    assert "FICHA T" in impresa and "(E2)" in impresa and "Pendiente" in impresa
    assert any(t.startswith("E1. Requerido") for t in parrafos_de(ficha))
