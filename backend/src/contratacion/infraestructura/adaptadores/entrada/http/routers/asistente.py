"""Asistente (chat): inicio, conversaciones y mensajes.

Aquí solo se arma la inyección: qué adaptador cumple cada puerto. La lógica —camino rápido sin
modelo, cobro solo cuando el modelo contesta, topes de historial— vive en el caso de uso.

Los mensajes llevan tope por persona: cada uno puede acabar en el modelo de IA o en un servicio
ajeno (SRI, datos abiertos), y una pestaña con un bucle no debe gastar la cuota de todos.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.asistente.herramientas import Servicios
from contratacion.aplicacion.asistente.recordados import CpcRecordado, PerfilRecordado
from contratacion.aplicacion.casos_uso.asistente import (
    MAX_TEXTO,
    MAX_TITULO,
    borrar_conversacion,
    enviar,
    inicio,
    listar_conversaciones,
    renombrar_conversacion,
    ver_conversacion,
)
from contratacion.dominio.acceso import Vista
from contratacion.dominio.serializacion import cuerpo_json
from contratacion.infraestructura.adaptadores.entrada.http.dependencias import (
    ActorDep,
    AjustesDep,
    CacheDep,
    ConsentimientoDep,
    ConsultasDep,
    CpcDep,
    CreditosDep,
    IaDep,
    MercadoDep,
    PerfilDep,
    RadarDep,
    UsuariosDep,
    VistasDep,
)
from contratacion.infraestructura.adaptadores.entrada.http.limites import LimitePorUsuario
from contratacion.infraestructura.adaptadores.salida.bd.asistente import (
    RepositorioConversacionesBd,
)
from contratacion.infraestructura.adaptadores.salida.bd.seguimiento import RepositorioSeguimiento
from contratacion.infraestructura.adaptadores.salida.bd.sesion import obtener_motor
from contratacion.infraestructura.adaptadores.salida.historial import (
    HistorialOcds,
    obtener_historial,
)
from contratacion.infraestructura.adaptadores.salida.sri import ConsultaSri, obtener_sri

router = APIRouter(prefix="/v1/asistente", tags=["Asistente"])


def repositorio_conversaciones() -> RepositorioConversacionesBd:
    return RepositorioConversacionesBd(obtener_motor())


ConversacionesDep = Annotated[RepositorioConversacionesBd, Depends(repositorio_conversaciones)]


async def servicios_del_asistente(
    actor: ActorDep,
    vistas: VistasDep,
    ajustes: AjustesDep,
    perfil: PerfilDep,
    cpc: CpcDep,
    radar: RadarDep,
    cache: CacheDep,
    consultas: ConsultasDep,
    mercado: MercadoDep,
    sri: Annotated[ConsultaSri, Depends(obtener_sri)],
    historial: Annotated[HistorialOcds, Depends(obtener_historial)],
) -> Servicios:
    return _servicios(
        actor,
        vistas,
        perfil=perfil,
        cpc=cpc,
        radar=radar,
        cache=cache,
        consultas=consultas,
        mercado=mercado,
        sri=sri,
        historial=historial,
        ttl_memo_seg=ajustes.cache_proceso_seg,
    )


def _servicios(actor: Actor, vistas: frozenset[Vista], **piezas: Any) -> Servicios:
    radar = piezas.pop("radar")
    # Perfil y CPC recordados solo durante esta petición: el inicio y el modelo los leen varias
    # veces, y cada lectura del perfil son una docena de consultas. Ver `recordados.py`.
    piezas["perfil"] = PerfilRecordado(piezas["perfil"])
    piezas["cpc"] = CpcRecordado(piezas["cpc"])
    return Servicios(
        actor=actor,
        vistas=vistas,
        infimas=radar,
        alertas=radar,
        seguimiento=RepositorioSeguimiento(obtener_motor()),
        **piezas,
    )


ServiciosDep = Annotated[Servicios, Depends(servicios_del_asistente)]


class MensajeNuevo(BaseModel):
    texto: str = Field(min_length=1, max_length=MAX_TEXTO)
    conversacion_id: UUID | None = None


class Renombrar(BaseModel):
    titulo: str = Field(min_length=1, max_length=MAX_TITULO)


@router.get(
    "/inicio",
    summary="Saludo, contadores, sugerencias y conversaciones del asistente",
    dependencies=[Depends(LimitePorUsuario("asistente.inicio", 30, 60))],
)
async def ver_inicio(
    actor: ActorDep,
    servicios: ServiciosDep,
    conversaciones: ConversacionesDep,
    modelo: IaDep,
    creditos: CreditosDep,
    usuarios: UsuariosDep,
    _: ConsentimientoDep,
) -> dict[str, Any]:
    return cuerpo_json(
        await inicio(
            actor,
            servicios=servicios,
            conversaciones=conversaciones,
            modelo=modelo,
            creditos=creditos,
            usuarios=usuarios,
        )
    )


@router.get("/conversaciones", summary="Conversaciones de quien entra, la más reciente primero")
async def conversaciones_del_usuario(
    actor: ActorDep, conversaciones: ConversacionesDep, _: ConsentimientoDep
) -> dict[str, Any]:
    return cuerpo_json(await listar_conversaciones(actor, conversaciones=conversaciones))


@router.get("/conversaciones/{conversacion_id}", summary="Una conversación con sus mensajes")
async def una_conversacion(
    conversacion_id: UUID,
    actor: ActorDep,
    conversaciones: ConversacionesDep,
    _: ConsentimientoDep,
) -> dict[str, Any]:
    return cuerpo_json(
        await ver_conversacion(
            actor, conversaciones=conversaciones, conversacion_id=conversacion_id
        )
    )


@router.patch("/conversaciones/{conversacion_id}", summary="Cambiar el título")
async def renombrar(
    conversacion_id: UUID,
    cuerpo: Renombrar,
    actor: ActorDep,
    conversaciones: ConversacionesDep,
    _: ConsentimientoDep,
) -> dict[str, Any]:
    return cuerpo_json(
        await renombrar_conversacion(
            actor,
            conversaciones=conversaciones,
            conversacion_id=conversacion_id,
            titulo=cuerpo.titulo,
        )
    )


@router.delete(
    "/conversaciones/{conversacion_id}", status_code=204, summary="Borrar una conversación"
)
async def borrar(
    conversacion_id: UUID,
    actor: ActorDep,
    conversaciones: ConversacionesDep,
    _: ConsentimientoDep,
) -> None:
    await borrar_conversacion(actor, conversaciones=conversaciones, conversacion_id=conversacion_id)


@router.post(
    "/mensajes",
    summary="Enviar un mensaje al asistente y recibir su respuesta",
    dependencies=[Depends(LimitePorUsuario("asistente.mensajes", 20, 60))],
)
async def mensaje(
    cuerpo: MensajeNuevo,
    actor: ActorDep,
    ajustes: AjustesDep,
    servicios: ServiciosDep,
    conversaciones: ConversacionesDep,
    modelo: IaDep,
    creditos: CreditosDep,
    _: ConsentimientoDep,
) -> dict[str, Any]:
    return cuerpo_json(
        await enviar(
            actor,
            texto=cuerpo.texto,
            conversacion_id=cuerpo.conversacion_id,
            servicios=servicios,
            conversaciones=conversaciones,
            modelo=modelo,
            creditos=creditos,
            max_rondas=ajustes.asistente_max_rondas,
        )
    )
