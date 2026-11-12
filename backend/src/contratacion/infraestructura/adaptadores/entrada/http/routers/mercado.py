"""Historial, precios, rankings, demanda y comparador. Nada de esto habla con el portal."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from contratacion.aplicacion.casos_uso.ver_mercado import (
    ver_adjudicaciones,
    ver_comparacion,
    ver_demanda,
    ver_entidades,
    ver_precios,
    ver_proveedores,
)
from contratacion.dominio.serializacion import cuerpo_json
from contratacion.infraestructura.adaptadores.entrada.http.dependencias import (
    ConsentimientoDep,
    MercadoDep,
    VistasDep,
)

router = APIRouter(prefix="/v1/mercado", tags=["Mercado"])


class Comparacion(BaseModel):
    ids: list[UUID] = Field(min_length=2, max_length=4)


@router.get("/adjudicaciones", summary="Historial de adjudicaciones")
async def adjudicaciones(
    vistas: VistasDep,
    mercado: MercadoDep,
    _: ConsentimientoDep,
    q: str = "",
    cpc: str = "",
    entidad: str = "",
    proveedor: str = "",
    anio: str = "",
) -> dict[str, Any]:
    return cuerpo_json(
        await ver_adjudicaciones(
            vistas, mercado=mercado, q=q, cpc=cpc, entidad=entidad, proveedor=proveedor, anio=anio
        )
    )


@router.get("/precios", summary="Estadísticas de montos de procesos comparables")
async def precios(
    vistas: VistasDep,
    mercado: MercadoDep,
    _: ConsentimientoDep,
    q: str = "",
    cpc: str = "",
    anio: str = "",
) -> dict[str, Any]:
    return cuerpo_json(await ver_precios(vistas, mercado=mercado, q=q, cpc=cpc, anio=anio))


@router.get("/proveedores", summary="Fichas de proveedores adjudicados")
async def proveedores(
    vistas: VistasDep,
    mercado: MercadoDep,
    _: ConsentimientoDep,
    q: str = "",
    cpc: str = "",
    anio: str = "",
) -> dict[str, Any]:
    return cuerpo_json(await ver_proveedores(vistas, mercado=mercado, q=q, cpc=cpc, anio=anio))


@router.get("/entidades", summary="Compras históricas por institución")
async def entidades(
    vistas: VistasDep,
    mercado: MercadoDep,
    _: ConsentimientoDep,
    q: str = "",
    cpc: str = "",
    anio: str = "",
) -> dict[str, Any]:
    return cuerpo_json(await ver_entidades(vistas, mercado=mercado, q=q, cpc=cpc, anio=anio))


@router.get("/demanda", summary="Dónde se concentran las compras")
async def demanda(
    vistas: VistasDep,
    mercado: MercadoDep,
    _: ConsentimientoDep,
    q: str = Query(""),
    cpc: str = "",
    anio: str = "",
) -> dict[str, Any]:
    return cuerpo_json(await ver_demanda(vistas, mercado=mercado, q=q, cpc=cpc, anio=anio))


@router.post("/comparar", summary="Compara de dos a cuatro oportunidades")
async def comparar(
    cuerpo: Comparacion,
    vistas: VistasDep,
    mercado: MercadoDep,
    _: ConsentimientoDep,
) -> dict[str, Any]:
    return cuerpo_json(await ver_comparacion(vistas, mercado=mercado, ids=cuerpo.ids))
