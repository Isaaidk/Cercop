"""Enrutador de los datos de la propia empresa.

Es el único sitio donde una empresa se describe a sí misma. Va aparte de `/v1/usuarios` porque son
dos cosas: aquí están los datos de contacto y el límite del plan; allí, quién entra. Podrían
compartir prefijo y no lo hacen por el mismo motivo que las cuentas se separaron de los accesos: una
lista de rutas que empiezan igual y significan cosas distintas se lee mal, justo cuando hay prisa.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from contratacion.aplicacion.casos_uso.registrar_empresa import (
    actualizar_empresa,
    consultar_empresa,
)
from contratacion.dominio.serializacion import cuerpo_json
from contratacion.infraestructura.adaptadores.entrada.http.dependencias import (
    ActorDep,
    ConsentimientoDep,
    NegociosDep,
)

router = APIRouter(prefix="/v1/negocio", tags=["Empresa"])


class EdicionDeEmpresa(BaseModel):
    """Datos editables de la empresa.

    Todos los campos son obligatorios en el cuerpo aunque el modelo los admita opcionales: la
    edición reemplaza el bloque completo, porque aceptar cambios parciales obligaría a distinguir
    «no lo envíes» de «bórralo», y esa distinción —con un `null` haciendo dos trabajos— es la causa
    habitual de que una dirección desaparezca sin que nadie la borrara.
    """

    nombre: str = Field(max_length=160, examples=["Constructora del Pacífico Cía. Ltda."])
    ruc: str | None = Field(default=None, max_length=20)
    email_contacto: str | None = Field(default=None, max_length=254)
    telefono: str | None = Field(default=None, max_length=20)
    direccion: str | None = Field(default=None, max_length=200)
    ciudad: str | None = Field(default=None, max_length=80)


@router.get("", summary="Datos de la empresa y margen del plan")
async def ver(actor: ActorDep, negocios: NegociosDep, _: ConsentimientoDep) -> dict[str, Any]:
    """Los datos de contacto de la propia empresa, más cuántos usuarios admite el plan.

    Solo para administradores: el plan y los datos de contacto son información de gestión.
    """
    ficha = await consultar_empresa(actor, negocios=negocios)
    return cuerpo_json(ficha.como_diccionario())


@router.put("", summary="Actualizar los datos de la empresa")
async def editar(
    cuerpo: EdicionDeEmpresa,
    actor: ActorDep,
    negocios: NegociosDep,
    _: ConsentimientoDep,
) -> dict[str, Any]:
    """Corrige los datos de la empresa: nombre, RUC, correo, teléfono, dirección y ciudad.

    El nombre y el RUC se pueden corregir porque al registrarse se teclean con prisa. El
    **estado** y el **plan** no: son decisiones de la plataforma, y permitir que una empresa se
    ampliara su propio límite convertiría el plan en una sugerencia.
    """
    ficha = await actualizar_empresa(
        actor,
        nombre_empresa=cuerpo.nombre,
        ruc=cuerpo.ruc,
        email_contacto=cuerpo.email_contacto,
        telefono=cuerpo.telefono,
        direccion=cuerpo.direccion,
        ciudad=cuerpo.ciudad,
        negocios=negocios,
    )
    return cuerpo_json(ficha.como_diccionario())
