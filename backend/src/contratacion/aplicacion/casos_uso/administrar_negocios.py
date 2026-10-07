"""Administración de la plataforma: ver las empresas, darles tiempo y suspenderlas o retirarlas.

Es la única parte del sistema que actúa **sobre empresas ajenas**, así que todo pasa por el mismo
guardián de rol. Las vistas conceden qué datos se leen; esto decide sobre la existencia misma de una
empresa, y por eso no se apoya en ellas: un administrador de negocio con todas las vistas concedidas
sigue sin poder tocar a otra empresa.

Aquí conviven las dos operaciones que **cortan el acceso** a una empresa, y no son lo mismo:

- **Suspender** para el servicio y se deshace con `reactivar_empresa`. Es lo que se usa para un
  impago o para una investigación en curso.
- **Eliminar** se lleva la empresa, sus cuentas y su registro de aceptación de los términos. No se
deshace y no hay ningún camino de vuelta en el sistema: exige escribir el nombre de la empresa y no
permite borrar la que da acceso a quien lo pide.

Lo que la eliminación **no** toca, a propósito: el histórico de contratación, que es de la
plataforma y no de la empresa —borrar un cliente no puede restar datos a los demás—, y la
auditoría, que sobrevive para poder decir quién lo hizo.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.puertos.negocios import EmpresaDePlataforma, RepositorioNegocios
from contratacion.aplicacion.puertos.usuarios import (
    CierreDeSesiones,
    RegistroAuditoria,
    RepositorioUsuarios,
)
from contratacion.dominio.errores import (
    MENSAJE_SUSPENSION,
    DatoInvalido,
    NoEncontrado,
    SinPermiso,
)
from contratacion.dominio.roles import es_administrativo, es_de_plataforma
from contratacion.dominio.sesiones import MotivoRevocacion

registro = logging.getLogger(__name__)

ESTADO_ACTIVO = "activo"
ESTADO_SUSPENDIDO = "suspendido"


@dataclass(frozen=True, slots=True)
class ResultadoDeAdministracion:
    """Lo que se devuelve tras suspender o reactivar una empresa."""

    negocio_id: UUID
    nombre: str
    estado: str
    activa: bool
    aviso: str

    def como_diccionario(self) -> dict[str, object]:
        return {
            "negocio_id": str(self.negocio_id),
            "nombre": self.nombre,
            "estado": self.estado,
            "activa": self.activa,
            "aviso": self.aviso,
        }


def _exigir_plataforma(actor: Actor) -> None:
    if not es_de_plataforma(actor.rol):
        raise SinPermiso("Solo el superadministrador de la plataforma puede administrar empresas.")


async def listar_empresas(
    actor: Actor, *, repositorio: RepositorioNegocios
) -> tuple[EmpresaDePlataforma, ...]:
    """Todas las empresas registradas, para el panel de la plataforma.

    Devuelve cuántas cuentas tiene cada una y **ninguna** información de sus usuarios: ni correos,
    ni nombres. El dueño del sistema necesita decidir a quién dar acceso y a quién suspender, y para
    eso el tamaño de la plantilla basta.
    """
    _exigir_plataforma(actor)
    return tuple(await repositorio.listar())


async def _cambiar_estado(
    actor: Actor,
    *,
    negocio_id: UUID,
    estado: str,
    aviso: str,
    repositorio: RepositorioNegocios,
    auditoria: RegistroAuditoria,
    momento: datetime | None = None,
) -> ResultadoDeAdministracion:
    _exigir_plataforma(actor)

    guardada = await repositorio.obtener(negocio_id=negocio_id)
    if guardada is None:
        raise NoEncontrado("Esa empresa no existe.")

    if guardada.estado == estado:
        # No es un error —el resultado es el que se pedía— pero sí conviene no escribir una línea de
        # auditoría que diga que se cambió algo que ya estaba así: ensuciaría el rastro de quién
        # cortó el servicio y cuándo.
        raise DatoInvalido(
            f"La empresa «{guardada.nombre}» ya está en estado «{estado}». No hay nada que cambiar."
        )

    instante = momento or datetime.now(UTC)
    await repositorio.cambiar_estado(negocio_id=negocio_id, estado=estado, momento=instante)
    await auditoria.auditar(
        accion=f"negocio_{estado}",
        negocio_id=negocio_id,
        usuario_id=actor.usuario_id,
        entidad="negocio",
        entidad_id=str(negocio_id),
        resultado=estado,
        detalle={"nombre": guardada.nombre, "estado_anterior": guardada.estado},
    )
    return ResultadoDeAdministracion(
        negocio_id=negocio_id,
        nombre=guardada.nombre,
        estado=estado,
        activa=estado in {"prueba", "activo"},
        aviso=aviso,
    )


async def suspender_empresa(
    actor: Actor,
    *,
    negocio_id: UUID,
    repositorio: RepositorioNegocios,
    auditoria: RegistroAuditoria,
    momento: datetime | None = None,
) -> ResultadoDeAdministracion:
    """Corta el acceso a una empresa entera.

    A partir de aquí sus usuarios no pueden leer nada: el guardián de cada petición mira el estado
    de la empresa y responde con el aviso. No se borra nada ni se tocan sus datos —suspender es
    reversible y debe serlo— y sus sesiones abiertas dejan de servir en la siguiente petición, que
    como mucho es el latido de presencia, unos segundos después.
    """
    return await _cambiar_estado(
        actor,
        negocio_id=negocio_id,
        estado=ESTADO_SUSPENDIDO,
        aviso=MENSAJE_SUSPENSION,
        repositorio=repositorio,
        auditoria=auditoria,
        momento=momento,
    )


async def reactivar_empresa(
    actor: Actor,
    *,
    negocio_id: UUID,
    repositorio: RepositorioNegocios,
    auditoria: RegistroAuditoria,
    momento: datetime | None = None,
) -> ResultadoDeAdministracion:
    """Devuelve el acceso. Las vistas que tuviera concedidas no se han tocado."""
    return await _cambiar_estado(
        actor,
        negocio_id=negocio_id,
        estado=ESTADO_ACTIVO,
        aviso="La empresa vuelve a tener acceso al aplicativo.",
        repositorio=repositorio,
        auditoria=auditoria,
        momento=momento,
    )


@dataclass(frozen=True, slots=True)
class ResultadoDeBorrado:
    """Lo que se devuelve tras retirar una empresa o una cuenta.

    Los recuentos no son adorno: quien pulsa el botón se queda sin nada que mirar —la empresa ya
    no está en la lista— y es lo único que le dice qué acaba de pasar y qué se ha cerrado por el
    camino.
    """

    nombre: str
    negocio_id: UUID
    cuentas_borradas: int
    sesiones_cerradas: int
    avisos: tuple[str, ...] = ()

    def como_diccionario(self) -> dict[str, object]:
        return {
            "nombre": self.nombre,
            "negocio_id": str(self.negocio_id),
            "cuentas_borradas": self.cuentas_borradas,
            "sesiones_cerradas": self.sesiones_cerradas,
            "avisos": list(self.avisos),
        }


async def eliminar_empresa(
    actor: Actor,
    *,
    negocio_id: UUID,
    repositorio: RepositorioNegocios,
    usuarios: RepositorioUsuarios,
    sesiones: CierreDeSesiones,
    auditoria: RegistroAuditoria,
    confirmacion: str | None,
    momento: datetime | None = None,
) -> ResultadoDeBorrado:
    """Retira una empresa entera: sus cuentas, sus accesos y su plantilla.

    Es la operación más destructiva del sistema, y por eso lleva tres guardas. Ninguna es ceremonia:

    1. **Solo el dueño de la plataforma.** No depende de las vistas concedidas; un administrador de
       empresa con todas las vistas sigue sin poder tocar a otra.
    2. **No se puede borrar la empresa propia.** Quien lo pide se quedaría fuera del sistema y sin
       forma de volver a entrar. Para cortarle el acceso a una empresa está suspenderla, que sí se
       deshace.
    3. **Hay que escribir el nombre de la empresa.** Se destruye el registro de aceptación de los
       términos de sus personas, porque la tabla de consentimientos se va en cascada, y eso no se
       recupera. Un botón que se pulsa sin querer no puede tener esa consecuencia.

    Las cuentas se leen **antes** de borrar, y no es un detalle de estilo. Hacen falta dos cosas de
    ellas: cuántas eran, para poder decirlo, y cuáles, para cerrarles la sesión viva del almacén.
    La fila de la sesión se va con el borrado, pero la marca del almacén no: sin este paso, alguien
    recién expulsado podría seguir renovando su token unos minutos.

    La auditoría se escribe **antes** del borrado, igual que al borrar una cuenta: el fallo que
    importa es el borrado que sí ocurrió y cuya anotación no, y escribir después lo produce justo al
    revés.
    """
    _exigir_plataforma(actor)

    guardada = await repositorio.obtener(negocio_id=negocio_id)
    if guardada is None:
        raise NoEncontrado("Esa empresa no existe.")

    if negocio_id == actor.negocio_id:
        raise DatoInvalido(
            "No se puede eliminar la empresa a la que pertenece tu propia cuenta: te quedarías "
            "fuera del sistema y no habría forma de volver a entrar. Para cortarle el acceso está "
            "suspenderla, que se puede deshacer."
        )

    if _limpiar(confirmacion) != guardada.nombre.strip().lower():
        raise DatoInvalido(
            f"Para eliminar la empresa hay que escribir su nombre («{guardada.nombre}») "
            "exactamente. Se borran sus cuentas, sus accesos y el registro de aceptación de los "
            "términos, y eso no se puede deshacer."
        )

    cuentas = await usuarios.listar(negocio_id=negocio_id, incluir_inactivos=True)
    instante = momento or datetime.now(UTC)

    await auditoria.auditar(
        accion="borrado_negocio",
        negocio_id=actor.negocio_id,
        usuario_id=actor.usuario_id,
        entidad="negocio",
        entidad_id=str(negocio_id),
        resultado="borrado",
        detalle={
            "nombre": guardada.nombre,
            "ruc": guardada.ruc,
            "estado": guardada.estado,
            "cuentas": len(cuentas),
        },
    )

    cerradas = 0
    for cuenta in cuentas:
        cerradas += await sesiones.revocar_todas(
            negocio_id=negocio_id,
            usuario_id=cuenta.usuario_id,
            motivo=MotivoRevocacion.ADMIN,
            momento=instante,
        )
    await repositorio.eliminar(negocio_id=negocio_id)
    registro.info(
        "Empresa eliminada: negocio=%s nombre=%s cuentas=%s",
        negocio_id,
        guardada.nombre,
        len(cuentas),
    )

    return ResultadoDeBorrado(
        nombre=guardada.nombre,
        negocio_id=negocio_id,
        cuentas_borradas=len(cuentas),
        sesiones_cerradas=cerradas,
        avisos=(
            "La empresa y sus cuentas ya no existen. El histórico de contratación no se ha tocado: "
            "es de la plataforma, no de la empresa.",
        ),
    )


async def eliminar_cuenta_de_empresa(
    actor: Actor,
    *,
    negocio_id: UUID,
    usuario_id: UUID,
    usuarios: RepositorioUsuarios,
    sesiones: CierreDeSesiones,
    auditoria: RegistroAuditoria,
    confirmacion: str | None,
    momento: datetime | None = None,
) -> ResultadoDeBorrado:
    """Retira una cuenta concreta, de cualquier empresa.

    Es el mismo borrado que hace un administrador con su propia gente —destruye el registro de
    aceptación de los términos, que se va en cascada— pero ejercido desde la plataforma y sobre una
    empresa ajena, así que necesita sus propias guardas: ser el dueño del sistema, escribir el
    correo a mano y no poder borrar la cuenta con la que se está actuando.

    Se conserva además la regla de **una empresa no puede quedarse sin administradores**. No es una
    limitación de la plataforma sino del modelo: sin ninguno, esa empresa no puede volver a
    gestionar sus cuentas ni sus accesos desde dentro, y no habría forma de arreglarlo salvo
    entrando a mano en la base. Si lo que se quiere es retirar la empresa entera, está
    `eliminar_empresa`, que sí se lleva todo.

    La empresa tiene que existir: la cuenta se busca **dentro** de ella, así que pedir un
    identificador de otra empresa o de una empresa borrada da «no existe» y no un borrado a ciegas.
    """
    _exigir_plataforma(actor)

    if usuario_id == actor.usuario_id:
        raise DatoInvalido(
            "No se puede eliminar la cuenta con la que se está actuando: es la que da acceso al "
            "panel de la plataforma."
        )

    ficha = await usuarios.obtener(negocio_id=negocio_id, usuario_id=usuario_id)
    if ficha is None:
        raise NoEncontrado("Esa cuenta no existe en esa empresa.")

    if _limpiar(confirmacion) != ficha.email.strip().lower():
        raise DatoInvalido(
            f"Para eliminar la cuenta hay que escribir su correo («{ficha.email}») exactamente. Se "
            "pierde su registro de aceptación de los términos y eso no se puede deshacer."
        )

    if es_administrativo(ficha.rol):
        cuantos = await usuarios.contar_administradores(negocio_id=negocio_id)
        if cuantos <= 1:
            raise DatoInvalido(
                "Esa es la última cuenta administrativa de la empresa. Sin ninguna, la empresa no "
                "puede volver a gestionar sus cuentas desde dentro. Para retirarla entera está "
                "«Eliminar empresa»."
            )

    instante = momento or datetime.now(UTC)
    await auditoria.auditar(
        accion="borrado_usuario",
        negocio_id=actor.negocio_id,
        usuario_id=actor.usuario_id,
        entidad="usuario",
        entidad_id=str(usuario_id),
        resultado="borrado",
        detalle={
            "email": ficha.email,
            "rol": str(ficha.rol),
            "nombre": ficha.nombre,
            "negocio_destino": str(negocio_id),
            "desde_plataforma": True,
        },
    )
    cerradas = await sesiones.revocar_todas(
        negocio_id=negocio_id,
        usuario_id=usuario_id,
        motivo=MotivoRevocacion.ADMIN,
        momento=instante,
    )
    await usuarios.eliminar(negocio_id=negocio_id, usuario_id=usuario_id)
    registro.info(
        "Cuenta eliminada desde la plataforma: negocio=%s usuario=%s", negocio_id, usuario_id
    )

    return ResultadoDeBorrado(
        nombre=ficha.nombre,
        negocio_id=negocio_id,
        cuentas_borradas=1,
        sesiones_cerradas=cerradas,
        avisos=(
            "La cuenta se ha borrado. Su registro de aceptación de los términos ya no existe.",
        ),
    )


def _limpiar(texto: str | None) -> str:
    """Normaliza lo que se escribe para confirmar un borrado.

    Se compara en minúsculas y sin espacios de sobra porque el objetivo es que nadie borre una
    empresa por un despiste, no que acierte con las mayúsculas del nombre o con un espacio final que
    el navegador añadió al copiar y pegar.
    """
    return (texto or "").strip().lower()
