"""La proforma sigue el modelo del SOCE: datos del proveedor, ítems con CPC y vigencia."""

from __future__ import annotations

import io
from typing import Any

from pypdf import PdfReader

from contratacion.dominio.documentos import calcular_proforma, items_pedidos
from contratacion.dominio.oferta import datos_empresa
from contratacion.infraestructura.adaptadores.salida.proforma_pdf import armar_proforma

ITEMS = [
    {
        "numero": 1,
        "codigo": "462110912",
        "descripcion_cpc": "OTROS APARATOS ELECTRICOS",
        "descripcion": "Contactores ABB, modelo AF 12",
        "unidad": "Unidad",
        "cantidad": "6.00",
    },
    {
        "numero": 2,
        "codigo": "462120015",
        "descripcion_cpc": "FUSIBLES",
        "descripcion": "Fusibles de barril de 10 amperios",
        "unidad": "Unidad",
        "cantidad": "6.00",
    },
]


def _texto(contenido: bytes) -> str:
    return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(contenido)).pages)


def _documento(impuesto: float) -> dict[str, Any]:
    lineas = [
        {
            "descripcion": i["descripcion"],
            "cantidad": 6,
            "unidad": "Unidad",
            "precio_unitario": 100,
            "cpc": i["codigo"],
            "cpc_nombre": i["descripcion_cpc"],
        }
        for i in ITEMS
    ]
    cifras = calcular_proforma(lineas, impuesto)
    return {
        "tipo": "proforma",
        "titulo": "Proforma",
        "entidad": "Refinería del Pacífico",
        "objeto": "Repuestos para switchgear",
        "lineas": cifras["lineas"],
        "cifras": cifras,
        "extras": {
            "fecha": "10/11/2026",
            "codigo": "NIC-1792157781001-2026-00038",
            "empresa": datos_empresa(
                {
                    "razon_social": "Arias Rengifo Renato",
                    "ruc": "1718613639001",
                    "email_contacto": "r@x.ec",
                    "telefono": "0983894300",
                    "direccion": "Av. Atahualpa",
                    "ciudad": "Quito",
                    "cobertura": [
                        {"provincia": "Guayas", "canton": "Guayaquil"},
                        {"provincia": "Pichincha", "canton": "Quito"},
                    ],
                }
            ),
            "condiciones": {
                "validez": "45 días",
                "plazo_entrega": "15 días",
                "forma_pago": "Contra entrega",
            },
        },
    }


def test_los_items_de_la_entidad_se_convierten_en_lineas() -> None:
    pedidos = items_pedidos([*ITEMS, {"numero": 3}, "basura"])
    assert [p["cpc"] for p in pedidos] == ["462110912", "462120015"]
    assert pedidos[0]["cantidad"] == 6.0
    assert pedidos[0]["cpc_nombre"] == "OTROS APARATOS ELECTRICOS"
    assert items_pedidos(None) == []


def test_el_cpc_viaja_con_la_linea_calculada() -> None:
    cifras = calcular_proforma(
        [{"descripcion": "Fusible", "cantidad": 2, "precio_unitario": 5, "cpc": "462120015"}], 0
    )
    assert cifras["lineas"][0]["cpc"] == "462120015"
    assert cifras["total"] == 10


def test_provincia_y_canton_salen_del_perfil() -> None:
    empresa = _documento(0)["extras"]["empresa"]
    assert empresa["provincia"] == "Pichincha"  # la del cantón de la ciudad, no la primera
    assert empresa["canton"] == "Quito" and empresa["pais"] == "ECUADOR"


def test_el_pdf_sigue_el_modelo_del_soce() -> None:
    pdf, _ = armar_proforma(_documento(0))
    texto = _texto(pdf)
    for esperado in (
        "Datos del Proveedor",
        "Detalle del objeto de compra",
        "Valor Unitario",
        "Valor Total",
        "462110912",
        "Contactores ABB",
        "TOTAL:",
        "Vigencia de la Proforma",
        "(días calendario)",
        "PICHINCHA",
        "Documentos Anexos",
        "ARCHIVO PARA ADJUNTAR SU PROFORMA",
        "600.00000",
        "NIC-1792157781001-2026-00038",
    ):
        assert esperado in texto, esperado
    assert "SUBTOTAL" not in texto  # con IVA 0 % solo se imprime el TOTAL, como el SOCE


def test_con_iva_se_desglosa() -> None:
    texto = _texto(armar_proforma(_documento(15))[0])
    assert "SUBTOTAL:" in texto and "IVA 15 %:" in texto and "1380.00000" in texto
