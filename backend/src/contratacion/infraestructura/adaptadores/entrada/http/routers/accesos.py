"""Enrutador de accesos a vistas.

Es la cara visible de CU-15 y CU-16 y el soporte del modelo de suscripción: el administrador elige
un plazo de una lista y pulsa conceder. **No hay ningún endpoint que acepte una fecha**: el cliente
manda un código (`30d`) y el cálculo del vencimiento ocurre en el servidor, donde no puede
manipularse.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

from contratacion.aplicacion.casos_uso.gestionar_acceso import (
    conceder_acceso,
    consultar_accesos,
    listar_usuarios,
    retirar_acceso,
)
from contratacion.dominio.acceso import (
    DIAS_AVISO_VENCIMIENTO,
    ETIQUETAS_PLAZO,
    ETIQUETAS_VISTA,
    Plazo,
    Vista,
)
from contratacion.dominio.serializacion import cuerpo_json
from contratacion.infraestructura.adaptadores.entrada.http.dependencias import (
    AccesosDep,
    ActorDep,
    ConsentimientoDep,
)
from contratacion.infraestructura.adaptadores.salida.cache.cliente import obtener_cache

router = APIRouter(prefix="/v1/accesos", tags=["Accesos"])


class ConcesionAcceso(BaseModel):
    """Cuerpo para conceder acceso a una vista."""

    vista: Vista = Field(description="Vista del panel a la que se concede acceso.")
    plazo: Plazo = Field(
        description="Plazo de la concesión. El vencimiento lo calcula el servidor.",
        examples=["30d"],
    )


@router.get("/catalogo", summary="Vistas y plazos disponibles")
async def catalogo(_: ActorDep) -> dict[str, Any]:
    """Catálogo cerrado para que el panel pinte los botones sin conocer las reglas.

    Se sirve desde el código del dominio y no desde la base de datos a propósito: una vista es una
    frontera de autorización, y añadir una debe ser un cambio de código revisado, no una fila
    insertada en una tabla de configuración.

    Exige sesión aunque el contenido sea estático, y no es un detalle: era el **único** endpoint sin
    guardián, así que una empresa suspendida seguía leyendo de aquí. El catálogo no son datos de
    contratación, pero «suspendida no ve nada» tiene que ser cierto entero y no casi entero:
    basta un
    endpoint abierto para que la suspensión deje de significar lo que dice.
    """
    return {
        "vistas": [{"codigo": str(vista), "etiqueta": ETIQUETAS_VISTA[vista]} for vista in Vista],
        "plazos": [
            {
                "codigo": str(plazo),
                "etiqueta": ETIQUETAS_PLAZO[plazo],
                "es_calendario": plazo.es_de_calendario,
            }
            for plazo in Plazo
        ],
        "aviso_vencimiento_dias": DIAS_AVISO_VENCIMIENTO,
    }


@router.get("/usuarios", summary="Usuarios registrados del negocio y sus vistas")
async def usuarios(
    actor: ActorDep,
    accesos: AccesosDep,
    _: ConsentimientoDep,
    negocio: Annotated[
        UUID | None,
        Query(description="Solo para el superadministrador: negocio sobre el que se consulta."),
    ] = None,
) -> dict[str, Any]:
    """Usuarios **registrados**, con el estado de cada vista en verde o rojo.

    Son las cuentas que existen, no las conectadas: la presencia llega en la fase 4 y se servirá por
    su propio canal. Mezclarlas aquí daría un listado cuyo contenido cambia con el tráfico.
    """
    filas = await listar_usuarios(actor, repositorio=accesos, negocio_solicitado=negocio)
    return cuerpo_json({"usuarios": [fila.como_diccionario() for fila in filas]})


@router.get("/usuarios/{usuario_id}", summary="Estado de las vistas de un usuario")
async def tablero_usuario(
    usuario_id: UUID,
    actor: ActorDep,
    accesos: AccesosDep,
    _: ConsentimientoDep,
    negocio: Annotated[UUID | None, Query()] = None,
) -> dict[str, Any]:
    """Cualquiera puede consultar sus propias vistas; las de otro, solo un administrador."""
    resultado = await consultar_accesos(
        actor, usuario_id=usuario_id, repositorio=accesos, negocio_solicitado=negocio
    )
    return cuerpo_json(resultado.como_diccionario())


@router.post(
    "/usuarios/{usuario_id}/vistas",
    status_code=status.HTTP_201_CREATED,
    summary="Conceder o extender el acceso a una vista",
)
async def conceder(
    usuario_id: UUID,
    cuerpo: ConcesionAcceso,
    actor: ActorDep,
    accesos: AccesosDep,
    _: ConsentimientoDep,
    negocio: Annotated[UUID | None, Query()] = None,
) -> dict[str, Any]:
    """Concede el acceso durante el plazo pedido.

    Si el usuario ya tenía acceso, **no lo acorta**: se añade una concesión nueva y la vigente pasa
    a ser la de vencimiento más lejano. Un administrador que renueva nunca puede quitarle días sin
    querer a quien ya había pagado.
    """
    resultado = await conceder_acceso(
        actor,
        usuario_id=usuario_id,
        vista_codigo=str(cuerpo.vista),
        plazo_codigo=str(cuerpo.plazo),
        repositorio=accesos,
        cache=obtener_cache(),
        negocio_solicitado=negocio,
    )
    return cuerpo_json(resultado.como_diccionario())


@router.delete("/usuarios/{usuario_id}/vistas/{vista}", summary="Retirar el acceso a una vista")
async def retirar(
    usuario_id: UUID,
    vista: Vista,
    actor: ActorDep,
    accesos: AccesosDep,
    _: ConsentimientoDep,
    negocio: Annotated[UUID | None, Query()] = None,
) -> dict[str, Any]:
    """Retira el acceso de inmediato.

    No se borra nada: se marca la concesión como retirada, de modo que queda el rastro de quién la
    quitó y cuándo. El permiso cacheado se invalida al instante, así que el cambio se nota en la
    siguiente petición y no «en un rato».
    """
    resultado = await retirar_acceso(
        actor,
        usuario_id=usuario_id,
        vista_codigo=str(vista),
        repositorio=accesos,
        cache=obtener_cache(),
        negocio_solicitado=negocio,
    )
    return cuerpo_json(resultado.como_diccionario())
