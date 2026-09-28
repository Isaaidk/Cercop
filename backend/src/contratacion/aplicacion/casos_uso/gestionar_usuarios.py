"""Casos de uso: crear, dar de baja, reactivar, borrar y cambiar contraseñas.

Aquí está la administración de cuentas de una empresa. Cinco reglas gobiernan todo el módulo, y las
cinco existen porque su ausencia produce un estado del que no se puede salir desde la interfaz.

**Quien administra no puede administrarse a sí mismo hacia afuera.** No puede darse de baja ni
borrarse: los dos casos dejarían la sesión abierta apuntando a una cuenta que ya no puede entrar, y
nadie entendería por qué el panel dejó de funcionar.

**No se puede dejar la empresa sin administradores.** Dar de baja o borrar al último que queda
convierte la empresa en algo que solo se arregla con acceso directo a la base de datos. La
comprobación se hace **antes** de tocar nada y cuenta a los administradores activos.

**Nadie puede crear un rol que no le corresponde asignar.** Un administrador de empresa puede crear
otro administrador, un consultor o un lector; `super_admin` no está en esa lista. Si lo estuviera,
cualquier administrador podría fabricarse una cuenta de plataforma en un formulario.

**El límite de usuarios del plan se comprueba al crear, no al entrar.** Avisar cuando ya no
caben más obliga a la persona a descubrir el problema después de haber decidido a quién
quería dar acceso.

**Cambiar una contraseña cierra las sesiones.** Las ajenas, todas; las propias, todas menos la
actual. Sin esto, un cambio de contraseña no servía para nada frente al caso que lo motiva
—una sesión robada o un portátil perdido—: quien tuviera una sesión abierta seguiría dentro.

Lo que estas reglas **no** pueden cerrar, y conviene decirlo
----------------------------------------------------------
El token de acceso es un JWT que se verifica sin consultar la base, y dura minutos. Al dar de
baja una cuenta se revocan sus sesiones, de modo que no puede renovar; pero el token que ya
tenía en la mano sigue valiendo hasta que caduque. La ventana está acotada por el tiempo de
vida del token, que es el precio de no consultar la base en cada petición. Está aquí escrito
para que nadie crea que la baja es instantánea en el sentido literal.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.casos_uso.consentimiento import marcar_lo_obligatorio_pendiente
from contratacion.aplicacion.puertos.cuentas import RepositorioCuentas
from contratacion.aplicacion.puertos.negocios import RepositorioNegocios
from contratacion.aplicacion.puertos.politicas import (
    RepositorioConsentimientos,
    RepositorioPoliticas,
)
from contratacion.aplicacion.puertos.seguridad import ServicioContrasenas
from contratacion.aplicacion.puertos.usuarios import (
    CierreDeSesiones,
    FichaUsuario,
    NuevaCuenta,
    RegistroAuditoria,
    RepositorioUsuarios,
)
from contratacion.dominio.credenciales import validar_contrasena
from contratacion.dominio.errores import DatoInvalido, NoEncontrado, SinPermiso
from contratacion.dominio.negocios import limpiar_texto, validar_correo
from contratacion.dominio.roles import (
    DESCRIPCION_ROL,
    ETIQUETAS_ROL,
    Rol,
    catalogo_para_panel,
    es_administrativo,
    puede_asignar,
    rol_desde_codigo,
)
from contratacion.dominio.sesiones import MotivoRevocacion

registro = logging.getLogger(__name__)

MENSAJE_LIMITE = (
    "La empresa alcanzó el número de usuarios de su plan. Da de baja a alguien antes de crear "
    "otra cuenta, o pide una ampliación."
)
MENSAJE_ULTIMO_ADMIN = (
    "No se puede dejar la empresa sin administradores: nadie podría volver a gestionar las "
    "cuentas desde el panel."
)
MENSAJE_A_SI_MISMO = (
    "No puedes darte de baja ni borrar tu propia cuenta. Si quieres dejar de usar el sistema, "
    "pide a otro administrador que lo haga."
)

ESTADO_ACTIVO = "activo"
ESTADO_INACTIVO = "inactivo"


@dataclass(frozen=True, slots=True)
class ResultadoCuenta:
    """Confirmación de una operación sobre una cuenta."""

    usuario: FichaUsuario
    sesiones_cerradas: int = 0
    avisos: tuple[str, ...] = ()

    def como_diccionario(self) -> dict[str, Any]:
        return {
            "usuario": self.usuario.como_diccionario(),
            "sesiones_cerradas": self.sesiones_cerradas,
            "avisos": list(self.avisos),
        }


@dataclass(frozen=True, slots=True)
class ResumenCuentas:
    """Listado de cuentas con el margen que queda en el plan."""

    usuarios: tuple[FichaUsuario, ...]
    limite_usuarios: int
    usuarios_activos: int
    administradores_activos: int
    plazas_libres: int

    def como_diccionario(self) -> dict[str, Any]:
        return {
            "usuarios": [ficha.como_diccionario() for ficha in self.usuarios],
            "limite_usuarios": self.limite_usuarios,
            "usuarios_activos": self.usuarios_activos,
            "administradores_activos": self.administradores_activos,
            "plazas_libres": self.plazas_libres,
            "roles": catalogo_para_panel(),
        }


def _etiqueta_asignable(rol: Rol) -> str:
    """Nombre del rol para el mensaje de error."""
    return ETIQUETAS_ROL.get(rol, str(rol))


def _lista_asignables() -> str:
    return ", ".join(ETIQUETAS_ROL[rol] for rol in (Rol.ADMIN_NEGOCIO, Rol.CONSULTOR, Rol.LECTOR))


def _exigir_gestion(actor: Actor) -> None:
    """Comprueba que el actor puede administrar cuentas, con un mensaje que orienta."""
    if not es_administrativo(actor.rol):
        raise SinPermiso(
            f"El rol «{actor.rol}» no puede gestionar usuarios. Solo pueden hacerlo el "
            "administrador de la empresa y el superadministrador."
        )


async def _ficha_o_fallo(
    usuario_id: UUID, *, actor: Actor, usuarios: RepositorioUsuarios
) -> FichaUsuario:
    """Lee la cuenta o falla con «no encontrada».

    El mensaje es el mismo para «no existe» y para «es de otra empresa», y no es un descuido:
    distinguirlos permitiría averiguar qué identificadores son reales en negocios ajenos. La
    consulta ya está acotada por RLS, así que la de otra empresa simplemente no aparece.
    """
    ficha = await usuarios.obtener(negocio_id=actor.negocio_id, usuario_id=usuario_id)
    if ficha is None:
        raise NoEncontrado("Esa cuenta no existe en esta empresa.")
    return ficha


def _exigir_no_es_uno_mismo(actor: Actor, usuario_id: UUID, accion: str) -> None:
    if actor.usuario_id == usuario_id:
        raise DatoInvalido(f"{MENSAJE_A_SI_MISMO} ({accion})")


def _exigir_queda_otro_admin(*, cuantos: int) -> None:
    """Comprueba que después de la operación seguirá habiendo un administrador.

    El cálculo es «cuántos administradores activos hay menos los que esta operación quita». Se hace
    sobre el número que devuelve la consulta y no sobre una lista, porque una lista puede venir
    truncada por un límite de filas y entonces el sistema creería que no queda ninguno: bloquearía
    una operación legítima con el argumento contrario al que corresponde.
    """
    if cuantos <= 1:
        raise DatoInvalido(MENSAJE_ULTIMO_ADMIN)


# --------------------------------------------------------------------------- #
# Consulta
# --------------------------------------------------------------------------- #


async def listar_cuentas(
    actor: Actor,
    *,
    usuarios: RepositorioUsuarios,
    negocios: RepositorioNegocios,
    incluir_inactivos: bool = True,
) -> ResumenCuentas:
    """Las cuentas de la empresa y el margen del plan, en una sola respuesta.

    Se devuelven juntas a propósito: el panel necesita saber cuántas plazas quedan para decidir si
    enseña el botón de crear, y dos peticiones seguidas podrían dar números de instantes distintos y
    un panel que se contradice consigo mismo.
    """
    _exigir_gestion(actor)

    fichas = await usuarios.listar(negocio_id=actor.negocio_id, incluir_inactivos=incluir_inactivos)
    uso = await negocios.resumen_uso(negocio_id=actor.negocio_id)
    return ResumenCuentas(
        usuarios=tuple(fichas),
        limite_usuarios=int(uso["limite_usuarios"]),
        usuarios_activos=int(uso["usuarios_activos"]),
        administradores_activos=int(uso["administradores_activos"]),
        plazas_libres=int(uso["plazas_libres"]),
    )


# --------------------------------------------------------------------------- #
# Alta
# --------------------------------------------------------------------------- #


async def crear_cuenta(
    actor: Actor,
    *,
    email: str | None,
    nombre: str | None,
    rol_codigo: str,
    contrasena: str | None,
    usuarios: RepositorioUsuarios,
    negocios: RepositorioNegocios,
    contrasenas: ServicioContrasenas,
    politicas: RepositorioPoliticas,
    consentimientos: RepositorioConsentimientos,
    auditoria: RegistroAuditoria,
    momento: datetime | None = None,
) -> ResultadoCuenta:
    """Crea una cuenta en la empresa del actor, con la contraseña que decide quien la crea.

    Que la contraseña la elija el administrador y no se genere automáticamente es una decisión de
    producto, no técnica: es lo que permite entregarla en mano o por el canal que la empresa ya usa,
    sin montar un envío de correo —que además revelaría que la cuenta existe a quien no debe—.
    La persona puede cambiarla después, y se le debe decir.
    """
    _exigir_gestion(actor)
    rol = rol_desde_codigo(rol_codigo)
    if not puede_asignar(rol):
        raise SinPermiso(
            f"No puedes crear una cuenta con el rol «{_etiqueta_asignable(rol)}». "
            f"Solo puedes asignar: {_lista_asignables()}."
        )

    correo = validar_correo(email, obligatorio=True)
    texto_contrasena = contrasena or ""
    validar_contrasena(texto_contrasena, email=correo)

    uso = await negocios.resumen_uso(negocio_id=actor.negocio_id)
    if int(uso["usuarios_activos"]) >= int(uso["limite_usuarios"]):
        raise DatoInvalido(f"{MENSAJE_LIMITE} El plan permite {uso['limite_usuarios']} usuarios.")

    instante = momento or datetime.now(UTC)

    # El repositorio traduce el choque con el índice único de correo a un `DatoInvalido` con un
    # mensaje entendible. No se comprueba antes: entre la comprobación y la inserción cabe otra alta
    # con el mismo correo, y entonces la comprobación habría dado una falsa tranquilidad.
    usuario_id = uuid4()
    await usuarios.crear(
        NuevaCuenta(
            usuario_id=usuario_id,
            negocio_id=actor.negocio_id,
            email=correo,
            nombre=limpiar_texto(nombre) or correo,
            rol=rol,
            huella=contrasenas.hash(texto_contrasena),
            momento=instante,
        )
    )

    await auditoria.auditar(
        accion="alta_usuario",
        negocio_id=actor.negocio_id,
        usuario_id=actor.usuario_id,
        entidad="usuario",
        entidad_id=str(usuario_id),
        resultado="ok",
        detalle={"email": correo, "rol": str(rol)},
    )

    # La cuenta nace debiendo aceptar los términos. La puerta de bloqueo lee el marcador de la
    # cuenta y no el catálogo de políticas, así que una cuenta sin marcador queda exenta sin que
    # nada lo delate. Ver `marcar_lo_obligatorio_pendiente`.
    await marcar_lo_obligatorio_pendiente(
        negocio_id=actor.negocio_id,
        usuario_id=usuario_id,
        politicas=politicas,
        consentimientos=consentimientos,
    )
    registro.info("Cuenta creada: negocio=%s usuario=%s rol=%s", actor.negocio_id, usuario_id, rol)

    ficha = await _ficha_o_fallo(usuario_id, actor=actor, usuarios=usuarios)
    return ResultadoCuenta(
        usuario=ficha,
        avisos=(
            "Comunica la contraseña a la persona por un canal privado y sugiérele que la cambie al "
            "entrar.",
            "Al entrar por primera vez tendrá que aceptar los términos y condiciones.",
        ),
    )


# --------------------------------------------------------------------------- #
# Baja y reactivación
# --------------------------------------------------------------------------- #


async def desactivar_cuenta(
    actor: Actor,
    *,
    usuario_id: UUID,
    usuarios: RepositorioUsuarios,
    sesiones: CierreDeSesiones,
    auditoria: RegistroAuditoria,
    momento: datetime | None = None,
) -> ResultadoCuenta:
    """Da de baja una cuenta: no puede entrar, sus sesiones se cierran y desaparece del listado.

    **No se borra nada.** La fila se queda, y con ella el registro de que esa persona aceptó los
    términos y condiciones. En un sistema que tiene que poder demostrar esa aceptación, borrar la
    fila es perder la prueba. Por eso esta es la operación recomendada y el borrado real es otra
    aparte.
    """
    _exigir_gestion(actor)
    _exigir_no_es_uno_mismo(actor, usuario_id, "desactivar")

    ficha = await _ficha_o_fallo(usuario_id, actor=actor, usuarios=usuarios)
    instante = momento or datetime.now(UTC)

    if es_administrativo(ficha.rol):
        cuantos = await usuarios.contar_administradores(negocio_id=actor.negocio_id)
        _exigir_queda_otro_admin(cuantos=cuantos)

    await usuarios.cambiar_estado(
        negocio_id=actor.negocio_id, usuario_id=usuario_id, estado=ESTADO_INACTIVO, momento=instante
    )
    cerradas = await sesiones.revocar_todas(
        negocio_id=actor.negocio_id,
        usuario_id=usuario_id,
        motivo=MotivoRevocacion.ADMIN,
        momento=instante,
    )
    await auditoria.auditar(
        accion="baja_usuario",
        negocio_id=actor.negocio_id,
        usuario_id=actor.usuario_id,
        entidad="usuario",
        entidad_id=str(usuario_id),
        resultado="inactivo",
        detalle={"sesiones_cerradas": cerradas, "email": ficha.email},
    )
    registro.info(
        "Cuenta desactivada: negocio=%s usuario=%s sesiones=%s",
        actor.negocio_id,
        usuario_id,
        cerradas,
    )

    return ResultadoCuenta(
        usuario=await _ficha_o_fallo(usuario_id, actor=actor, usuarios=usuarios),
        sesiones_cerradas=cerradas,
        avisos=(
            "La cuenta queda desactivada y conserva su historial de consentimiento. Puedes "
            "reactivarla cuando quieras.",
            "Si tenía una sesión abierta, dejará de poder renovarla; su token de acceso actual "
            "caduca en unos minutos.",
        ),
    )


async def reactivar_cuenta(
    actor: Actor,
    *,
    usuario_id: UUID,
    usuarios: RepositorioUsuarios,
    negocios: RepositorioNegocios,
    contrasenas: ServicioContrasenas,
    auditoria: RegistroAuditoria,
    nombre: str | None = None,
    rol_codigo: str | None = None,
    contrasena: str | None = None,
    momento: datetime | None = None,
) -> ResultadoCuenta:
    """Vuelve a habilitar una cuenta dada de baja, opcionalmente con datos nuevos.

    Existe porque la baja es reversible y, sin esta operación, el camino para recuperar a alguien
    sería crear otra cuenta con el mismo correo —que el índice único rechazaría— y quedarse sin
    entender por qué. La contraseña es opcional: si no se indica, se conserva la que tenía, y quien
    la haya olvidado puede recibir una nueva desde la operación de restablecer.
    """
    _exigir_gestion(actor)

    ficha = await _ficha_o_fallo(usuario_id, actor=actor, usuarios=usuarios)
    if ficha.activo:
        raise DatoInvalido("Esa cuenta ya está activa.")

    rol = rol_desde_codigo(rol_codigo) if rol_codigo else ficha.rol
    if not puede_asignar(rol):
        raise SinPermiso(f"No puedes asignar el rol «{_etiqueta_asignable(rol)}».")

    if contrasena is not None:
        validar_contrasena(contrasena, email=ficha.email)

    # Reactivar ocupa una plaza del plan: si el cupo se llenó mientras la cuenta estaba de baja, no
    # se puede volver a habilitar sin ampliarlo o dar de baja a otra.
    uso = await negocios.resumen_uso(negocio_id=actor.negocio_id)
    if int(uso["usuarios_activos"]) >= int(uso["limite_usuarios"]):
        raise DatoInvalido(f"{MENSAJE_LIMITE} El plan permite {uso['limite_usuarios']} usuarios.")

    instante = momento or datetime.now(UTC)
    await usuarios.actualizar_identidad(
        negocio_id=actor.negocio_id,
        usuario_id=usuario_id,
        nombre=limpiar_texto(nombre) or ficha.nombre,
        rol=rol,
        huella=contrasenas.hash(contrasena) if contrasena is not None else None,
    )
    await usuarios.cambiar_estado(
        negocio_id=actor.negocio_id, usuario_id=usuario_id, estado=ESTADO_ACTIVO, momento=instante
    )
    await auditoria.auditar(
        accion="reactivacion_usuario",
        negocio_id=actor.negocio_id,
        usuario_id=actor.usuario_id,
        entidad="usuario",
        entidad_id=str(usuario_id),
        resultado="activo",
        detalle={"rol": str(rol), "contrasena_nueva": contrasena is not None},
    )

    return ResultadoCuenta(usuario=await _ficha_o_fallo(usuario_id, actor=actor, usuarios=usuarios))


async def eliminar_cuenta(
    actor: Actor,
    *,
    usuario_id: UUID,
    usuarios: RepositorioUsuarios,
    sesiones: CierreDeSesiones,
    auditoria: RegistroAuditoria,
    confirmacion: str | None,
    momento: datetime | None = None,
) -> ResultadoCuenta:
    """Borra la cuenta definitivamente.

    Se exige escribir el correo de la cuenta en `confirmacion`. No es un formalismo: esta operación
    **destruye el registro de que esa persona aceptó los términos y condiciones**, porque la
    tabla de consentimientos se borra en cascada, y no hay forma de recuperarlo. Un botón que se
    pulsa sin querer no puede tener esa consecuencia.

    La auditoría sí sobrevive, y por eso la línea de auditoría se escribe **antes** del borrado:
    si se escribiera después, el fallo que más importa —el borrado que sí ocurrió pero cuya
    anotación no— es exactamente el que se produciría al revés.
    """
    _exigir_gestion(actor)
    _exigir_no_es_uno_mismo(actor, usuario_id, "eliminar")

    ficha = await _ficha_o_fallo(usuario_id, actor=actor, usuarios=usuarios)

    if limpiar_texto(confirmacion).lower() != ficha.email.lower():
        raise DatoInvalido(
            "Para borrar la cuenta hay que escribir su correo electrónico exactamente. "
            "Se conserva el historial de acceso, pero se pierde el registro de aceptación de los "
            "términos, y eso no se puede deshacer."
        )

    if es_administrativo(ficha.rol):
        cuantos = await usuarios.contar_administradores(negocio_id=actor.negocio_id)
        _exigir_queda_otro_admin(cuantos=cuantos)

    instante = momento or datetime.now(UTC)
    await auditoria.auditar(
        accion="borrado_usuario",
        negocio_id=actor.negocio_id,
        usuario_id=actor.usuario_id,
        entidad="usuario",
        entidad_id=str(usuario_id),
        resultado="borrado",
        detalle={"email": ficha.email, "rol": str(ficha.rol), "nombre": ficha.nombre},
    )
    cerradas = await sesiones.revocar_todas(
        negocio_id=actor.negocio_id,
        usuario_id=usuario_id,
        motivo=MotivoRevocacion.ADMIN,
        momento=instante,
    )
    await usuarios.eliminar(negocio_id=actor.negocio_id, usuario_id=usuario_id)
    registro.info("Cuenta borrada: negocio=%s usuario=%s", actor.negocio_id, usuario_id)

    return ResultadoCuenta(
        usuario=ficha,
        sesiones_cerradas=cerradas,
        avisos=(
            "La cuenta se ha borrado. Su registro de aceptación de los términos ya no existe.",
        ),
    )


# --------------------------------------------------------------------------- #
# Contraseñas
# --------------------------------------------------------------------------- #


async def restablecer_contrasena(
    actor: Actor,
    *,
    usuario_id: UUID,
    contrasena: str | None,
    usuarios: RepositorioUsuarios,
    sesiones: CierreDeSesiones,
    contrasenas: ServicioContrasenas,
    auditoria: RegistroAuditoria,
    momento: datetime | None = None,
) -> ResultadoCuenta:
    """Asigna una contraseña nueva a otra cuenta y cierra sus sesiones.

    Se cierran **todas**, incluidas las que estuvieran abiertas de buena fe. El caso que justifica
    esta operación es «creo que alguien ha entrado en esa cuenta», y dejar viva la sesión intrusa
    convertiría el restablecimiento en un cambio de contraseña cosmético.
    """
    _exigir_gestion(actor)

    ficha = await _ficha_o_fallo(usuario_id, actor=actor, usuarios=usuarios)
    texto = contrasena or ""
    validar_contrasena(texto, email=ficha.email)

    instante = momento or datetime.now(UTC)
    await usuarios.actualizar_huella(
        negocio_id=actor.negocio_id,
        usuario_id=usuario_id,
        huella=contrasenas.hash(texto),
        momento=instante,
    )
    cerradas = await sesiones.revocar_todas(
        negocio_id=actor.negocio_id,
        usuario_id=usuario_id,
        motivo=MotivoRevocacion.ADMIN,
        momento=instante,
    )
    await auditoria.auditar(
        accion="restablecimiento_contrasena",
        negocio_id=actor.negocio_id,
        usuario_id=actor.usuario_id,
        entidad="usuario",
        entidad_id=str(usuario_id),
        resultado="ok",
        detalle={"sesiones_cerradas": cerradas},
    )
    registro.info(
        "Contraseña restablecida por un administrador: negocio=%s usuario=%s",
        actor.negocio_id,
        usuario_id,
    )

    return ResultadoCuenta(
        usuario=ficha,
        sesiones_cerradas=cerradas,
        avisos=(
            "Comunica la contraseña nueva por un canal privado.",
            "Se cerraron todas sus sesiones, también las que estuvieran abiertas.",
        ),
    )


async def cambiar_mi_contrasena(
    actor: Actor,
    *,
    contrasena_actual: str | None,
    contrasena_nueva: str | None,
    cuentas: RepositorioCuentas,
    sesiones: CierreDeSesiones,
    contrasenas: ServicioContrasenas,
    auditoria: RegistroAuditoria,
    sesion_actual: UUID | None = None,
    momento: datetime | None = None,
) -> ResultadoCuenta:
    """Cambia la contraseña propia, comprobando antes la actual.

    Pedir la contraseña actual es lo que impide que alguien con una sesión abierta y sin conocer la
    clave se apropie de la cuenta: sin esta comprobación, un equipo desatendido durante un minuto
    bastaría para quedarse con ella para siempre.

    Se cierran todas las sesiones **menos la que hace el cambio**: cerrar también la propia sería
    expulsar a quien acaba de hacer lo correcto, y dejar todas abiertas sería no cerrar nada.
    """
    cuenta = await cuentas.obtener(negocio_id=actor.negocio_id, usuario_id=actor.usuario_id)
    if cuenta is None:
        raise NoEncontrado("La cuenta de esta sesión ya no existe.")

    if not contrasenas.verificar(cuenta.hash_password, contrasena_actual or ""):
        # El mensaje distingue este fallo del de «contraseña débil»: son cosas distintas y la
        # respuesta de la persona también lo es.
        raise DatoInvalido("La contraseña actual no es correcta.")

    texto = contrasena_nueva or ""
    if contrasenas.verificar(cuenta.hash_password, texto):
        raise DatoInvalido("La contraseña nueva tiene que ser distinta de la actual.")
    validar_contrasena(texto, email=cuenta.email)

    instante = momento or datetime.now(UTC)
    await cuentas.actualizar_huella(
        negocio_id=actor.negocio_id, usuario_id=actor.usuario_id, huella=contrasenas.hash(texto)
    )
    cerradas = await sesiones.revocar_todas_salvo(
        negocio_id=actor.negocio_id,
        usuario_id=actor.usuario_id,
        excepto=sesion_actual,
        motivo=MotivoRevocacion.ADMIN,
        momento=instante,
    )
    await auditoria.auditar(
        accion="cambio_contrasena",
        negocio_id=actor.negocio_id,
        usuario_id=actor.usuario_id,
        entidad="usuario",
        entidad_id=str(actor.usuario_id),
        resultado="ok",
        detalle={"sesiones_cerradas": cerradas, "sesion_conservada": str(sesion_actual or "")},
    )

    return ResultadoCuenta(
        usuario=FichaUsuario(
            usuario_id=cuenta.usuario_id,
            negocio_id=cuenta.negocio_id,
            email=cuenta.email,
            nombre=cuenta.nombre,
            rol=Rol(cuenta.rol),
            estado=cuenta.estado,
            ultimo_acceso=None,
            creado_en=instante,
        ),
        sesiones_cerradas=cerradas,
        avisos=("Tu contraseña ha cambiado. Se cerraron tus otras sesiones.",),
    )


def catalogo_roles() -> list[dict[str, str]]:
    """Los roles asignables con su descripción, para el desplegable del panel."""
    return [
        {**fila, "descripcion": DESCRIPCION_ROL.get(Rol(fila["codigo"]), "")}
        for fila in catalogo_para_panel()
    ]
