"""Radar, alertas y búsquedas guardadas. Nada de esto habla con el portal."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from contratacion.aplicacion.casos_uso.revisar_alertas import previsualizar_alerta
from contratacion.aplicacion.casos_uso.ver_propuestas import ver_propuestas
from contratacion.aplicacion.casos_uso.ver_radar import ver_radar
from contratacion.dominio.acceso import fuentes_para_vistas
from contratacion.dominio.errores import DatoInvalido
from contratacion.dominio.serializacion import cuerpo_json
from contratacion.infraestructura.adaptadores.entrada.http.dependencias import (
    ActorDep,
    CacheDep,
    ConsentimientoDep,
    CpcDep,
    PerfilDep,
    RadarDep,
    VistasDep,
)
from contratacion.infraestructura.adaptadores.entrada.http.limites import LimitePorUsuario

router = APIRouter(prefix="/v1", tags=["Radar"])

_FRECUENCIAS = {"inmediata", "diaria", "semanal"}


class BusquedaNueva(BaseModel):
    nombre: str = Field(min_length=2, max_length=80)
    parametros: dict[str, Any] = Field(default_factory=dict)


class AlertaNueva(BaseModel):
    nombre: str = Field(min_length=2, max_length=80)
    cpc: list[str] = Field(default_factory=list)
    palabras: list[str] = Field(default_factory=list)
    provincia: str = ""
    canton: str = ""
    presupuesto_min: float | None = None
    presupuesto_max: float | None = None
    frecuencia: str = "diaria"
    avisar_correo: bool = False


@router.get("/radar", summary="Oportunidades compatibles con el perfil")
async def radar(
    actor: ActorDep,
    vistas: VistasDep,
    perfil: PerfilDep,
    cpc: CpcDep,
    radar_repo: RadarDep,
    _: ConsentimientoDep,
) -> dict[str, Any]:
    return cuerpo_json(
        await ver_radar(actor, vistas=vistas, perfil=perfil, cpc=cpc, radar=radar_repo)
    )


@router.get(
    "/propuestas",
    summary="Propuestas para ti: ínfimas abiertas que la empresa puede ofertar",
    dependencies=[Depends(LimitePorUsuario("propuestas.listar", 60, 60))],
)
async def propuestas(
    actor: ActorDep,
    vistas: VistasDep,
    perfil: PerfilDep,
    cpc: CpcDep,
    radar_repo: RadarDep,
    cache: CacheDep,
    _: ConsentimientoDep,
    pagina: int = Query(default=1, ge=1, le=1000),
    tamano: int = Query(default=20, ge=1, le=50),
    orden: str = Query(default="coincidencia", pattern="^(coincidencia|cierre|presupuesto)$"),
    provincia: str | None = Query(default=None, max_length=80),
    solo_abiertas: bool = True,
) -> dict[str, Any]:
    """Todas las ínfimas vigentes con plazo de proformas abierto que encajan con el perfil.

    Coinciden por CPC (por el inicio del código) o por lo que la empresa ofrece, y respetan la
    cobertura y el rango de presupuesto cuando el perfil los define. Cada fila dice por qué se
    sugiere.
    """
    return cuerpo_json(
        await ver_propuestas(
            actor,
            vistas=vistas,
            perfil=perfil,
            cpc=cpc,
            infimas=radar_repo,
            cache=cache,
            pagina=pagina,
            tamano=tamano,
            orden=orden,
            provincia=provincia,
            solo_abiertas=solo_abiertas,
        )
    )


@router.get("/busquedas", summary="Búsquedas guardadas de quien entra")
async def listar_busquedas(
    actor: ActorDep, radar_repo: RadarDep, _: ConsentimientoDep
) -> dict[str, Any]:
    filas = await radar_repo.listar_busquedas(
        negocio_id=actor.negocio_id, usuario_id=actor.usuario_id
    )
    return cuerpo_json({"busquedas": filas})


@router.post("/busquedas", status_code=201, summary="Guardar los filtros actuales")
async def guardar_busqueda(
    cuerpo: BusquedaNueva, actor: ActorDep, radar_repo: RadarDep, _: ConsentimientoDep
) -> dict[str, Any]:
    fila = await radar_repo.guardar_busqueda(
        negocio_id=actor.negocio_id,
        usuario_id=actor.usuario_id,
        nombre=cuerpo.nombre.strip(),
        parametros=cuerpo.parametros,
    )
    return cuerpo_json(fila)


@router.delete("/busquedas/{busqueda_id}", status_code=204, summary="Quitar una búsqueda")
async def quitar_busqueda(
    busqueda_id: UUID, actor: ActorDep, radar_repo: RadarDep, _: ConsentimientoDep
) -> None:
    ok = await radar_repo.quitar_busqueda(
        negocio_id=actor.negocio_id, usuario_id=actor.usuario_id, busqueda_id=busqueda_id
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Esa búsqueda no está.")


@router.get("/alertas", summary="Alertas de quien entra")
async def listar_alertas(
    actor: ActorDep, radar_repo: RadarDep, _: ConsentimientoDep
) -> dict[str, Any]:
    filas = [
        fila
        for fila in await radar_repo.listar_alertas(negocio_id=actor.negocio_id)
        if fila["usuario_id"] == actor.usuario_id
    ]
    return cuerpo_json({"alertas": filas})


class AlertaEnBorrador(BaseModel):
    """Lo mismo que una alerta nueva, sin nombre ni frecuencia: aún se está armando."""

    cpc: list[str] = Field(default_factory=list, max_length=40)
    palabras: list[str] = Field(default_factory=list, max_length=40)
    provincia: str = Field(default="", max_length=80)
    canton: str = Field(default="", max_length=80)
    presupuesto_min: float | None = None
    presupuesto_max: float | None = None


@router.post(
    "/alertas/vista-previa",
    summary="Cuántos procesos vigentes cumplirían hoy una alerta",
    dependencies=[Depends(LimitePorUsuario("alertas.vista_previa", 40, 60))],
)
async def vista_previa_alerta(
    cuerpo: AlertaEnBorrador,
    actor: ActorDep,
    vistas: VistasDep,
    radar_repo: RadarDep,
    _: ConsentimientoDep,
) -> dict[str, Any]:
    """Misma regla que la revisión del worker. No guarda nada.

    Solo cuenta y enseña procesos de las fuentes que la persona puede ver.
    """
    del actor
    return cuerpo_json(
        await previsualizar_alerta(
            radar_repo, cuerpo.model_dump(), fuentes=fuentes_para_vistas(vistas)
        )
    )


@router.post("/alertas", status_code=201, summary="Crear una alerta")
async def crear_alerta(
    cuerpo: AlertaNueva, actor: ActorDep, radar_repo: RadarDep, _: ConsentimientoDep
) -> dict[str, Any]:
    if cuerpo.frecuencia not in _FRECUENCIAS:
        raise DatoInvalido("La frecuencia debe ser inmediata, diaria o semanal.")
    if not cuerpo.cpc and not cuerpo.palabras:
        raise DatoInvalido("La alerta necesita al menos un CPC o una palabra clave.")
    # Por ahora el aviso solo vive en el panel. El correo se deja apagado aunque el cliente lo pida.
    cuerpo.avisar_correo = False
    fila = await radar_repo.crear_alerta(
        negocio_id=actor.negocio_id,
        usuario_id=actor.usuario_id,
        campos=cuerpo.model_dump(),
    )
    return cuerpo_json(fila)


@router.delete("/alertas/{alerta_id}", status_code=204, summary="Quitar una alerta")
async def quitar_alerta(
    alerta_id: UUID, actor: ActorDep, radar_repo: RadarDep, _: ConsentimientoDep
) -> None:
    ok = await radar_repo.quitar_alerta(
        negocio_id=actor.negocio_id, usuario_id=actor.usuario_id, alerta_id=alerta_id
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Esa alerta no está.")


@router.get("/avisos", summary="Avisos dentro de Cercop")
async def listar_avisos(
    actor: ActorDep, vistas: VistasDep, radar_repo: RadarDep, _: ConsentimientoDep
) -> dict[str, Any]:
    # Los avisos de alertas solo de las fuentes que la persona puede ver hoy.
    filas = await radar_repo.listar_avisos(
        negocio_id=actor.negocio_id,
        usuario_id=actor.usuario_id,
        fuentes=fuentes_para_vistas(vistas),
    )
    return cuerpo_json({"avisos": filas})


@router.post("/avisos/{aviso_id}/leido", summary="Marcar un aviso como leído")
async def leer_aviso(
    aviso_id: UUID, actor: ActorDep, radar_repo: RadarDep, _: ConsentimientoDep
) -> dict[str, Any]:
    ok = await radar_repo.marcar_leido(
        negocio_id=actor.negocio_id,
        usuario_id=actor.usuario_id,
        aviso_id=aviso_id,
        momento=datetime.now(UTC),
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Ese aviso no está.")
    return {"leido": True}
