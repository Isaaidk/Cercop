"""Enrutador de la administración de la plataforma.

Va aparte de `/v1/negocio` —que es «los datos de mi empresa»— porque son dos cosas distintas y con
dueños distintos: allí una empresa se describe a sí misma, aquí el dueño del sistema decide sobre
las demás. Juntarlos dejaría rutas que empiezan igual y significan lo contrario, que es justo lo que
no se quiere leer con prisa.

Todos los endpoints exigen el rol de plataforma. La comprobación vive en el caso de uso y no aquí:
la regla es de negocio —«solo el dueño del sistema administra empresas ajenas»— y debe negarse igual
desde la API, desde el worker o desde una tarea programada.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, status

from contratacion.aplicacion.casos_uso.administrar_negocios import (
    listar_empresas,
    reactivar_empresa,
    suspender_empresa,
)
from contratacion.dominio.serializacion import cuerpo_json
from contratacion.infraestructura.adaptadores.entrada.http.dependencias import (
    ActorDep,
    AuditoriaDep,
    NegociosDep,
)

router = APIRouter(prefix="/v1/plataforma", tags=["Plataforma"])


@router.get("/empresas", summary="Todas las empresas registradas")
async def empresas(actor: ActorDep, negocios: NegociosDep) -> dict[str, Any]:
    """El censo de empresas: identidad, estado y cuántas cuentas tiene cada una.

    No lleva la puerta de consentimiento a propósito. Esa puerta protege datos de contratación de
    terceros; esto es la lista de clientes de la plataforma, y quien la pide ya ha aceptado los
    términos para poder entrar. Añadirla aquí no protegería nada nuevo y sí dejaría al dueño del
    sistema sin poder ver sus empresas si su propia aceptación caducara.
    """
    fichas = await listar_empresas(actor, repositorio=negocios)
    return cuerpo_json({"empresas": [ficha.como_diccionario() for ficha in fichas]})


@router.post(
    "/empresas/{negocio_id}/suspension",
    status_code=status.HTTP_201_CREATED,
    summary="Suspender el acceso de una empresa",
)
async def suspender(
    negocio_id: UUID,
    actor: ActorDep,
    negocios: NegociosDep,
    auditoria: AuditoriaDep,
) -> dict[str, Any]:
    """Corta el acceso de una empresa entera.

    Sus usuarios dejan de poder leer nada y ven **solo** el aviso de suspensión. No se borra nada:
    suspender es reversible y tiene que seguir siéndolo.
    """
    resultado = await suspender_empresa(
        actor,
        negocio_id=negocio_id,
        repositorio=negocios,
        auditoria=auditoria,
    )
    return cuerpo_json(resultado.como_diccionario())


@router.post(
    "/empresas/{negocio_id}/reactivacion",
    status_code=status.HTTP_201_CREATED,
    summary="Devolver el acceso a una empresa",
)
async def reactivar(
    negocio_id: UUID,
    actor: ActorDep,
    negocios: NegociosDep,
    auditoria: AuditoriaDep,
) -> dict[str, Any]:
    """Devuelve el acceso. Las vistas que la empresa tuviera concedidas siguen donde estaban."""
    resultado = await reactivar_empresa(
        actor,
        negocio_id=negocio_id,
        repositorio=negocios,
        auditoria=auditoria,
    )
    return cuerpo_json(resultado.como_diccionario())
