"""Administración de la plataforma: ver las empresas, darles tiempo y suspenderlas.

Es la única parte del sistema que actúa **sobre empresas ajenas**, así que todo pasa por el mismo
guardián de rol. Las vistas conceden qué datos se leen; esto decide sobre la existencia misma de una
empresa, y por eso no se apoya en ellas: un administrador de negocio con todas las vistas concedidas
sigue sin poder tocar a otra empresa.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.puertos.negocios import EmpresaDePlataforma, RepositorioNegocios
from contratacion.aplicacion.puertos.usuarios import RegistroAuditoria
from contratacion.dominio.errores import (
    MENSAJE_SUSPENSION,
    DatoInvalido,
    NoEncontrado,
    SinPermiso,
)
from contratacion.dominio.roles import Rol

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


def es_de_plataforma(actor: Actor) -> bool:
    """¿Quien llama es el dueño del sistema?

    Se normaliza el rol antes de compararlo, en vez de comparar cadenas: el rol puede llegar del
    token como enumeración o como texto, y una comparación directa negaría el paso a quien sí lo
    tiene según de dónde viniera. Negar el paso al dueño del sistema es un fallo que se nota tarde.
    """
    try:
        return Rol(str(actor.rol).strip().lower()) is Rol.SUPER_ADMIN
    except ValueError:
        return False


def _exigir_plataforma(actor: Actor) -> None:
    if not es_de_plataforma(actor):
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
