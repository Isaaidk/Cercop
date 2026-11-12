"""Procesos con oferta (OCDS): los anexos para la proforma y el monto del proceso.

Esta ruta **sí** habla con un servicio ajeno (los datos abiertos del SERCOP, una petición por
proceso), como la consulta de contratos del perfil: por eso lleva tope por usuario, y el adaptador
va con cortacircuitos, compartimento y memoria de media hora.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends

from contratacion.aplicacion.casos_uso.anexos_ocds import anexos_del_proceso
from contratacion.dominio.serializacion import cuerpo_json
from contratacion.infraestructura.adaptadores.entrada.http.dependencias import (
    ConsentimientoDep,
    VistasDep,
)
from contratacion.infraestructura.adaptadores.entrada.http.limites import LimitePorUsuario
from contratacion.infraestructura.adaptadores.salida.bd.procesos import RepositorioProcesos
from contratacion.infraestructura.adaptadores.salida.bd.sesion import obtener_motor
from contratacion.infraestructura.adaptadores.salida.fuentes.ocds_proceso import (
    FichasOcds,
    obtener_fichas,
)

router = APIRouter(prefix="/v1/procesos", tags=["Procesos con oferta"])


def repositorio_procesos() -> RepositorioProcesos:
    return RepositorioProcesos(obtener_motor())


@router.get(
    "/{registro_id}/anexos",
    summary="Anexos para la proforma (TDR, pliego, última acta) y monto de un proceso OCDS",
    dependencies=[Depends(LimitePorUsuario("procesos.anexos", 20, 60))],
)
async def anexos(
    registro_id: UUID,
    vistas: VistasDep,
    _: ConsentimientoDep,
    registros: Annotated[RepositorioProcesos, Depends(repositorio_procesos)],
    fichas: Annotated[FichasOcds, Depends(obtener_fichas)],
) -> dict[str, Any]:
    """400 para las ínfimas (sus anexos van por la ficha); 503 si la fuente no responde."""
    return cuerpo_json(
        await anexos_del_proceso(vistas, registro_id, registros=registros, fichas=fichas)
    )
