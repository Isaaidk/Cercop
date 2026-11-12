"""Créditos de IA: saldo, movimientos y compras. La confirmación del pago es de la plataforma."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from contratacion.aplicacion.casos_uso.generar_oferta import (
    compras_pendientes,
    otorgar_creditos,
    pedir_compra,
    resolver_compra,
    ver_creditos,
)
from contratacion.dominio.serializacion import cuerpo_json
from contratacion.infraestructura.adaptadores.entrada.http.dependencias import (
    ActorDep,
    AuditoriaDep,
    CreditosDep,
    IaDep,
)

router = APIRouter(tags=["IA"])


class Compra(BaseModel):
    paquete: str = Field(min_length=2, max_length=30)


class Resolucion(BaseModel):
    pagada: bool


@router.get("/v1/ia/creditos", summary="Saldo, costos y paquetes de créditos de IA")
async def creditos(actor: ActorDep, repositorio: CreditosDep, modelo: IaDep) -> dict[str, Any]:
    return cuerpo_json(await ver_creditos(actor, creditos=repositorio, modelo=modelo))


@router.get("/v1/ia/movimientos", summary="Últimos movimientos del saldo")
async def movimientos(actor: ActorDep, repositorio: CreditosDep) -> dict[str, Any]:
    return cuerpo_json({"movimientos": await repositorio.movimientos(actor.negocio_id)})


@router.post("/v1/ia/compras", status_code=status.HTTP_201_CREATED, summary="Solicitar un paquete")
async def comprar(
    cuerpo: Compra, actor: ActorDep, repositorio: CreditosDep, auditoria: AuditoriaDep
) -> dict[str, Any]:
    compra = await pedir_compra(actor, creditos=repositorio, codigo=cuerpo.paquete)
    await auditoria.auditar(
        accion="ia.compra_solicitada",
        negocio_id=actor.negocio_id,
        usuario_id=actor.usuario_id,
        entidad="compra_ia",
        resultado="pendiente",
        detalle={"paquete": compra["paquete"], "creditos": compra["creditos"]},
    )
    return cuerpo_json(compra)


class Otorgamiento(BaseModel):
    cantidad: int = Field(ge=1, le=100_000)
    motivo: str = Field(default="", max_length=120)


@router.post(
    "/v1/plataforma/ia/otorgar/{negocio_id}",
    summary="Dar créditos de IA a una empresa",
)
async def otorgar(
    negocio_id: UUID,
    cuerpo: Otorgamiento,
    actor: ActorDep,
    repositorio: CreditosDep,
    auditoria: AuditoriaDep,
) -> dict[str, Any]:
    fila = await otorgar_creditos(
        actor,
        creditos=repositorio,
        negocio_id=negocio_id,
        cantidad=cuerpo.cantidad,
        motivo=cuerpo.motivo,
    )
    await auditoria.auditar(
        accion="ia.creditos_otorgados",
        negocio_id=negocio_id,
        usuario_id=actor.usuario_id,
        entidad="saldo_ia",
        resultado="ok",
        detalle={"cantidad": cuerpo.cantidad, "motivo": cuerpo.motivo},
    )
    return cuerpo_json(fila)


@router.get("/v1/plataforma/ia/compras", summary="Compras de créditos por confirmar")
async def pendientes(actor: ActorDep, repositorio: CreditosDep) -> dict[str, Any]:
    return cuerpo_json({"compras": await compras_pendientes(actor, creditos=repositorio)})


@router.post(
    "/v1/plataforma/ia/compras/{negocio_id}/{compra_id}",
    summary="Confirmar el pago (suma los créditos) o anular la compra",
)
async def resolver(
    negocio_id: UUID,
    compra_id: UUID,
    cuerpo: Resolucion,
    actor: ActorDep,
    repositorio: CreditosDep,
    auditoria: AuditoriaDep,
) -> dict[str, Any]:
    fila = await resolver_compra(
        actor,
        creditos=repositorio,
        negocio_id=negocio_id,
        compra_id=compra_id,
        pagada=cuerpo.pagada,
    )
    await auditoria.auditar(
        accion="ia.compra_resuelta",
        negocio_id=negocio_id,
        usuario_id=actor.usuario_id,
        entidad="compra_ia",
        resultado=fila["estado"],
        detalle={"compra_id": str(compra_id), "creditos": fila["creditos"]},
    )
    return cuerpo_json(fila)
