"""Enrutador de estado de la ingesta.

Sirve para que el panel administrativo pueda responder a la pregunta «¿está entrando información?»
sin acceso a la base ni a los registros del proceso. Expone el último ciclo de cada fuente: cuándo
empezó, cuándo terminó, cuántos registros nuevos y actualizados hubo, cuántas peticiones se
consumieron y qué avisos se registraron.

Y expone, aparte y para cualquiera con sesión, la **versión de los datos**: un solo número que sube
cuando la ingesta escribe. Es lo que permite que el panel se refresque solo al terminar el ciclo
—con las contrataciones y sus CPC ya escritos— en lugar de recargar la tabla cada minuto a ciegas o
de quedarse mostrando lo de hace un cuarto de hora.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from contratacion.aplicacion.generaciones import leer_generacion
from contratacion.dominio.errores import NoEncontrado
from contratacion.dominio.serializacion import cuerpo_json
from contratacion.infraestructura.adaptadores.entrada.http.dependencias import (
    ActorDep,
    CacheDep,
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


@router.get("/version", summary="Versión de los datos, para saber si hay algo nuevo")
async def version_datos(cache: CacheDep, actor: ActorDep, _: ConsentimientoDep) -> dict[str, Any]:
    """El número que cambia cada vez que la ingesta escribe: lo consulta el panel para refrescarse.

    Va **antes** de `/{codigo}` a propósito, y no es cosmético: FastAPI resuelve las rutas en orden
    de declaración, así que con esta línea más abajo, `version` entraría por `/{codigo}` y la
    respuesta sería un 404 diciendo que la fuente «VERSION» no está registrada.

    Cuesta una lectura de caché de una clave —nada de base de datos—, porque su razón de ser es
    preguntarla a menudo: el panel la pide cada minuto para saber si el ciclo terminó en lugar de
    recargar la tabla a ciegas. Se admite un memo de dos segundos para que mil paneles preguntando a
    la vez no sean mil lecturas: refrescar la pantalla no necesita precisión de milisegundos.
    """
    generacion = await leer_generacion(cache, ttl_memo_seg=2)
    return cuerpo_json({"generacion": generacion})


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
