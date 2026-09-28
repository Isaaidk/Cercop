"""Enrutador de estado de la ingesta.

Sirve para que el panel administrativo pueda responder a la pregunta «¿está entrando información?»
sin acceso a la base ni a los registros del proceso. Expone el último ciclo de cada fuente: cuándo
empezó, cuándo terminó, cuántos registros nuevos y actualizados hubo, cuántas peticiones se
consumieron y qué avisos se registraron.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from contratacion.dominio.errores import NoEncontrado
from contratacion.dominio.serializacion import cuerpo_json
from contratacion.infraestructura.adaptadores.entrada.http.dependencias import (
    ActorDep,
    ConsentimientoDep,
    ConsultasDep,
)

router = APIRouter(prefix="/v1/ingestas", tags=["Ingesta"])


@router.get("", summary="Estado del último ciclo de cada fuente")
async def estado_ingestas(
    consultas: ConsultasDep, actor: ActorDep, _: ConsentimientoDep
) -> dict[str, Any]:
    """Una entrada por fuente, aunque nunca se haya ejecutado ningún ciclo.

    Es información de operación, no de negocio: expone cuántas peticiones se consumieron y qué falló
    en la fuente oficial. Por eso se limita a los roles administrativos, que son quienes pueden
    actuar sobre ella; a un consultor no le sirve y le contaría más de la cuenta del sistema.
    """
    actor.exigir_administrativo()
    fuentes = await consultas.estado_fuentes()
    return cuerpo_json({"fuentes": [dict(fuente) for fuente in fuentes]})


@router.get("/{codigo}", summary="Estado del último ciclo de una fuente")
async def estado_ingesta(
    codigo: str, consultas: ConsultasDep, actor: ActorDep, _: ConsentimientoDep
) -> dict[str, Any]:
    """Detalle de una fuente concreta, por su código (`NCO` u `OCDS`)."""
    actor.exigir_administrativo()
    fuente = await consultas.estado_fuente(codigo.upper())
    if fuente is None:
        raise NoEncontrado(f"La fuente {codigo!r} no está registrada.")
    return cuerpo_json(dict(fuente))
