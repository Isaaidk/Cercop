"""Consultas de mercado. Leen lo ya guardado; no llaman al portal."""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from contratacion.aplicacion.puertos.mercado import RepositorioMercado
from contratacion.dominio.acceso import Vista, fuentes_para_vistas
from contratacion.dominio.errores import DatoInvalido, SinPermiso
from contratacion.dominio.mercado import (
    AVISO_PRECIOS,
    agrupar_precios,
    requisitos_de,
)

_SIN_FUENTES = (
    "No hay ninguna vista concedida que dé acceso al histórico. Pide al administrador que active "
    "al menos una."
)
_ANIO = re.compile(r"^\d{4}$")


def _fuentes(vistas: frozenset[Vista]) -> tuple[str, ...]:
    fuentes = fuentes_para_vistas(vistas)
    if not fuentes:
        raise SinPermiso(_SIN_FUENTES)
    return fuentes


def _anio(valor: str) -> str:
    limpio = valor.strip()
    if limpio and _ANIO.fullmatch(limpio) is None:
        raise DatoInvalido("El año tiene que ser de cuatro dígitos.")
    return limpio


def _ocds(fuentes: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(fuente for fuente in fuentes if fuente == "OCDS")


async def ver_adjudicaciones(
    vistas: frozenset[Vista],
    *,
    mercado: RepositorioMercado,
    q: str = "",
    cpc: str = "",
    entidad: str = "",
    proveedor: str = "",
    anio: str = "",
) -> dict[str, Any]:
    fuentes = _ocds(_fuentes(vistas))
    if not fuentes:
        return {
            "filas": [],
            "motivo": "Las adjudicaciones salen de las ofertas, y esa vista no está activa.",
        }
    filas = await mercado.adjudicaciones(
        fuentes=fuentes,
        q=q,
        cpc=cpc,
        entidad=entidad,
        proveedor=proveedor,
        anio=_anio(anio),
    )
    return {"filas": filas, "motivo": ""}


async def ver_precios(
    vistas: frozenset[Vista],
    *,
    mercado: RepositorioMercado,
    q: str = "",
    cpc: str = "",
    anio: str = "",
) -> dict[str, Any]:
    if not q.strip() and not cpc.strip():
        return {
            "grupos": [],
            "aviso": AVISO_PRECIOS,
            "motivo": (
                "Indica un CPC o un término. Sin eso se mezclarían contratos de cosas distintas."
            ),
        }
    fuentes = _ocds(_fuentes(vistas))
    if not fuentes:
        return {
            "grupos": [],
            "aviso": AVISO_PRECIOS,
            "motivo": "Los precios salen de las ofertas adjudicadas, y esa vista no está activa.",
        }
    filas = await mercado.montos(fuentes=fuentes, q=q, cpc=cpc, anio=_anio(anio))
    return {"grupos": agrupar_precios(filas), "aviso": AVISO_PRECIOS, "motivo": ""}


async def ver_proveedores(
    vistas: frozenset[Vista],
    *,
    mercado: RepositorioMercado,
    q: str = "",
    cpc: str = "",
    anio: str = "",
) -> dict[str, Any]:
    fuentes = _ocds(_fuentes(vistas))
    if not fuentes:
        return {"filas": [], "motivo": "El ranking de proveedores sale de las ofertas adjudicadas."}
    filas = await mercado.proveedores(fuentes=fuentes, q=q, cpc=cpc, anio=_anio(anio))
    return {"filas": filas, "motivo": ""}


async def ver_entidades(
    vistas: frozenset[Vista],
    *,
    mercado: RepositorioMercado,
    q: str = "",
    cpc: str = "",
    anio: str = "",
) -> dict[str, Any]:
    filas = await mercado.entidades(fuentes=_fuentes(vistas), q=q, cpc=cpc, anio=_anio(anio))
    return {"filas": filas, "motivo": ""}


async def ver_demanda(
    vistas: frozenset[Vista],
    *,
    mercado: RepositorioMercado,
    q: str = "",
    cpc: str = "",
    anio: str = "",
) -> dict[str, Any]:
    datos = await mercado.demanda(fuentes=_fuentes(vistas), q=q, cpc=cpc, anio=_anio(anio))
    return {**datos, "motivo": ""}


async def ver_comparacion(
    vistas: frozenset[Vista],
    *,
    mercado: RepositorioMercado,
    ids: list[UUID],
) -> dict[str, Any]:
    if len(ids) < 2:
        raise DatoInvalido("Elige al menos dos oportunidades.")
    if len(ids) > 4:
        raise DatoInvalido("Se comparan hasta cuatro oportunidades a la vez.")
    filas = await mercado.comparar(fuentes=_fuentes(vistas), ids=ids)
    for fila in filas:
        fila["requisitos"] = requisitos_de(list(fila.pop("documentos") or []))
        fila["ubicacion"] = " ".join(
            parte for parte in (fila.get("provincia"), fila.get("canton")) if parte
        ).strip()
    return {"filas": filas}
