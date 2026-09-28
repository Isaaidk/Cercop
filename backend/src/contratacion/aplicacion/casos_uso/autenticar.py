"""Casos de uso de autenticación: iniciar sesión, renovar y cerrar.

Las decisiones que definen este módulo
--------------------------------------
**El mismo mensaje para todos los fallos.** «El correo o la contraseña no son correctos» es lo que
se responde cuando la cuenta no existe, cuando la contraseña está mal y cuando la cuenta no puede
entrar. Distinguirlos convertiría el inicio de sesión en un buscador de usuarios. Y para que el
mensaje no se delate por el tiempo, cuando la cuenta no existe se comprueba igualmente la contraseña
contra una huella de descarte.

**El orden sí importa cuando la contraseña es correcta.** Solo entonces se dice que la cuenta está
bloqueada o desactivada, porque quien ha demostrado conocer la contraseña ya sabía que la cuenta
existe y merece un mensaje útil en lugar de uno genérico.

**El negocio sale del token, nunca de la petición.** Es la regla R-04, y aquí se ve por qué: si el
cliente pudiera elegir el negocio, podría pedir datos de otro.

**La rotación del token de renovación con detección de reutilización.** Cada renovación emite un
token nuevo y guarda su huella. Si llega uno que no coincide con la guardada, significa que alguien
tiene una copia antigua —se filtró, o se reutiliza desde otro sitio— y se cierran **todas** las
sesiones de esa cuenta. Es la única respuesta prudente: no se sabe quién es el legítimo, y quien
tiene las contraseñas puede volver a entrar.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from contratacion.aplicacion.puertos.cuentas import (
    Cuenta,
    RepositorioCuentas,
    RepositorioSesiones,
)
from contratacion.aplicacion.puertos.seguridad import (
    Claims,
    ServicioContrasenas,
    ServicioTokens,
    TipoToken,
)
from contratacion.dominio.credenciales import (
    esta_bloqueada,
    intentos_tras_fallo,
    siguiente_bloqueo,
)
from contratacion.dominio.errores import SinPermiso
from contratacion.dominio.sesiones import MotivoRevocacion, sesiones_a_expulsar

registro = logging.getLogger(__name__)

MENSAJE_CREDENCIALES = "El correo o la contraseña no son correctos."
MENSAJE_SIN_SESION = "La sesión ya no está activa. Vuelve a iniciar sesión."
MENSAJE_SIN_ENTRADA = "Esta cuenta no tiene acceso al sistema. Contacta con el administrador."


@dataclass(frozen=True, slots=True)
class SesionIniciada:
    """Resultado de un inicio o una renovación de sesión."""

    usuario_id: UUID
    negocio_id: UUID
    rol: str
    sesion_id: UUID
    nombre: str
    email: str
    acceso: str
    refresco: str
    acceso_expira_en: datetime
    refresco_expira_en: datetime
    debe_aceptar_politica_version: int | None
    sesiones_abiertas: int
    sesiones_expulsadas: int

    @property
    def debe_aceptar_terminos(self) -> bool:
        """¿Hay que mostrar la pantalla de aceptación antes de dejar pasar?

        Lo decide el servidor: el frontend solo obedece. Si lo decidiera el cliente, bastaría con
        editar la interfaz para saltarse la aceptación de los términos.
        """
        return self.debe_aceptar_politica_version is not None

    def como_diccionario(self) -> dict[str, Any]:
        return {
            "usuario_id": str(self.usuario_id),
            "negocio_id": str(self.negocio_id),
            "rol": self.rol,
            "sesion_id": str(self.sesion_id),
            "nombre": self.nombre,
            "email": self.email,
            "token_acceso": self.acceso,
            "token_renovacion": self.refresco,
            "acceso_expira_en": self.acceso_expira_en.isoformat(),
            "renovacion_expira_en": self.refresco_expira_en.isoformat(),
            "debe_aceptar_terminos": self.debe_aceptar_terminos,
            # El número de versión lo usa el frontend solo para pedir el texto correcto. La decisión
            # de si hace falta aceptar ya está tomada arriba.
            "politica_version": self.debe_aceptar_politica_version,
            "sesiones_abiertas": self.sesiones_abiertas,
            "sesiones_expulsadas": self.sesiones_expulsadas,
        }


def _claims(cuenta: Cuenta, sesion_id: UUID, tipo: TipoToken, expira_en: datetime) -> Claims:
    return Claims(
        usuario_id=cuenta.usuario_id,
        negocio_id=cuenta.negocio_id,
        rol=cuenta.rol,
        sesion_id=sesion_id,
        tipo=tipo,
        expira_en=expira_en,
    )


async def iniciar_sesion(
    email: str,
    contrasena: str,
    *,
    cuentas: RepositorioCuentas,
    sesiones: RepositorioSesiones,
    contrasenas: ServicioContrasenas,
    tokens: ServicioTokens,
    huella_descarte: str,
    max_sesiones: int,
    acceso_ttl_seg: int,
    refresco_ttl_seg: int,
    dispositivo: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    momento: datetime | None = None,
) -> SesionIniciada:
    """Valida las credenciales y abre una sesión, expulsando la más antigua si hace falta."""
    instante = momento or datetime.now(UTC)
    correo = (email or "").strip()

    referencia = await cuentas.resolver(correo)
    if referencia is None:
        # Se comprueba contra una huella de descarte para que el tiempo de respuesta no delate si
        # el correo existe: 2 ms sería «no existe» y 60 ms «existe y la contraseña está mal», y eso
        # convierte el inicio de sesión en un comprobador de correos registrados.
        contrasenas.verificar(huella_descarte, contrasena)
        await _auditar_fallo(cuentas, None, correo, ip, user_agent)
        raise SinPermiso(MENSAJE_CREDENCIALES)

    usuario_id, negocio_id = referencia
    cuenta = await cuentas.obtener(negocio_id=negocio_id, usuario_id=usuario_id)
    if cuenta is None:
        # La cuenta se resolvió pero no se puede leer: pasa cuando la política de RLS y la función
        # de resolución no coinciden. Es un problema de configuración, y conviene que se vea.
        registro.error("La cuenta %s se resolvió pero no se pudo leer", usuario_id)
        raise SinPermiso(MENSAJE_CREDENCIALES)

    if not contrasenas.verificar(cuenta.hash_password, contrasena):
        await _registrar_fallo(cuentas, cuenta, instante)
        await _auditar_fallo(cuentas, cuenta, correo, ip, user_agent)
        raise SinPermiso(MENSAJE_CREDENCIALES)

    # A partir de aquí la contraseña es correcta, así que se puede ser concreto sin revelar nada.
    if esta_bloqueada(cuenta.bloqueado_hasta, instante):
        restante = cuenta.bloqueado_hasta
        assert restante is not None  # lo garantiza `esta_bloqueada`
        raise SinPermiso(
            "La cuenta está bloqueada temporalmente por intentos fallidos. "
            f"Vuelve a intentarlo después de las {restante.astimezone().strftime('%H:%M')}."
        )

    if not cuenta.puede_iniciar_sesion:
        registro.warning("Intento de acceso de una cuenta no habilitada: %s", cuenta.usuario_id)
        await _auditar_fallo(cuentas, cuenta, correo, ip, user_agent)
        raise SinPermiso(MENSAJE_SIN_ENTRADA)

    if contrasenas.necesita_rehash(cuenta.hash_password):
        await cuentas.actualizar_huella(
            negocio_id=negocio_id,
            usuario_id=usuario_id,
            huella=contrasenas.hash(contrasena),
        )
        registro.info("Huella de contraseña actualizada a los parámetros vigentes")

    await cuentas.registrar_acceso_correcto(
        negocio_id=negocio_id, usuario_id=usuario_id, momento=instante
    )

    vigentes = await sesiones.vigentes(
        negocio_id=negocio_id, usuario_id=usuario_id, momento=instante
    )
    a_expulsar = sesiones_a_expulsar(vigentes, max_sesiones)
    expulsadas = 0
    if a_expulsar:
        expulsadas = await sesiones.revocar_varias(
            negocio_id=negocio_id,
            sesion_ids=a_expulsar,
            motivo=MotivoRevocacion.EVICCION,
            momento=instante,
        )
        registro.info(
            "Se expulsaron %s sesiones de %s por superar el máximo de %s",
            expulsadas,
            usuario_id,
            max_sesiones,
        )

    sesion_id = uuid4()
    acceso_expira = instante + timedelta(seconds=acceso_ttl_seg)
    refresco_expira = instante + timedelta(seconds=refresco_ttl_seg)

    refresco = tokens.emitir(
        _claims(cuenta, sesion_id, TipoToken.REFRESCO, refresco_expira), refresco_ttl_seg
    )
    await sesiones.crear(
        sesion_id=sesion_id,
        negocio_id=negocio_id,
        usuario_id=usuario_id,
        refresh_hash=tokens.huella(refresco),
        expira_en=refresco_expira,
        momento=instante,
        dispositivo=dispositivo,
        ip=ip,
        user_agent=user_agent,
    )
    acceso = tokens.emitir(
        _claims(cuenta, sesion_id, TipoToken.ACCESO, acceso_expira), acceso_ttl_seg
    )

    await cuentas.auditar(
        accion="sesion_iniciada",
        negocio_id=negocio_id,
        usuario_id=usuario_id,
        entidad="sesion",
        entidad_id=str(sesion_id),
        resultado="ok",
        ip=ip,
        user_agent=user_agent,
        detalle={"sesiones_expulsadas": expulsadas},
    )

    return SesionIniciada(
        usuario_id=usuario_id,
        negocio_id=negocio_id,
        rol=cuenta.rol,
        sesion_id=sesion_id,
        nombre=cuenta.nombre,
        email=cuenta.email,
        acceso=acceso,
        refresco=refresco,
        acceso_expira_en=acceso_expira,
        refresco_expira_en=refresco_expira,
        debe_aceptar_politica_version=cuenta.debe_aceptar_politica_version,
        sesiones_abiertas=len(vigentes) - expulsadas + 1,
        sesiones_expulsadas=expulsadas,
    )


async def renovar_sesion(
    token_refresco: str,
    *,
    cuentas: RepositorioCuentas,
    sesiones: RepositorioSesiones,
    tokens: ServicioTokens,
    acceso_ttl_seg: int,
    refresco_ttl_seg: int,
    momento: datetime | None = None,
) -> SesionIniciada:
    """Emite un par de tokens nuevo a partir de uno de renovación.

    Detecta la reutilización: si el token presentado no coincide con la huella guardada, se cierra
    **todo** lo abierto de esa cuenta. No se intenta averiguar cuál de las dos copias es la
    legítima, porque no hay forma de saberlo y suponerlo mal deja dentro a quien robó el token.
    """
    instante = momento or datetime.now(UTC)
    claims = tokens.verificar(token_refresco, TipoToken.REFRESCO)

    guardada = await sesiones.por_id(negocio_id=claims.negocio_id, sesion_id=claims.sesion_id)
    if guardada is None or not guardada.sesion.vigente(instante):
        raise SinPermiso(MENSAJE_SIN_SESION)

    if tokens.huella(token_refresco) != guardada.refresh_hash:
        cerradas = await sesiones.revocar_todas(
            negocio_id=claims.negocio_id,
            usuario_id=claims.usuario_id,
            motivo=MotivoRevocacion.REUSO_DETECTADO,
            momento=instante,
        )
        registro.error(
            "Reutilización de token de renovación en %s: se cerraron %s sesiones",
            claims.usuario_id,
            cerradas,
        )
        await cuentas.auditar(
            accion="reuso_de_token_detectado",
            negocio_id=claims.negocio_id,
            usuario_id=claims.usuario_id,
            entidad="sesion",
            entidad_id=str(claims.sesion_id),
            resultado="sesiones_revocadas",
            detalle={"sesiones_cerradas": cerradas},
        )
        raise SinPermiso(MENSAJE_SIN_SESION)

    cuenta = await cuentas.obtener(negocio_id=claims.negocio_id, usuario_id=claims.usuario_id)
    if cuenta is None or not cuenta.puede_iniciar_sesion:
        # Renovar a alguien a quien acaban de desactivar dejaría la puerta abierta durante toda la
        # vigencia del token de renovación, que es de días.
        await sesiones.revocar_todas(
            negocio_id=claims.negocio_id,
            usuario_id=claims.usuario_id,
            motivo=MotivoRevocacion.ADMIN,
            momento=instante,
        )
        raise SinPermiso(MENSAJE_SIN_ENTRADA)

    acceso_expira = instante + timedelta(seconds=acceso_ttl_seg)
    refresco_expira = instante + timedelta(seconds=refresco_ttl_seg)

    refresco = tokens.emitir(
        _claims(cuenta, claims.sesion_id, TipoToken.REFRESCO, refresco_expira), refresco_ttl_seg
    )
    await sesiones.rotar(
        negocio_id=claims.negocio_id,
        sesion_id=claims.sesion_id,
        refresh_hash=tokens.huella(refresco),
        ultimo_uso_en=instante,
    )
    acceso = tokens.emitir(
        _claims(cuenta, claims.sesion_id, TipoToken.ACCESO, acceso_expira), acceso_ttl_seg
    )

    return SesionIniciada(
        usuario_id=cuenta.usuario_id,
        negocio_id=cuenta.negocio_id,
        rol=cuenta.rol,
        sesion_id=claims.sesion_id,
        nombre=cuenta.nombre,
        email=cuenta.email,
        acceso=acceso,
        refresco=refresco,
        acceso_expira_en=acceso_expira,
        refresco_expira_en=refresco_expira,
        debe_aceptar_politica_version=cuenta.debe_aceptar_politica_version,
        sesiones_abiertas=1,
        sesiones_expulsadas=0,
    )


async def cerrar_sesion(
    claims: Claims,
    *,
    sesiones: RepositorioSesiones,
    cuentas: RepositorioCuentas,
    motivo: MotivoRevocacion = MotivoRevocacion.LOGOUT,
    momento: datetime | None = None,
) -> int:
    """Cierra la sesión del token presentado.

    Recibe las declaraciones ya verificadas para que el enrutador pueda aceptar tanto un token de
    acceso —el caso normal— como uno de renovación.

    Se cierra **la sesión del token**, no todas las de la cuenta. La diferencia importa cuando una
    cuenta se comparte, que es justo el caso para el que existe el tope de sesiones: si cerrar
    sesión en un equipo echara también al otro, el que se va estaría echando a quien se queda.
    """
    instante = momento or datetime.now(UTC)
    cerradas = await sesiones.revocar_varias(
        negocio_id=claims.negocio_id,
        sesion_ids=[claims.sesion_id],
        motivo=motivo,
        momento=instante,
    )
    await cuentas.auditar(
        accion="sesion_cerrada",
        negocio_id=claims.negocio_id,
        usuario_id=claims.usuario_id,
        entidad="sesion",
        entidad_id=str(claims.sesion_id),
        resultado=str(motivo),
        detalle={"sesiones_cerradas": cerradas},
    )
    return cerradas


async def _registrar_fallo(cuentas: RepositorioCuentas, cuenta: Cuenta, momento: datetime) -> None:
    intentos = intentos_tras_fallo(cuenta.intentos_fallidos)
    await cuentas.registrar_fallo(
        negocio_id=cuenta.negocio_id,
        usuario_id=cuenta.usuario_id,
        intentos=intentos,
        bloqueado_hasta=siguiente_bloqueo(intentos, momento),
    )


async def _auditar_fallo(
    cuentas: RepositorioCuentas,
    cuenta: Cuenta | None,
    correo: str,
    ip: str | None,
    user_agent: str | None,
) -> None:
    """Anota el intento fallido si se puede.

    Con un correo desconocido no hay negocio del que colgar la línea, y la política de la tabla de
    auditoría impide escribir sin él. En ese caso se deja constancia en el registro de la
    aplicación: es preferible a no dejar rastro, y no se puede hacer mejor sin abrir la auditoría a
    filas sin negocio.
    """
    if cuenta is None:
        registro.warning("Intento de acceso con un correo sin cuenta: %s", _correo_velado(correo))
        return
    await cuentas.auditar(
        accion="intento_de_acceso_fallido",
        negocio_id=cuenta.negocio_id,
        usuario_id=cuenta.usuario_id,
        entidad="usuario",
        entidad_id=str(cuenta.usuario_id),
        resultado="credenciales_incorrectas",
        ip=ip,
        user_agent=user_agent,
    )


def _correo_velado(correo: str) -> str:
    """Versión parcial del correo, para correlacionar sin guardarlo entero en los registros."""
    if "@" not in correo:
        return "(sin formato de correo)"
    usuario, dominio = correo.split("@", 1)
    visible = usuario[:2] if len(usuario) > 2 else ""
    return f"{visible}***@{dominio}"
