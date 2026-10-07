"""Enrutador de palabras clave.

Implementa CU-04. La propiedad que define este enrutador: **agregar un término no consulta la
fuente**. Responde al instante con lo que ya hay y deja el término en la cola; el `worker` lo
atenderá en el próximo ciclo, respetando el presupuesto y el límite de tasa.

El panel refresca llamando a `/v1/terminos/{id}/estado`, que es una lectura barata y no dispara
nada.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from contratacion.aplicacion.casos_uso.encolar_termino import (
    agregar_termino,
    agregar_terminos,
    consultar_estado,
    listar_terminos,
    quitar_termino,
)
from contratacion.dominio.acceso import fuentes_para_vistas
from contratacion.dominio.errores import SinPermiso
from contratacion.dominio.palabras import LONGITUD_MINIMA_TERMINO
from contratacion.dominio.serializacion import cuerpo_json
from contratacion.infraestructura.adaptadores.entrada.http.dependencias import (
    ActorDep,
    AjustesDep,
    ConsentimientoDep,
    TerminosDep,
    VistasDep,
)

router = APIRouter(prefix="/v1/terminos", tags=["Palabras clave"])


class AltaTermino(BaseModel):
    """Cuerpo de la petición para agregar una palabra clave."""

    texto: str = Field(
        min_length=LONGITUD_MINIMA_TERMINO,
        max_length=200,
        description="Palabra o frase que se quiere vigilar.",
        examples=["obras viales"],
    )


class AltaTerminos(BaseModel):
    """Cuerpo de la petición para agregar varias palabras clave de una vez."""

    textos: list[str] = Field(
        min_length=1,
        max_length=200,
        description="Palabras o frases que se quieren vigilar.",
        examples=[["produccion", "cultura", "exposicion"]],
    )


class BajaTermino(BaseModel):
    """Cuerpo de la petición para dar de baja una palabra clave."""

    termino_id: UUID = Field(description="Término que el negocio deja de seguir.")


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Agregar una palabra clave y encolarla para el próximo ciclo",
)
async def crear_termino(
    cuerpo: AltaTermino,
    actor: ActorDep,
    terminos: TerminosDep,
    ajustes: AjustesDep,
    vistas: VistasDep,
    _: ConsentimientoDep,
) -> dict[str, Any]:
    """Suscribe el negocio al término y devuelve su estado de ingesta.

    Responde `202` porque el trabajo **no está hecho**: se ha aceptado para ejecutarse. Devolver
    `201` daría a entender que los datos ya están, y no lo están hasta el próximo ciclo.

    Se exige tener alguna vista con datos: agregar una palabra clave hace que se consulte la
    fuente oficial por ella, y quien no puede ver contrataciones no tiene motivo para provocarla.
    """
    if not fuentes_para_vistas(vistas):
        raise SinPermiso(
            "No tienes ninguna vista concedida que dé acceso al histórico, así que no puedes "
            "agregar palabras clave."
        )
    resultado = await agregar_termino(
        cuerpo.texto,
        actor=actor,
        repositorio=terminos,
        intervalo_min=ajustes.intervalo_ingesta_min,
        maximo_terminos=ajustes.maximo_terminos_negocio,
    )
    return cuerpo_json(resultado.como_diccionario())


@router.post(
    "/lote",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Agregar varias palabras clave de una vez",
)
async def crear_terminos(
    cuerpo: AltaTerminos,
    actor: ActorDep,
    terminos: TerminosDep,
    ajustes: AjustesDep,
    vistas: VistasDep,
    _: ConsentimientoDep,
) -> dict[str, Any]:
    """Suscribe el negocio a una lista de palabras clave y las deja en la cola.

    Existe porque pegar una lista de temas es el uso real: nadie escribe veinte palabras de una en
    una. Va en **una** petición y no en veinte porque cada alta sobre una base remota cuesta abrir
    su conexión; veinte peticiones encadenadas se irían a más de un minuto de espera.

    Se responde `202` como en el alta individual: el trabajo queda aceptado, no hecho.
    """
    if not fuentes_para_vistas(vistas):
        raise SinPermiso(
            "No tienes ninguna vista concedida que dé acceso al histórico, así que no puedes "
            "agregar palabras clave."
        )
    resultado = await agregar_terminos(
        cuerpo.textos,
        actor=actor,
        repositorio=terminos,
        maximo_terminos=ajustes.maximo_terminos_negocio,
    )
    return cuerpo_json(resultado.como_diccionario())


@router.post(
    "/quitar",
    summary="Dar de baja una palabra clave del negocio",
)
async def quitar_suscripcion(
    cuerpo: BajaTermino,
    actor: ActorDep,
    terminos: TerminosDep,
    _: ConsentimientoDep,
) -> dict[str, Any]:
    """Deja de seguir la palabra clave. El término del catálogo no se borra.

    Existe porque faltaba: el panel podía deseleccionar una palabra —dejar de filtrar por ella— pero
    no darla de baja, así que la suscripción seguía activa y volver a agregarla devolvía «ya se
    consultó hace poco». Ahora la baja es real y **volver a agregarla la encola otra vez**.

    Responder con `quitado: false` no es un error: significa que ya no estaba activa, que es
    exactamente lo que la persona quería.

    Va **antes** de las rutas con `{termino_id}` por la norma de la casa: FastAPI resuelve en orden
    de declaración y una ruta literal detrás de una paramétrica no se alcanza nunca.
    """
    quitado = await quitar_termino(cuerpo.termino_id, actor=actor, repositorio=terminos)
    return cuerpo_json({"termino_id": str(cuerpo.termino_id), "quitado": quitado})


@router.get("", summary="Palabras clave del negocio")
async def listar(
    actor: ActorDep,
    terminos: TerminosDep,
    ajustes: AjustesDep,
    _: ConsentimientoDep,
) -> dict[str, Any]:
    """Las palabras clave a las que está suscrito el negocio, con su estado de ingesta.

    Es lo que permite al panel pintar los filtros al abrirse: sin esto habría que guardar los
    términos en el navegador y se perderían al cambiar de equipo.

    Se comprueba el consentimiento porque la lista de palabras clave es información del negocio y
    revela qué está siguiendo: no es un dato neutro que pueda verse antes de aceptar los términos.
    """
    resultado = await listar_terminos(
        actor, repositorio=terminos, intervalo_min=ajustes.intervalo_ingesta_min
    )
    return cuerpo_json({"terminos": [estado.como_diccionario() for estado in resultado]})


@router.get("/{termino_id}/estado", summary="Estado de ingesta de una palabra clave")
async def estado_termino(
    termino_id: UUID,
    terminos: TerminosDep,
    ajustes: AjustesDep,
) -> dict[str, Any]:
    """Consulta barata para que el panel refresque sin volver a agregar el término."""
    resultado = await consultar_estado(
        termino_id,
        repositorio=terminos,
        intervalo_min=ajustes.intervalo_ingesta_min,
    )
    return cuerpo_json(resultado.como_diccionario())
