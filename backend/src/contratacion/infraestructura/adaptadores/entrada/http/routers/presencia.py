"""Enrutador de presencia: latidos, cuadro y transmisión en vivo.

Cómo se mantiene el panel al día
---------------------------------
Hay dos mecanismos y **ninguno es prescindible**:

1. **Avisos.** Cada conexión o cierre publica un evento en el canal del negocio. Es lo que hace que
   el punto cambie de color al instante, sin recargar.
2. **Instantánea periódica.** Cada pocos segundos se reenvía el cuadro completo, releyendo el
   almacén. Es lo que hace que el panel sea **correcto** y no solo rápido.

El segundo parece redundante y no lo es. Un rojo por falta de señal no genera ningún aviso —nadie
avisa de que se le fue el wifi—, así que sin la relectura el panel mantendría en verde a quien ya se
fue. Y si un aviso se pierde porque una réplica se reinició, la instantánea lo corrige sola. Los
avisos dan inmediatez; la instantánea, verdad.

Por qué esto **no** usa `EventSource` ni `navigator.sendBeacon`
--------------------------------------------------------------
`EventSource` no permite enviar cabeceras, así que la única forma de autenticarlo sería poner el
token de acceso en la dirección. Eso lo escribiría en el registro de cada proxy, cada balanceador y
cada servidor por el que pase, que es exactamente donde no debe estar. En su lugar el panel usa
`fetch` y lee el flujo por partes, enviando la cabecera `Authorization` como en cualquier otra
petición.

Por la misma razón el aviso de cierre de ventana usa `fetch` con `keepalive: true` y no
`sendBeacon`: `sendBeacon` tampoco admite cabeceras, y la alternativa sería aceptar el token por el
cuerpo. Se evita tener **dos formas** de autenticarse, porque la segunda es siempre la que se olvida
de revisar. La diferencia práctica es nula —`keepalive` envía la petición igualmente durante la
descarga de la página— y a cambio solo hay un camino de autenticación que auditar.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from contratacion.aplicacion.casos_uso.presencia import (
    cerrar_por_ventana,
    cuadro_del_negocio,
    latir,
)
from contratacion.dominio.presencia import SEGUNDOS_ENTRE_INSTANTANEAS, EstadoPresencia
from contratacion.dominio.serializacion import a_json, cuerpo_json
from contratacion.infraestructura.adaptadores.entrada.http.dependencias import (
    AccesosDep,
    ActorDep,
    AjustesDep,
    BusDep,
    PresenciaDep,
    SesionesDep,
)

router = APIRouter(prefix="/v1/presencia", tags=["Presencia"])

registro = logging.getLogger(__name__)


class LatidoCuerpo(BaseModel):
    """Cuerpo del latido."""

    sesion_id: UUID = Field(description="Sesión que sigue viva. Sale del token de acceso.")


class CierreCuerpo(BaseModel):
    """Cuerpo del aviso de cierre de ventana."""

    sesion_id: UUID = Field(description="Sesión que se cierra.")


@router.post("/latido", summary="Anotar que la sesión sigue viva")
async def marcar_latido(
    cuerpo: LatidoCuerpo,
    actor: ActorDep,
    ajustes: AjustesDep,
    presencia: PresenciaDep,
    sesiones: SesionesDep,
    bus: BusDep,
) -> dict[str, Any]:
    """Refresca la señal de vida de la sesión.

    La respuesta dice cada cuánto hay que repetirla, para que el panel no tenga que saberlo. Así, si
    alguien cambia la configuración, los paneles ya abiertos se ajustan solos en el latido siguiente
    en lugar de seguir con el valor con el que se abrieron.
    """
    evento = await latir(
        actor,
        sesion_id=cuerpo.sesion_id,
        registro=presencia,
        sesiones=sesiones,
        bus=bus,
        ttl_seg=ajustes.presencia_ttl_seg,
    )
    return cuerpo_json(
        {
            "momento": evento.momento.isoformat(),
            "estado": str(evento.presencia.estado if evento.presencia else EstadoPresencia.VERDE),
            "repetir_en_seg": ajustes.heartbeat_seg,
            "vigencia_seg": ajustes.presencia_ttl_seg,
        }
    )


@router.post("/cierre", summary="Avisar de que se cerró la ventana")
async def avisar_cierre(
    cuerpo: CierreCuerpo,
    actor: ActorDep,
    presencia: PresenciaDep,
    sesiones: SesionesDep,
    bus: BusDep,
) -> dict[str, Any]:
    """Cierra la sesión porque la persona cerró la pestaña.

    Es una mejora de latencia, no un requisito de corrección: si este aviso no llega —y con un
    navegador cerrándose por delante, no siempre llega— el rojo aparece igual cuando caduca la
    señal. Por eso el panel lo manda sin esperar respuesta y sin reintentar.
    """
    evento = await cerrar_por_ventana(
        actor,
        sesion_id=cuerpo.sesion_id,
        registro=presencia,
        sesiones=sesiones,
        bus=bus,
    )
    return cuerpo_json({"momento": evento.momento.isoformat(), "estado": str(EstadoPresencia.ROJO)})


@router.get("", summary="Quién está conectado ahora")
async def consultar_presencia(
    actor: ActorDep,
    ajustes: AjustesDep,
    accesos: AccesosDep,
    sesiones: SesionesDep,
    presencia: PresenciaDep,
    negocio: Annotated[
        UUID | None,
        Query(description="Solo para un administrador: negocio sobre el que se consulta."),
    ] = None,
) -> dict[str, Any]:
    """Cuadro completo, con el color y el motivo de cada persona.

    Es el mismo cálculo que alimenta la relectura periódica del flujo. Tener un solo camino —y no
    uno distinto para la carga inicial— evita que las dos formas de obtener el mismo dato se
    separen con el tiempo y acaben dando respuestas distintas.
    """
    cuadro = await cuadro_del_negocio(
        actor,
        accesos=accesos,
        sesiones=sesiones,
        registro=presencia,
        ttl_seg=ajustes.presencia_ttl_seg,
        negocio_solicitado=negocio,
    )
    return cuerpo_json(cuadro.como_diccionario())


@router.get(
    "/eventos",
    summary="Cambios de presencia en vivo",
    response_class=StreamingResponse,
    responses={
        200: {
            # Sin esta declaración, el contrato anunciaría `application/json` y quien lo leyera
            # —persona o generador de clientes— esperaría una respuesta que termina. Este flujo no
            # termina: se queda abierto mientras la persona mire el panel.
            "content": {"text/event-stream": {}},
            "description": (
                "Flujo de eventos: `instantanea` con el cuadro completo, `conectado` y "
                "`desconectado` con cada cambio."
            ),
        }
    },
)
async def eventos(
    peticion: Request,
    actor: ActorDep,
    ajustes: AjustesDep,
    accesos: AccesosDep,
    sesiones: SesionesDep,
    presencia: PresenciaDep,
    bus: BusDep,
) -> StreamingResponse:
    """Abre un flujo de eventos con los cambios de presencia del negocio.

    El flujo se cierra cuando el cliente se desconecta, y eso se comprueba en cada vuelta del bucle.
    No hay tiempo máximo de vida: una sesión de panel puede quedarse abierta toda la jornada, y
    cerrarla por tiempo obligaría a reconectar y a parpadear en la interfaz sin ninguna ganancia.

    La instantánea periódica hace además de latido del propio enlace. Sin ningún mensaje durante un
    rato, nginx y Cloudflare cortan la conexión por inactividad y el panel se queda congelado sin
    que nadie se entere; con ella, siempre hay tráfico y no hace falta un latido aparte.
    """

    async def transmitir() -> AsyncIterator[str]:
        # La suscripción se abre **antes** de la primera lectura. Al revés se perdería cualquier
        # aviso ocurrido entre las dos, y el panel arrancaría con un estado que ya no es cierto.
        async with bus.suscribir(negocio_id=actor.negocio_id) as canal:
            # Y se comprueba la desconexión antes de la primera lectura: si el cliente ya se fue, no
            # tiene sentido ir a la base a componer un cuadro que nadie va a ver. No es una
            # optimización de escritorio —cada panel que se cierra durante la carga llegaría hasta
            # aquí— y cuesta una comprobación barata.
            if await peticion.is_disconnected():
                return

            cuadro = await cuadro_del_negocio(
                actor,
                accesos=accesos,
                sesiones=sesiones,
                registro=presencia,
                ttl_seg=ajustes.presencia_ttl_seg,
            )
            yield _evento_servidor("instantanea", cuadro.como_diccionario())

            while not await peticion.is_disconnected():
                aviso = await canal.siguiente(SEGUNDOS_ENTRE_INSTANTANEAS)
                if aviso is not None:
                    yield _evento_servidor(str(aviso.tipo), aviso.como_diccionario())
                    continue

                # No llegó ningún aviso: se reenvía el cuadro completo. Este es el camino que
                # descubre los rojos por falta de señal, que por definición no generan ningún aviso.
                cuadro = await cuadro_del_negocio(
                    actor,
                    accesos=accesos,
                    sesiones=sesiones,
                    registro=presencia,
                    ttl_seg=ajustes.presencia_ttl_seg,
                )
                yield _evento_servidor("instantanea", cuadro.como_diccionario())

    return StreamingResponse(
        transmitir(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            # Sin esto, nginx acumula la respuesta en su búfer y el flujo llega a ráfagas o no
            # llega nunca.
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _evento_servidor(nombre: str, datos: Mapping[str, Any]) -> str:
    """Formatea un evento como exige el protocolo de envío de eventos.

    El nombre se limpia de saltos de línea porque un salto dentro del campo `event` inyectaría
    cabeceras del protocolo: bastaría con que un valor llegara con un salto para que el cliente
    interpretara como evento algo que es un dato.
    """
    limpio = nombre.replace("\n", " ").replace("\r", " ")
    return f"event: {limpio}\ndata: {a_json(datos)}\n\n"
