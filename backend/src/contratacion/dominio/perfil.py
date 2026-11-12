"""Datos de la empresa que después rellenan un TDR.

Cada valor de aquí entra en un anexo del pliego: la dedicación dice a qué licitaciones se presenta,
el representante firma, y la experiencia, el personal y el equipo arman los anexos cuando el objeto
coincide. Validar aquí evita que un código inventado llegue a la base y falle el CHECK a destiempo.
"""

from __future__ import annotations

import re

from contratacion.dominio.errores import DatoInvalido

TIPOS_CONTRATACION = frozenset({"bienes", "servicios", "obras", "consultoria"})
TIPOS_PROCEDIMIENTO = frozenset({"infima", "subasta_inversa", "catalogo", "licitacion"})
TIPOS_PERSONA = frozenset({"natural", "juridica"})
TIPOS_CONTACTO = frozenset({"representante_legal", "comercial", "tecnico"})
TIPOS_OFERTA = frozenset({"producto", "servicio"})

_RUC = re.compile(r"^[0-9]{13}$")


def exigir_opcion(valor: str, permitidos: frozenset[str], nombre: str) -> str:
    """Normaliza un código de catálogo o lo rechaza."""
    limpio = str(valor or "").strip().lower()
    if limpio not in permitidos:
        opciones = ", ".join(sorted(permitidos))
        raise DatoInvalido(f"{nombre} no reconocido: {valor!r}. Se espera uno de: {opciones}.")
    return limpio


def exigir_ruc(valor: str | None) -> str | None:
    """Un RUC, si viene, tiene 13 dígitos. Vacío se guarda como ausente."""
    if valor is None:
        return None
    limpio = str(valor).strip()
    if not limpio:
        return None
    if _RUC.fullmatch(limpio) is None:
        raise DatoInvalido("El RUC debe tener 13 dígitos.")
    return limpio


def clasificar_objeto(texto: str | None) -> str | None:
    """Traduce el tipo que publica la fuente a bienes, servicios, obras o consultoría.

    Si el texto no dice nada reconocible, devuelve `None`: no se inventa una clasificación para
    poder rechazar una ínfima que el pliego no clasificó.
    """
    normal = str(texto or "").strip().lower()
    if not normal:
        return None
    if "consult" in normal:
        return "consultoria"
    if "obra" in normal:
        return "obras"
    if "bien" in normal:
        return "bienes"
    if "servic" in normal:
        return "servicios"
    return None


def clasificar_procedimiento(texto: str | None, *, es_infima: bool) -> str | None:
    """Traduce el procedimiento de la fuente al catálogo de la dedicación."""
    if es_infima:
        return "infima"
    normal = str(texto or "").strip().lower()
    if "subasta" in normal:
        return "subasta_inversa"
    if "catalog" in normal or "catálog" in normal:
        return "catalogo"
    if "licit" in normal:
        return "licitacion"
    if "infim" in normal or "cuantia" in normal or "cuantía" in normal:
        return "infima"
    return None
