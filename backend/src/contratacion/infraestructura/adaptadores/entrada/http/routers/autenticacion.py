"""Enrutador de autenticación: iniciar sesión, renovar y cerrar.

El contrato de tokens y por qué es así
--------------------------------------
Se devuelven **dos** tokens en el cuerpo de la respuesta:

- **Acceso**, de minutos. Es el que viaja en la cabecera `Authorization` de cada petición.
- **Renovación**, de días. Solo sirve para pedir un par nuevo, y **rota en cada uso**: el que se
  acaba de usar deja de valer. Si alguien presenta uno viejo, se cierran todas las sesiones de
  esa cuenta, porque significa que hay dos copias en circulación.

Se devuelven en el cuerpo y no en una cookie porque el panel es una aplicación de otro origen: una
cookie exigiría `SameSite=None`, que es la configuración con más superficie de ataque por
falsificación de petición. La contrapartida es que el cliente debe guardar el token de renovación
con cuidado; la recomendación es en memoria y no en `localStorage`.

Sobre el `DELETE` con cuerpo
----------------------------
Cerrar la sesión al cerrar la ventana necesita enviar el token de renovación, porque el de acceso ya
puede haber caducado. Eso obliga a un `POST` en lugar de un `DELETE`, porque el navegador no envía
cuerpo en los avisos de descarga con `DELETE`. Es una concesión al navegador, no al diseño.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Body, Header, status
from pydantic import BaseModel, Field

from contratacion.aplicacion.casos_uso.autenticar import (
    cerrar_sesion,
    iniciar_sesion,
    renovar_sesion,
)
from contratacion.aplicacion.casos_uso.gestionar_usuarios import cambiar_mi_contrasena
from contratacion.aplicacion.puertos.seguridad import TipoToken
from contratacion.dominio.errores import SinPermiso
from contratacion.dominio.serializacion import cuerpo_json
from contratacion.dominio.sesiones import MotivoRevocacion
from contratacion.infraestructura.adaptadores.entrada.http.dependencias import (
    ActorDep,
    AjustesDep,
    AuditoriaDep,
    CierreSesionesDep,
    ContrasenasDep,
    CuentasDep,
    SesionesDep,
)
from contratacion.infraestructura.adaptadores.salida.seguridad.fabrica import (
    huella_de_descarte,
    obtener_contrasenas,
    obtener_tokens,
)

router = APIRouter(prefix="/v1/auth", tags=["Autenticación"])

SEGUNDOS_POR_MINUTO = 60
SEGUNDOS_POR_DIA = 86_400


class Credenciales(BaseModel):
    """Cuerpo del inicio de sesión."""

    email: str = Field(min_length=3, max_length=320, examples=["ana@constructora.ec"])
    contrasena: str = Field(min_length=1, max_length=200)


class Renovacion(BaseModel):
    """Cuerpo de la renovación."""

    token_renovacion: str = Field(min_length=1)


class CierreDeSesion(BaseModel):
    """Cuerpo del cierre. El token es opcional porque también vale el de acceso de la cabecera."""

    token_renovacion: str | None = None
    motivo: MotivoRevocacion = MotivoRevocacion.LOGOUT


# Valor por defecto del cuerpo del cierre, creado una sola vez.
#
# Se declara como constante y no como `CierreDeSesion()` en la firma porque evaluar una llamada en
# los valores por defecto de un parámetro los comparte entre invocaciones y esconde efectos raros.
CIERRE_PREDETERMINADO = CierreDeSesion()


@router.post("/sesion", summary="Iniciar sesión")
async def iniciar(
    cuerpo: Credenciales,
    cuentas: CuentasDep,
    sesiones: SesionesDep,
    ajustes: AjustesDep,
    user_agent: Annotated[str | None, Header()] = None,
    x_forwarded_for: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    """Valida las credenciales y abre una sesión.

    Si la cuenta ya tenía dos sesiones abiertas, la de último uso más lejano se cierra, y la
    respuesta lo indica en `sesiones_expulsadas` para que el panel pueda avisar de la otra.
    """
    resultado = await iniciar_sesion(
        cuerpo.email,
        cuerpo.contrasena,
        cuentas=cuentas,
        sesiones=sesiones,
        contrasenas=obtener_contrasenas(),
        tokens=obtener_tokens(),
        huella_descarte=huella_de_descarte(),
        max_sesiones=ajustes.max_sesiones_usuario,
        acceso_ttl_seg=ajustes.acceso_ttl_min * SEGUNDOS_POR_MINUTO,
        refresco_ttl_seg=ajustes.refresh_ttl_dias * SEGUNDOS_POR_DIA,
        dispositivo=user_agent,
        ip=x_forwarded_for,
        user_agent=user_agent,
    )
    return cuerpo_json(resultado.como_diccionario())


@router.post("/sesion/renovacion", summary="Renovar los tokens")
async def renovar(
    cuerpo: Renovacion,
    cuentas: CuentasDep,
    sesiones: SesionesDep,
    ajustes: AjustesDep,
) -> dict[str, Any]:
    """Emite un par de tokens nuevo y rota el de renovación."""
    resultado = await renovar_sesion(
        cuerpo.token_renovacion,
        cuentas=cuentas,
        sesiones=sesiones,
        tokens=obtener_tokens(),
        acceso_ttl_seg=ajustes.acceso_ttl_min * SEGUNDOS_POR_MINUTO,
        refresco_ttl_seg=ajustes.refresh_ttl_dias * SEGUNDOS_POR_DIA,
        gracia_seg=ajustes.refresh_gracia_seg,
    )
    return cuerpo_json(resultado.como_diccionario())


@router.post(
    "/sesion/cierre",
    status_code=status.HTTP_200_OK,
    summary="Cerrar la sesión",
)
async def cerrar(
    cuentas: CuentasDep,
    sesiones: SesionesDep,
    cuerpo: Annotated[CierreDeSesion, Body()] = CIERRE_PREDETERMINADO,
    autorizacion: Annotated[str | None, Header(alias="Authorization")] = None,
) -> dict[str, Any]:
    """Cierra la sesión. Acepta el token de renovación o, si no, el de acceso de la cabecera.

    Es lo que usa el aviso de cierre de ventana del navegador, que puede llegar cuando el token de
    acceso ya expiró y solo queda el de renovación.
    """
    tokens = obtener_tokens()
    if cuerpo.token_renovacion:
        claims = tokens.verificar(cuerpo.token_renovacion, TipoToken.REFRESCO)
    elif autorizacion and autorizacion.lower().startswith("bearer "):
        claims = tokens.verificar(autorizacion.split(" ", 1)[1].strip(), TipoToken.ACCESO)
    else:
        raise SinPermiso("No se recibió ningún token con el que cerrar la sesión.")

    cerradas = await cerrar_sesion(
        claims,
        sesiones=sesiones,
        cuentas=cuentas,
        motivo=cuerpo.motivo,
    )
    return {"cerrada": True, "sesiones_cerradas": cerradas}


@router.get("/sesion", summary="Datos de la sesión actual")
async def sesion_actual(actor: ActorDep, ajustes: AjustesDep) -> dict[str, Any]:
    """Identidad y ámbito del token con el que se llama.

    Sirve para que el panel sepa quién es sin descodificar el token por su cuenta: descodificarlo en
    el cliente sería tratar su contenido como fiable, y no lo es hasta que el servidor lo verifica.
    """
    return {
        "usuario_id": str(actor.usuario_id),
        "negocio_id": str(actor.negocio_id),
        "rol": actor.rol,
        "acceso_ttl_seg": ajustes.acceso_ttl_min * SEGUNDOS_POR_MINUTO,
        "max_sesiones": ajustes.max_sesiones_usuario,
    }


class CambioDeContrasenaPropia(BaseModel):
    """Cuerpo del cambio de contraseña propio.

    `sesion_actual` es opcional y sirve para no cerrar la sesión desde la que se hace el cambio. Se
    acepta del cliente porque el cliente ya conoce ese identificador —viaja en su propio token— y
    porque la operación está acotada a las sesiones del propio usuario: como mucho, alguien consigue
    conservar viva una sesión que ya tenía. Si no se envía, se cierran todas y habrá que volver a
    entrar.
    """

    contrasena_actual: str = Field(min_length=1, max_length=200)
    contrasena_nueva: str = Field(min_length=1, max_length=200)
    sesion_actual: UUID | None = None


@router.post("/contrasena", summary="Cambiar la contraseña propia")
async def cambiar_contrasena(
    cuerpo: CambioDeContrasenaPropia,
    actor: ActorDep,
    cuentas: CuentasDep,
    sesiones: CierreSesionesDep,
    contrasenas: ContrasenasDep,
    auditoria: AuditoriaDep,
) -> dict[str, Any]:
    """Cambia la contraseña de quien llama, comprobando antes la actual.

    Pedir la contraseña actual es lo que impide que alguien con una sesión abierta y sin conocer la
    clave se apropie de la cuenta: sin esta comprobación, un equipo desatendido un minuto bastaría
    para quedarse con ella de forma permanente.

    Se cierran las demás sesiones y **se conserva la que hace el cambio**, si se identifica. No se
    exige ser administrador: es la operación que permite a cualquier persona cambiar la contraseña
    que le entregaron, y sin ella la contraseña inicial sería para siempre.

    Tampoco se exige haber aceptado los términos, y es deliberado. La puerta de consentimiento
    bloquea lo que trata datos del negocio; cambiar una contraseña no trata ninguno. Ponerla aquí
    dejaba a una persona recién dada de alta atrapada en un círculo: no puede cambiar la contraseña
    que le entregaron hasta aceptar, y aceptar es algo que decide hacer después de entrar. Lo mismo
    vale para poder salir del sistema, que tampoco lleva la puerta.
    """
    resultado = await cambiar_mi_contrasena(
        actor,
        contrasena_actual=cuerpo.contrasena_actual,
        contrasena_nueva=cuerpo.contrasena_nueva,
        cuentas=cuentas,
        sesiones=sesiones,
        contrasenas=contrasenas,
        auditoria=auditoria,
        sesion_actual=cuerpo.sesion_actual,
    )
    return cuerpo_json(resultado.como_diccionario())
