"""Enrutador de la lista de términos de CPC que vigila una empresa.

Es la parte que hace que el filtro por CPC sirva para trabajar y no solo para probar: la lista vive
en el servidor, así que **la ve todo el equipo** y sigue ahí al recargar. Antes vivía solo en el
navegador, y con eso cada persona escribía la suya.
Tres decisiones que se ven leyendo las rutas.

**No hace falta ninguna vista concedida**, a diferencia de las palabras clave. Aquel alta tiene que
comprobar el permiso porque encola una consulta a la fuente oficial sobre un histórico al que hay
que tener acceso; esto solo anota un criterio de búsqueda y no toca la fuente ni abre ninguna
puerta.

**La lista no dispara ingesta.** Es la diferencia de fondo con `/v1/terminos`, y conviene no
confundirlas al leer una petición: un término de CPC acota lo que ya está descargado, sin pedir nada
a nadie.

**Quitar un término va por `POST /quitar`** y no por un `DELETE /{texto}`. El término lleva espacios
y acentos —«LAVADO Y ENGRASADO DE AUTOMOTORES»— y, metido en la ruta, el resultado dependería de que
quien llama lo escape bien. En el cuerpo del mensaje no hay nada que escapar, y el día que alguien
escriba un cliente a mano no se encontrará con una ruta rota por un carácter.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Body, status
from pydantic import BaseModel, Field

from contratacion.aplicacion.casos_uso.gestionar_cpc import (
    agregar,
    limpiar,
    listar,
    quitar,
)
from contratacion.dominio.palabras import LONGITUD_MINIMA_TERMINO
from contratacion.dominio.serializacion import cuerpo_json
from contratacion.infraestructura.adaptadores.entrada.http.dependencias import (
    ActorDep,
    ConsentimientoDep,
    CpcDep,
)

router = APIRouter(prefix="/v1/cpc", tags=["CPC"])

registro = logging.getLogger(__name__)


class TerminoCpc(BaseModel):
    """Un término suelto."""

    texto: str = Field(
        max_length=160,
        description="Palabra, fragmento del nombre del CPC o código completo.",
        examples=["lavado", "871410032"],
    )


class TerminosCpc(BaseModel):
    """Una lista pegada, con los separadores que salen de una hoja de cálculo."""

    textos: list[str] = Field(
        min_length=1,
        max_length=500,
        description=(
            "Términos separados por comas, punto y coma o saltos de línea. Se descartan los de "
            f"menos de {LONGITUD_MINIMA_TERMINO} letras."
        ),
        examples=[["lavado", "engrasado", "871410032"]],
    )


@router.get("", summary="Términos de CPC que vigila el negocio")
async def ver_claves(actor: ActorDep, cpc: CpcDep, _: ConsentimientoDep) -> dict[str, Any]:
    """La lista guardada, en orden de alta."""
    claves = await listar(actor, repositorio=cpc)
    return cuerpo_json({"claves": list(claves)})


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Añadir un término a la lista de CPC",
)
async def anadir_clave(
    cuerpo: TerminoCpc, actor: ActorDep, cpc: CpcDep, _: ConsentimientoDep
) -> dict[str, Any]:
    """Añade un término. Si ya estaba, lo dice en lugar de fallar."""
    resultado = await agregar(actor, textos=[cuerpo.texto], repositorio=cpc)
    return cuerpo_json(resultado.como_diccionario())


@router.post(
    "/lote",
    status_code=status.HTTP_201_CREATED,
    summary="Añadir varios términos de CPC de una vez",
)
async def anadir_claves(
    cuerpo: TerminosCpc, actor: ActorDep, cpc: CpcDep, _: ConsentimientoDep
) -> dict[str, Any]:
    """Añade una lista pegada.

    Va en **una** petición porque pegar una lista es el uso real —nadie escribe veinte
    clasificaciones de una en una— y el servidor aplica los mismos separadores y el mismo mínimo que
    la pantalla, así que el contador que se ve antes de pulsar coincide con lo que se guarda.
    """
    resultado = await agregar(actor, textos=cuerpo.textos, repositorio=cpc)
    return cuerpo_json(resultado.como_diccionario())


@router.post("/quitar", summary="Quitar un término de la lista de CPC")
async def quitar_clave(
    actor: ActorDep,
    cpc: CpcDep,
    _: ConsentimientoDep,
    cuerpo: Annotated[TerminoCpc, Body()],
) -> dict[str, Any]:
    """Quita un término. Quitar dos veces el mismo no es un error: la segunda dice que no estaba."""
    quitada = await quitar(actor, texto=cuerpo.texto, repositorio=cpc)
    return cuerpo_json({"quitada": quitada})


@router.delete("", summary="Vaciar la lista de CPC")
async def vaciar_claves(actor: ActorDep, cpc: CpcDep, _: ConsentimientoDep) -> dict[str, Any]:
    """Vacía la lista y dice cuántos había."""
    quitadas = await limpiar(actor, repositorio=cpc)
    return cuerpo_json({"quitadas": quitadas})
