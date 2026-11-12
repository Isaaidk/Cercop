"""«Mis ofertas»: tablero de las proformas hechas por la empresa."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from contratacion.aplicacion.casos_uso.seguimiento_ofertas import mover_oferta, ver_ofertas
from contratacion.dominio.serializacion import cuerpo_json
from contratacion.infraestructura.adaptadores.entrada.http.dependencias import (
    ActorDep,
    ConsentimientoDep,
)
from contratacion.infraestructura.adaptadores.salida.bd.seguimiento import (
    RepositorioSeguimiento,
)
from contratacion.infraestructura.adaptadores.salida.bd.sesion import obtener_motor

router = APIRouter(prefix="/v1/mis-ofertas", tags=["Mis ofertas"])


def repositorio_seguimiento() -> RepositorioSeguimiento:
    return RepositorioSeguimiento(obtener_motor())


SeguimientoDep = Annotated[RepositorioSeguimiento, Depends(repositorio_seguimiento)]


class CambioDeOferta(BaseModel):
    etapa: str | None = Field(default=None, max_length=20)
    monto_adjudicado: float | None = Field(default=None, ge=0)
    nota: str | None = Field(default=None, max_length=500)


@router.get("", summary="Proformas de la empresa por etapa, con tasa de éxito")
async def listar(
    actor: ActorDep, repositorio: SeguimientoDep, _: ConsentimientoDep
) -> dict[str, Any]:
    return cuerpo_json(await ver_ofertas(actor, repositorio=repositorio))


@router.patch("/{proforma_id}", status_code=204, summary="Mover de etapa, monto o nota")
async def mover(
    proforma_id: UUID,
    cuerpo: CambioDeOferta,
    actor: ActorDep,
    repositorio: SeguimientoDep,
    _: ConsentimientoDep,
) -> None:
    await mover_oferta(
        actor,
        repositorio=repositorio,
        proforma_id=proforma_id,
        campos=cuerpo.model_dump(exclude_unset=True),
    )
