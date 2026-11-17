"""Notificaciones web: la clave pública y alta/baja del navegador de quien entra.

Estas rutas solo se usan cuando la persona pulsa «Activar notificaciones» o las apaga: no hay
sondeo. Los mensajes los manda el worker (`aplicacion/casos_uso/notificar.py`).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from contratacion.infraestructura.adaptadores.entrada.http.dependencias import (
    ActorDep,
    ConsentimientoDep,
)
from contratacion.infraestructura.adaptadores.entrada.http.limites import LimitePorUsuario
from contratacion.infraestructura.adaptadores.salida.bd.notificaciones import (
    RepositorioNotificaciones,
)
from contratacion.infraestructura.adaptadores.salida.bd.sesion import obtener_motor
from contratacion.infraestructura.config.ajustes import obtener_ajustes

router = APIRouter(prefix="/v1/notificaciones", tags=["Notificaciones"])


def repositorio_notificaciones() -> RepositorioNotificaciones:
    return RepositorioNotificaciones(obtener_motor())


NotificacionesDep = Annotated[RepositorioNotificaciones, Depends(repositorio_notificaciones)]


class ClavesNavegador(BaseModel):
    p256dh: str = Field(min_length=20, max_length=200)
    auth: str = Field(min_length=8, max_length=100)


class Suscripcion(BaseModel):
    endpoint: str = Field(min_length=12, max_length=1000, pattern=r"^https://")
    keys: ClavesNavegador
    avisar_perfil: bool = True


class Navegador(BaseModel):
    endpoint: str = Field(min_length=12, max_length=1000, pattern=r"^https://")


@router.get("/clave", summary="Clave pública para suscribir el navegador")
async def clave(_actor: ActorDep) -> dict[str, Any]:
    publica = obtener_ajustes().vapid_publica.strip()
    return {"disponible": bool(publica), "clave_publica": publica or None}


@router.post(
    "/estado",
    summary="¿Este navegador está suscrito?",
    dependencies=[Depends(LimitePorUsuario("notificaciones.estado", 30, 60))],
)
async def estado(
    cuerpo: Navegador, actor: ActorDep, repo: NotificacionesDep, _: ConsentimientoDep
) -> dict[str, Any]:
    return await repo.estado(
        negocio_id=actor.negocio_id, usuario_id=actor.usuario_id, endpoint=cuerpo.endpoint
    )


@router.post(
    "/suscripcion",
    status_code=201,
    summary="Activar las notificaciones en este navegador",
    dependencies=[Depends(LimitePorUsuario("notificaciones.alta", 10, 60))],
)
async def suscribir(
    cuerpo: Suscripcion, actor: ActorDep, repo: NotificacionesDep, _: ConsentimientoDep
) -> dict[str, Any]:
    if not obtener_ajustes().vapid_publica.strip():
        raise HTTPException(status_code=503, detail="Las notificaciones aún no están disponibles.")
    await repo.guardar_suscripcion(
        negocio_id=actor.negocio_id,
        usuario_id=actor.usuario_id,
        endpoint=cuerpo.endpoint,
        p256dh=cuerpo.keys.p256dh,
        auth=cuerpo.keys.auth,
        avisar_perfil=cuerpo.avisar_perfil,
    )
    return {"suscrito": True, "avisar_perfil": cuerpo.avisar_perfil}


@router.post(
    "/baja",
    summary="Apagar las notificaciones en este navegador",
    dependencies=[Depends(LimitePorUsuario("notificaciones.baja", 10, 60))],
)
async def dar_de_baja(
    cuerpo: Navegador, actor: ActorDep, repo: NotificacionesDep
) -> dict[str, Any]:
    # Sin exigir consentimiento: apagar notificaciones siempre tiene que poder hacerse.
    await repo.quitar_suscripcion(
        negocio_id=actor.negocio_id, usuario_id=actor.usuario_id, endpoint=cuerpo.endpoint
    )
    return {"suscrito": False}
