"""Enrutador de políticas y consentimiento.

Cuatro endpoints, y el diseño de cuál se bloquea y cuál no es la parte importante:

| Endpoint | ¿Bloqueado sin aceptar? |
|---|---|
| consultar el estado | **No** |
| leer el texto completo | **No** |
| aceptar | **No** — sería imposible salir del bloqueo |
| revocar | **No** — retirar un consentimiento no puede requerir el consentimiento |

Los cuatro quedan fuera de la puerta por la misma razón: si aceptar estuviera detrás de la puerta,
nadie podría aceptar nunca y el aplicativo quedaría inutilizable para todo el mundo. Es el fallo
clásico de este tipo de bloqueo y merece comprobarse con una prueba.

El resto de endpoints que devuelven datos sí pasan por la puerta, y esa comprobación vive en
`dependencias.py`, aplicada enróuter por enrutador en lugar de globalmente: una dependencia global
también alcanzaría a `/salud`, al inicio de sesión y a este mismo enrutador, y habría que excluirlos
con excepciones que alguien puede olvidar al añadir una ruta nueva.

La dirección IP y el agente de usuario de la aceptación llegan en cabeceras que el cliente controla.
No se validan aquí: el adaptador de base de datos las valida y las recorta antes de guardarlas, en
un solo sitio y también para la auditoría. Repetir la validación en el enrutador crearía dos reglas
que pueden separarse.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Header, status
from pydantic import BaseModel, Field

from contratacion.aplicacion.casos_uso.consentimiento import aceptar, estado, revocar, texto
from contratacion.dominio.politicas import TipoPolitica
from contratacion.dominio.serializacion import cuerpo_json
from contratacion.infraestructura.adaptadores.entrada.http.dependencias import (
    ActorDep,
    ConsentimientosDep,
    CuentasDep,
    PoliticasDep,
)

router = APIRouter(prefix="/v1/politicas", tags=["Políticas y consentimiento"])


class Aceptacion(BaseModel):
    """Cuerpo de la aceptación.

    Se exigen la versión y la huella del texto que el cliente dice haber mostrado. No son un detalle
    de trazabilidad: son lo que permite comprobar que se aceptó **el texto que estaba delante**. Si
    la redacción cambió mientras la persona leía, no coincidirán y la aceptación se rechazará en
    lugar de guardar una prueba que afirma algo que no ocurrió.
    """

    version: int = Field(gt=0, description="Versión del texto que se estaba mostrando.")
    hash: str = Field(
        min_length=64,
        max_length=64,
        description="Huella del texto mostrado, tal y como la devolvió el endpoint del texto.",
        examples=["9f2c1a..."],
    )


@router.get("", summary="Qué falta por aceptar")
async def consultar_estado(
    actor: ActorDep,
    politicas: PoliticasDep,
    consentimientos: ConsentimientosDep,
) -> dict[str, Any]:
    """Estado del consentimiento de quien llama, con el catálogo de textos.

    Los textos **no** viajan aquí: solo su título, versión y huella. El texto completo se pide con
    el enlace «términos y condiciones», que es justo lo que hace el navegador cuando alguien lo
    pulsa. Mandarlo siempre sería enviar varios miles de caracteres para pintar una casilla.
    """
    resultado = await estado(actor, politicas=politicas, consentimientos=consentimientos)
    return cuerpo_json(resultado.como_diccionario())


@router.get("/{tipo}", summary="Texto completo de una política")
async def consultar_texto(tipo: TipoPolitica, politicas: PoliticasDep) -> dict[str, Any]:
    """El texto íntegro, con su versión y su huella.

    La huella se devuelve junto al texto para que el cliente declare exactamente esa al aceptar, sin
    recalcularla: si se calculara en el navegador, dos formas de normalizar el texto podrían dar
    huellas distintas y la aceptación se rechazaría sin que nadie entienda por qué.
    """
    publicada = await texto(tipo, politicas=politicas)
    return cuerpo_json(
        {
            "tipo": str(publicada.tipo),
            "titulo": publicada.titulo,
            "version": publicada.version,
            "hash": publicada.hash,
            "vigente_desde": publicada.vigente_desde.isoformat(),
            "texto": publicada.texto,
        }
    )


@router.post(
    "/{tipo}/aceptacion",
    status_code=status.HTTP_201_CREATED,
    summary="Aceptar una política",
)
async def aceptar_politica(
    tipo: TipoPolitica,
    cuerpo: Aceptacion,
    actor: ActorDep,
    politicas: PoliticasDep,
    consentimientos: ConsentimientosDep,
    cuentas: CuentasDep,
    user_agent: Annotated[str | None, Header()] = None,
    x_forwarded_for: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    """Registra la aceptación con su evidencia y levanta el bloqueo de la cuenta.

    Devuelve el estado actualizado para que el cliente no tenga que preguntar otra vez si le queda
    algo pendiente: si hay más de un texto obligatorio, la pantalla encadena el siguiente sin una
    ida y vuelta adicional.
    """
    publicada = await aceptar(
        actor,
        tipo=tipo,
        version=cuerpo.version,
        hash_texto=cuerpo.hash,
        politicas=politicas,
        consentimientos=consentimientos,
        cuentas=cuentas,
        ip=x_forwarded_for,
        user_agent=user_agent,
    )
    restante = await estado(actor, politicas=politicas, consentimientos=consentimientos)
    return cuerpo_json(
        {
            "aceptado": {
                "tipo": str(publicada.tipo),
                "version": publicada.version,
                "hash": publicada.hash,
            },
            **restante.como_diccionario(),
        }
    )


@router.post("/{tipo}/revocacion", summary="Retirar el consentimiento")
async def revocar_politica(
    tipo: TipoPolitica,
    actor: ActorDep,
    politicas: PoliticasDep,
    consentimientos: ConsentimientosDep,
    cuentas: CuentasDep,
    user_agent: Annotated[str | None, Header()] = None,
    x_forwarded_for: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    """Retira el consentimiento y **bloquea el aplicativo** hasta que se vuelva a aceptar.

    La respuesta lo dice explícitamente para que la interfaz no tenga que deducirlo: el cliente debe
    llevar a la pantalla de aceptación, no mostrar un aviso de éxito y dejar a la persona chocando
    contra un bloqueo sin entender por qué.
    """
    afectadas = await revocar(
        actor,
        tipo=tipo,
        politicas=politicas,
        consentimientos=consentimientos,
        cuentas=cuentas,
        ip=x_forwarded_for,
        user_agent=user_agent,
    )
    restante = await estado(actor, politicas=politicas, consentimientos=consentimientos)
    return cuerpo_json(
        {
            "revocado": str(tipo),
            "aceptaciones_revocadas": afectadas,
            "bloqueado": restante.pendientes.hay_pendientes,
            **restante.como_diccionario(),
        }
    )
