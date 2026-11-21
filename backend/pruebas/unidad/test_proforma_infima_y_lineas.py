"""Modelo de proforma de ínfima, páginas finales opcionales, líneas fieles al TDR y modelo de IA.

El cliente reclamó que la cotización «se inventa» y no sale de los TDR: aquí se fija que las líneas
sean solo los ítems publicados (ficha o tabla del TDR), con su cantidad y unidad, y que la IA no
pueda agregar, quitar ni cambiar nada.
"""

from __future__ import annotations

import io
import zipfile
from typing import Any

import pytest
from pypdf import PdfReader

from contratacion.dominio.documentos import calcular_proforma, items_pedidos
from contratacion.dominio.lineas import items_de_tdr, lineas_de_fuente, validar_lineas
from contratacion.dominio.oferta import borrador_plantilla, limpiar_respuesta
from contratacion.dominio.paginas_finales import (
    ADHIERE,
    paginas_activas,
    totales_iva,
)
from contratacion.dominio.verificacion import verificar_proforma
from contratacion.infraestructura.adaptadores.salida.ia import ModeloIa
from contratacion.infraestructura.adaptadores.salida.oficina import docx_documento
from contratacion.infraestructura.adaptadores.salida.proforma_pdf import armar_proforma

CPC = "369900011"
# Una ínfima de ferretería: todos los ítems con el mismo CPC y cantidades distintas.
FICHA = [
    {"numero": 1, "codigo": CPC, "descripcion_cpc": "ARTICULOS DE FERRETERIA",
     "descripcion": 'BROCHA 4"', "unidad": "UNIDAD", "cantidad": "10.00"},
    {"numero": 2, "codigo": CPC, "descripcion_cpc": "ARTICULOS DE FERRETERIA",
     "descripcion": "FLEXOMETRO 5 MTS", "unidad": "UNIDAD", "cantidad": "3.00"},
    {"numero": 3, "codigo": CPC, "descripcion_cpc": "ARTICULOS DE FERRETERIA",
     "descripcion": "CINTA AISLANTE 3M", "unidad": "ROLLO", "cantidad": "12.00"},
    {"numero": 4, "codigo": CPC, "descripcion_cpc": "ARTICULOS DE FERRETERIA",
     "descripcion": "LIJA DE AGUA N° 100", "unidad": "UNIDAD", "cantidad": "25.00"},
]  # fmt: skip

TDR_CON_TABLA = """### Términos de referencia: TDR ferreteria.pdf
6. OBJETO
Adquisición de materiales de ferretería para mantenimiento.
7. PRODUCTOS O SERVICIOS ESPERADOS
N° DESCRIPCIÓN UNIDAD CANTIDAD
1 BROCHA 4" UNIDAD 10
2 FLEXOMETRO 5 MTS UNIDAD 3
3 CINTA AISLANTE 3M ROLLO 12
4 LIJA DE AGUA N° 100 UNIDAD 25
TOTAL
8. FORMA DE PAGO
Contra entrega."""


def test_items_de_la_ficha_pasan_tal_cual() -> None:
    lineas = lineas_de_fuente(items_pedidos(FICHA), "")
    assert [(x["descripcion"], x["cantidad"], x["unidad"]) for x in lineas] == [
        ('BROCHA 4"', 10, "UNIDAD"),
        ("FLEXOMETRO 5 MTS", 3, "UNIDAD"),
        ("CINTA AISLANTE 3M", 12, "ROLLO"),
        ("LIJA DE AGUA N° 100", 25, "UNIDAD"),
    ]
    assert {x["cpc"] for x in lineas} == {CPC}
    assert all(x["origen"] == "ficha" and x["precio_unitario"] is None for x in lineas)


def test_tabla_de_productos_del_tdr() -> None:
    filas = items_de_tdr(TDR_CON_TABLA)
    assert [(f["descripcion"], f["unidad"], f["cantidad"]) for f in filas] == [
        ('BROCHA 4"', "UNIDAD", 10),
        ("FLEXOMETRO 5 MTS", "UNIDAD", 3),
        ("CINTA AISLANTE 3M", "ROLLO", 12),
        ("LIJA DE AGUA N° 100", "UNIDAD", 25),
    ]
    assert [x["origen"] for x in lineas_de_fuente([], TDR_CON_TABLA)] == ["tdr"] * 4


def test_tabla_con_cantidad_antes_de_la_unidad() -> None:
    texto = (
        "ÍTEM DESCRIPCIÓN CANTIDAD UNIDAD DE MEDIDA\n"
        "1 Pintura látex blanca 4 GALONES\n"
        "2 Rodillo de felpa 9 pulgadas 2 UNIDADES\n"
        "SUBTOTAL"
    )
    filas = items_de_tdr(texto)
    assert [(f["descripcion"], f["cantidad"], f["unidad"]) for f in filas] == [
        ("Pintura látex blanca", 4, "GALONES"),
        ("Rodillo de felpa 9 pulgadas", 2, "UNIDADES"),
    ]


def test_sin_tabla_no_se_adivinan_items() -> None:
    assert items_de_tdr("El contratista entregará 10 brochas y 3 flexómetros.") == []


def test_la_ia_no_agrega_ni_cambia_cantidades_de_la_ficha() -> None:
    fuente = lineas_de_fuente(items_pedidos(FICHA), "")
    propuestas = [
        # Reordenadas, con cantidades cambiadas, unidad distinta y un ítem que nadie pidió.
        {"descripcion": "Flexómetro de 5 metros", "cantidad": 30, "unidad": "caja"},
        {"descripcion": 'Brocha 4"', "cantidad": 1, "unidad": "global"},
        {"descripcion": "Guantes de cuero", "cantidad": 50, "unidad": "par"},
        {"descripcion": "Lija de agua N° 100", "cantidad": 2, "unidad": "unidad"},
    ]
    lineas, descartadas = validar_lineas(propuestas, fuente, "")
    assert [(x["descripcion"], x["cantidad"], x["unidad"]) for x in lineas] == [
        (x["descripcion"], x["cantidad"], x["unidad"]) for x in fuente
    ]
    # Lo que no corresponde con seguridad a un ítem publicado se descarta (y se avisa); las líneas
    # siguen siendo las publicadas.
    assert "Guantes de cuero" in descartadas
    assert 'Brocha 4"' not in descartadas


def test_limpiar_respuesta_con_ficha_restaura_lo_publicado() -> None:
    base = borrador_plantilla(
        secciones={"objeto": "Materiales de ferretería"},
        perfil={},
        entidad="GAD",
        objeto="",
        items=items_pedidos(FICHA),
    )
    assert base["fuente_lineas"] == "ficha"
    respuesta = {
        "lineas": [
            {"descripcion": "Brocha de 4 pulgadas premium", "cantidad": 100, "unidad": "caja"},
            {"descripcion": "Taladro percutor", "cantidad": 1, "unidad": "unidad"},
        ]
    }
    limpio = limpiar_respuesta(respuesta, base, modelo="prueba")
    assert [x["cantidad"] for x in limpio["lineas"]] == [10, 3, 12, 25]
    assert "Taladro percutor" in limpio["lineas_descartadas"]
    assert all(x["precio_unitario"] is None for x in limpio["lineas"])


def test_sin_fuente_solo_queda_lo_que_el_tdr_respalda() -> None:
    texto = "Se requiere el servicio de fumigación de 3 bodegas institucionales."
    lineas, descartadas = validar_lineas(
        [
            {"descripcion": "Fumigación de bodegas institucionales", "cantidad": 3, "unidad": ""},
            {"descripcion": "Desratización de oficinas centrales", "cantidad": 8},
        ],
        [],
        texto,
    )
    assert [x["descripcion"] for x in lineas] == ["Fumigación de bodegas institucionales"]
    assert lineas[0]["cantidad"] == 3 and lineas[0]["verificar"] == ["unidad"]
    assert descartadas == ["Desratización de oficinas centrales"]


def test_el_origen_de_la_linea_se_guarda() -> None:
    cifras = calcular_proforma(
        [
            {"descripcion": "Brocha", "cantidad": 10, "precio_unitario": 2, "origen": "ficha"},
            {"descripcion": "Otro", "cantidad": 1, "precio_unitario": 1, "origen": "inventado"},
        ],
        15,
    )
    assert cifras["lineas"][0]["origen"] == "ficha"
    assert "origen" not in cifras["lineas"][1]


# --- Formato de ínfima y páginas finales ------------------------------------------------------


def _documento(**extras: Any) -> dict[str, Any]:
    lineas = [
        {**linea, "precio_unitario": precio}
        for linea, precio in zip(
            lineas_de_fuente(items_pedidos(FICHA), ""), (2.5, 7.8, 1.125, 0.45), strict=True
        )
    ]
    cifras = calcular_proforma(lineas, 15)
    return {
        "tipo": "proforma",
        "titulo": "Proforma",
        "entidad": "Fundación Museos de la Ciudad",
        "objeto": "Adquisición de materiales de ferretería",
        "lineas": cifras["lineas"],
        "cifras": cifras,
        "extras": {
            "fecha": "21/11/2026",
            "codigo": "NIC-1768152560001-2026-00012",
            "entidad": {"ruc": "1768152560001", "direccion": "García Moreno N1-47, Quito"},
            "empresa": {
                "razon_social": "FERRETERÍA EL CLAVO S.A.",
                "ruc": "1792345678001",
                "telefono": "02 245 6789",
                "direccion": "Av. 10 de Agosto",
                "ciudad": "Quito",
                "email": "ventas@elclavo.ec",
                "representante": "María Andrade",
            },
            "condiciones": {"validez": "30 días", "garantia": "6 meses contra defectos"},
            "alcance": "Entrega de 4 ítems de ferretería.",
            "cumplimiento": [{"requisito": "Entrega en bodega", "como_cumple": "Cumplimos."}],
            **extras,
        },
    }


def _paginas(contenido: bytes) -> list[str]:
    return [p.extract_text() or "" for p in PdfReader(io.BytesIO(contenido)).pages]


def test_primera_pagina_sigue_el_modelo_de_la_entidad() -> None:
    pdf, cajas = armar_proforma(_documento())
    primera = _paginas(pdf)[0]
    for esperado in (
        "PROFORMA",
        "Cliente:",
        "FUNDACIÓN MUSEOS DE LA CIUDAD",
        "1768152560001",
        "Proveedor (Razón Social):",
        "Correo electrónico:",
        "N°",
        "DESCRIPCIÓN",
        "UNIDAD DE MEDIDA",
        "VALOR UNITARIO",
        "VALOR TOTAL",
        "BASE IMPONIBLE 15%",
        "BASE IMPONIBLE 0%",
        "IVA 15%",
        "TOTAL",
        "Forma de Pago:",
        "Vigencia de la Oferta:",
        "Plazo de entrega:",
        "Garantía:",
        "Lugar de entrega:",
        "Atentamente",
        "Firma electrónica del oferente",
        'BROCHA 4"',
        "$ 1.125",
    ):
        assert esperado in primera, esperado
    # El CPC y el cumplimiento no ensucian la primera página.
    assert CPC not in primera and "CUMPLIMIENTO" not in primera
    # Sin forma de pago, plazo ni lugar, la frase del modelo.
    assert primera.count(ADHIERE) == 3
    assert cajas[0][0] == 0


def test_paginas_finales_opcionales() -> None:
    nada = dict.fromkeys(("respaldo", "cumplimiento", "declaracion", "integridad"), False)
    pdf, cajas = armar_proforma(_documento(paginas_finales=nada))
    assert len(_paginas(pdf)) == 1 and len(cajas) == 1

    pdf, cajas = armar_proforma(_documento(paginas_finales={**nada, "compromiso": True}))
    paginas = _paginas(pdf)
    assert len(paginas) == 2
    assert "CARTA DE COMPROMISO" in paginas[1] and "por mis propios derechos" in paginas[1]
    assert "FERRETERÍA EL CLAVO S.A. con RUC: 1792345678001" in paginas[1]
    assert len(cajas) == 2 and cajas[1][0] == 1

    todo = "\n".join(_paginas(armar_proforma(_documento())[0]))
    for esperado in (
        "DOCUMENTO DE RESPALDO",
        CPC,
        "Entrega de 4 ítems",
        "CUMPLIMIENTO DE LOS TÉRMINOS DE REFERENCIA",
        "DECLARACIÓN DEL OFERENTE",
        "FORMULARIO DE PERFIL DE INTEGRIDAD",
    ):
        assert esperado in todo, esperado
    assert "CARTA DE COMPROMISO" not in todo  # apagada por defecto


def test_paginas_por_defecto_y_compatibilidad() -> None:
    assert paginas_activas({"tipo": "proforma"}) == {
        "respaldo": True,
        "cumplimiento": True,
        "declaracion": True,
        "compromiso": False,
        "integridad": True,
    }
    assert not paginas_activas({"tipo": "proforma", "extras": {"integridad": False}})["integridad"]
    cotizacion = paginas_activas(
        {"tipo": "cotizacion", "extras": {"paginas_finales": {"compromiso": True}}}
    )
    assert not cotizacion["compromiso"] and not cotizacion["integridad"]


def test_totales_con_y_sin_iva() -> None:
    con = dict(totales_iva({"subtotal": 100, "impuesto": 15, "impuesto_porcentaje": 15}))
    assert con == {
        "SUBTOTAL": 100,
        "BASE IMPONIBLE 15%": 100,
        "BASE IMPONIBLE 0%": 0,
        "IVA 15%": 15,
        "TOTAL": 115,
    }
    sin = dict(totales_iva({"subtotal": 100, "impuesto": 0, "impuesto_porcentaje": 0}))
    assert sin["BASE IMPONIBLE 15%"] == 0 and sin["BASE IMPONIBLE 0%"] == 100
    assert sin["TOTAL"] == 100


def test_el_formato_soce_sigue_disponible() -> None:
    texto = "\n".join(_paginas(armar_proforma(_documento(formato_proforma="soce"))[0]))
    assert "Datos del Proveedor" in texto and "Detalle del objeto de compra" in texto


def test_word_con_el_modelo_y_las_paginas_elegidas() -> None:
    contenido = docx_documento(_documento(paginas_finales={"compromiso": True}))
    with zipfile.ZipFile(io.BytesIO(contenido)) as archivo:
        xml = archivo.read("word/document.xml").decode("utf-8")
    for esperado in (
        "Proveedor (Razón Social):",
        "UNIDAD DE MEDIDA",
        "BASE IMPONIBLE 0%",
        "Atentamente,",
        "CARTA DE COMPROMISO",
        "FORMULARIO DE PERFIL DE INTEGRIDAD",
        "w:tbl",
    ):
        assert esperado in xml, esperado
    sin = docx_documento(_documento(paginas_finales={"integridad": False, "respaldo": False}))
    with zipfile.ZipFile(io.BytesIO(sin)) as archivo:
        xml = archivo.read("word/document.xml").decode("utf-8")
    assert "PERFIL DE INTEGRIDAD" not in xml and "DOCUMENTO DE RESPALDO" not in xml


def test_totales_con_precios_de_tres_decimales_no_bloquean_la_firma() -> None:
    lineas = [
        {"descripcion": f"Ítem {n}", "cantidad": 1, "precio_unitario": 1.125, "unidad": "U"}
        for n in range(6)
    ]
    cifras = calcular_proforma(lineas, 15)
    documento = {"tipo": "proforma", "lineas": cifras["lineas"], "cifras": cifras, "extras": {}}
    codigos = {h["codigo"] for h in verificar_proforma(documento)["errores"]}
    assert "totales" not in codigos
    alterado = {**documento, "cifras": {**cifras, "subtotal": cifras["subtotal"] + 1}}
    assert "totales" in {h["codigo"] for h in verificar_proforma(alterado)["errores"]}


# --- Modelo de IA por uso -----------------------------------------------------------------------


def _modelo(**opciones: Any) -> ModeloIa:
    return ModeloIa(
        url="https://api.deepseek.com",
        clave="",
        modelo="deepseek-flash",
        concurrencia=1,
        tiempo_seg=30,
        **opciones,
    )


def test_modelo_y_modo_pensar_por_uso() -> None:
    modelo = _modelo(modelo_documentos="deepseek-v4-pro", pensar_documentos=True, pensar_chat=False)
    documentos: dict[str, Any] = {"max_tokens": 8000}
    modelo._modo(documentos, "documentos")
    assert documentos["model"] == "deepseek-v4-pro"
    assert documentos["thinking"] == {"type": "enabled"}
    assert documentos["max_tokens"] > 8000
    chat: dict[str, Any] = {"max_tokens": 700}
    modelo._modo(chat, "chat")
    assert chat == {"max_tokens": 700, "model": "deepseek-flash", "thinking": {"type": "disabled"}}


def test_sin_ajustes_no_se_envia_thinking() -> None:
    cuerpo: dict[str, Any] = {"max_tokens": 10}
    _modelo()._modo(cuerpo, "documentos")
    assert cuerpo == {"max_tokens": 10, "model": "deepseek-flash"}


@pytest.mark.asyncio
async def test_el_razonamiento_no_se_muestra_pero_se_reenvia(monkeypatch: Any) -> None:
    modelo = _modelo()

    async def pedir(cuerpo: dict[str, Any]) -> dict[str, Any]:
        return {"content": "Hola", "reasoning_content": "pensando…", "tool_calls": []}

    monkeypatch.setattr(modelo, "_pedir", pedir)
    assert await modelo.completar("s", "u") == "Hola"
    turno = await modelo.conversar([{"role": "user", "content": "u"}])
    assert turno["content"] == "Hola" and turno["reasoning_content"] == "pensando…"
