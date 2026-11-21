"""Formato de la proforma y páginas finales opcionales.

La primera página sigue el «Modelo de proforma» de ínfima cuantía que usan las entidades (cliente,
proveedor, tabla de ítems, totales, condiciones y firma). Lo demás —respaldo con condiciones y
alcance del TDR, cumplimiento de los TDR, declaración, carta de compromiso y Formulario de Perfil de
Integridad— va en páginas finales que la persona elige. La lista es la misma que exporta el panel
(`frontend/src/utils/proformaPdf.js::PAGINAS_FINALES`): si cambia una, cambia la otra.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# El modelo de proforma de ínfima cuantía (por defecto) y el formulario del SOCE de antes.
FORMATO_INFIMA = "infima"
FORMATO_SOCE = "soce"
FORMATOS = (FORMATO_INFIMA, FORMATO_SOCE)

# (id, etiqueta, por defecto), en el orden en que se imprimen.
PAGINAS_FINALES: tuple[tuple[str, str, bool], ...] = (
    ("respaldo", "Documento de respaldo: condiciones, alcance y detalle del TDR", True),
    ("cumplimiento", "Cumplimiento de los TDR", True),
    ("declaracion", "Declaración del oferente", True),
    ("compromiso", "Carta de compromiso", False),
    ("integridad", "Formulario de Perfil de Integridad", True),
)
IDS_PAGINAS = tuple(pagina for pagina, _, _ in PAGINAS_FINALES)
# Una cotización es un estudio de mercado, no una oferta: no lleva compromiso ni integridad.
_SOLO_OFERTA = {"compromiso", "integridad"}


def formato_de(documento: Mapping[str, Any]) -> str:
    """El formato elegido; sin elección, el modelo de ínfima para la proforma y el SOCE para la
    cotización (que no es una oferta)."""
    elegido = str((documento.get("extras") or {}).get("formato_proforma") or "")
    if elegido in FORMATOS:
        return elegido
    return FORMATO_SOCE if documento.get("tipo") == "cotizacion" else FORMATO_INFIMA


def paginas_activas(documento: Mapping[str, Any]) -> dict[str, bool]:
    """Qué páginas finales se imprimen. Lo que no viene en `extras.paginas_finales` va por defecto.

    `extras.integridad = false` (proformas guardadas antes de esta lista) sigue apagando el
    formulario de integridad si no hay una elección explícita.
    """
    extras = documento.get("extras") or {}
    elegidas = extras.get("paginas_finales") or {}
    if not isinstance(elegidas, Mapping):
        elegidas = {}
    activas: dict[str, bool] = {}
    for pagina, _, defecto in PAGINAS_FINALES:
        valor = elegidas.get(pagina)
        if isinstance(valor, bool):
            activas[pagina] = valor
        elif pagina == "integridad" and extras.get("integridad") is False:
            activas[pagina] = False
        else:
            activas[pagina] = defecto
    if documento.get("tipo") == "cotizacion":
        for pagina in _SOLO_OFERTA:
            activas[pagina] = False
    return activas


def limpiar_paginas(valor: Any) -> dict[str, bool]:
    """Solo ids conocidos con `true`/`false`: es lo que se guarda en `extras.paginas_finales`."""
    if not isinstance(valor, Mapping):
        return {}
    return {pagina: valor[pagina] for pagina in IDS_PAGINAS if isinstance(valor.get(pagina), bool)}


# Frase del modelo cuando la condición es la que fija la entidad en su contratación.
ADHIERE = "El proponente se adhiere a las condiciones de la contratación"


def texto_compromiso(razon: str, ruc: str, entidad: str, objeto: str) -> str:
    """Carta de compromiso del modelo de la entidad, con los datos de la proforma."""
    return (
        f"Yo, {razon or '[RAZÓN SOCIAL]'} con RUC: {ruc or '[RUC]'} por mis propios derechos me "
        f"comprometo con la {entidad or '[ENTIDAD]'}, respecto del proceso "
        f"{objeto or '[OBJETO DE CONTRATACIÓN]'}, que en el caso de ser adjudicado cumpliré con "
        "los requisitos y condiciones solicitadas en los términos de referencia y/o "
        "especificaciones técnicas, referente al personal técnico/equipo de trabajo/recursos/otros "
        "parámetros; para lo cual, al inicio de la etapa de ejecución de la Orden de Compra, "
        "entregaré la documentación de respaldo al Administrador de la Orden de Compra; caso "
        "contrario se procederá conforme a lo establecido en la normativa legal vigente."
    )


def totales_iva(cifras: Mapping[str, Any]) -> list[tuple[str, float]]:
    """SUBTOTAL, BASE IMPONIBLE <tarifa>%, BASE IMPONIBLE 0%, IVA <tarifa>% y TOTAL.

    La proforma tiene una sola tarifa para todas sus líneas (`impuesto_porcentaje`): con tarifa,
    todo el subtotal es base gravada; con 0 %, todo es base 0 %. La tarifa vigente es 15 % y es la
    que se rotula cuando la proforma va con 0 %.
    """
    subtotal = float(cifras.get("subtotal") or 0)
    tarifa = float(cifras.get("impuesto_porcentaje") or 0)
    impuesto = float(cifras.get("impuesto") or 0)
    total = float(cifras.get("total") or subtotal + impuesto)
    rotulo = f"{tarifa:g}" if tarifa > 0 else "15"
    gravada = subtotal if tarifa > 0 else 0.0
    return [
        ("SUBTOTAL", subtotal),
        (f"BASE IMPONIBLE {rotulo}%", gravada),
        ("BASE IMPONIBLE 0%", subtotal - gravada),
        (f"IVA {rotulo}%", impuesto),
        ("TOTAL", total),
    ]
