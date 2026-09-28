"""Errores del dominio.

Un solo tipo raíz permite que las capas externas traduzcan cualquier violación de una regla de
negocio sin conocer los detalles: el adaptador HTTP la convierte en 4xx, el worker la registra.

Se evita `ValueError` porque es demasiado genérico: un `ValueError` puede venir de cualquier
biblioteca y confundirse con una regla de negocio incumplida.
"""

from __future__ import annotations


class ErrorDominio(Exception):
    """Raíz de todos los errores que representan una regla de negocio incumplida.

    Cada error lleva un `codigo` estable, aparte del mensaje. El mensaje está escrito para que lo
    lea una persona y puede reescribirse en cualquier momento; el código lo lee el programa y no
    cambia. Sin él, el cliente tendría que adivinar qué ha pasado mirando el texto —y hay casos en
    los que dos errores distintos comparten el mismo código HTTP—:

    - «no tienes permiso para esto» y «tienes que aceptar los términos» son los dos un 403, y la
      interfaz debe hacer cosas completamente distintas con cada uno: explicar el motivo, o abrir la
      pantalla de aceptación.
    """

    codigo = "error"


class DatoInvalido(ErrorDominio):
    """El dato recibido no cumple una regla del dominio.

    Corresponde a una petición mal formada: el cliente puede corregirla y reintentar.
    """

    codigo = "dato_invalido"


class EstadoInvalido(ErrorDominio):
    """La operación no es válida para el estado actual del recurso."""

    codigo = "estado_invalido"


class SinPermiso(ErrorDominio):
    """El actor no tiene autorización para esta operación.

    Es una regla de negocio y no un detalle de HTTP: el mismo caso de uso debe negarse igual desde
    la API, desde el worker o desde una tarea programada.
    """

    codigo = "sin_permiso"


class NoEncontrado(ErrorDominio):
    """El recurso pedido no existe o no está dentro del ámbito del actor.

    Los dos casos comparten tipo a propósito: distinguir «no existe» de «existe pero no es tuyo»
    permitiría a un cliente averiguar qué identificadores son reales en otros negocios.
    """

    codigo = "no_encontrado"


class ConsentimientoPendiente(ErrorDominio):
    """Hay que aceptar los términos antes de poder usar el aplicativo.

    Es un error de dominio y no una comprobación del enrutador porque la regla es del negocio: el
    mismo caso de uso debe negarse igual desde cualquier entrada, no solo desde HTTP.

    Se distingue de `SinPermiso` —que también sería un 403— porque la respuesta a esta no es «pide
    permiso a tu administrador», sino «acepta los términos». Confundirlas dejaría al usuario leyendo
    un mensaje que le manda a pedir algo que ya tiene.
    """

    codigo = "consentimiento_pendiente"


class SesionRevocada(ErrorDominio):
    """La sesión existió y ya no vale: la cerraron desde otro sitio o la expulsó otro acceso.

    Se distingue de «falta el token» a propósito, y esa distinción es el motivo de que exista. Quien
    se queda fuera porque alguien entró con sus mismas credenciales necesita saber **por qué**:
    «vuelve a entrar» parece un fallo del sistema cuando la causa real es que hay otra persona
    usando su cuenta, que es justo lo que tiene que averiguar. El `motivo` viaja aparte del mensaje
    para que la interfaz pueda decidir sin leer texto: `eviccion` se cuenta de una manera y
    `logout` de otra.
    """

    codigo = "sesion_revocada"

    def __init__(self, mensaje: str, *, motivo: str | None = None) -> None:
        super().__init__(mensaje)
        self.motivo = motivo


# El aviso que recibe una empresa suspendida, y **lo único** que recibe: ni panel, ni tabla, ni
# gráficas. Vive aquí, junto al error que lo lanza, porque son la misma cosa: no es un mensaje que
# alguien escriba al suspender, es lo que significa estar suspendido.
MENSAJE_SUSPENSION = (
    "Tu cuenta fue suspendida. Contáctate con el administrador: isaacpuga661@gmail.com"
)


class EmpresaSuspendida(ErrorDominio):
    """La empresa de quien llama tiene el acceso cortado por decisión de la plataforma.

    Se comprueba en la puerta común y no en cada endpoint: si hubiera que acordarse de añadirlo en
    cada sitio, el día que se añadiera uno nuevo la empresa suspendida volvería a leer datos por esa
    puerta nueva. Y se distingue de `SinPermiso` porque la respuesta que espera el usuario no es
    «pide permiso», sino «habla con el administrador», que es a quien le pueden levantar la
    suspensión.
    """

    codigo = "empresa_suspendida"

    def __init__(self, mensaje: str | None = None) -> None:
        super().__init__(mensaje or MENSAJE_SUSPENSION)
