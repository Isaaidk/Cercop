"""Puerto de gestión de las cuentas de un negocio.

Por qué es un puerto aparte y no más métodos de `RepositorioCuentas`
-------------------------------------------------------------------
`RepositorioCuentas` es el puerto de la **autenticación**: resolver un correo, leer una cuenta para
comprobar su contraseña, contar intentos fallidos. Este es el de la **administración**:
crear cuentas, darlas de baja y cambiar contraseñas ajenas. Son dos responsabilidades distintas
y las usan dos entornos distintos —el inicio de sesión y el panel de administración—, así que
mezclarlas obligaría a cualquier doble de prueba a implementar también lo que no usa.

Hay además una razón práctica que decidió la separación: añadir métodos a un `Protocol` existente
obliga a tocar todos los dobles que ya existen, y en este proyecto son varios. Un puerto nuevo no
rompe nada de lo que ya funcionaba.

Sobre el borrado
----------------
Hay dos operaciones y no una, y no es indecisión: son consecuencias distintas.

- `desactivar` es **reversible**. La fila permanece, la persona desaparece de la lista de usuarios
  activos, sus sesiones se cierran y no puede volver a entrar. La auditoría y —esto es lo que manda—
  **el registro de que aceptó los términos** siguen ahí.
- `eliminar` es **definitivo**. La fila se va, y con ella sus consentimientos, porque la tabla tiene
  `ON DELETE CASCADE`. La auditoría sobrevive: no tiene clave ajena hacia `usuario`.

Que el borrado destruya la prueba del consentimiento es la razón de que existan las dos. En un
sistema cuyo propósito declarado incluye poder demostrar que alguien aceptó unas condiciones, borrar
la fila es perder la evidencia. Por eso el borrado real no se esconde: se ofrece como una acción
aparte, con su propio aviso, en lugar de ser el único botón.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from contratacion.dominio.roles import Rol
from contratacion.dominio.sesiones import MotivoRevocacion


@dataclass(frozen=True, slots=True)
class FichaUsuario:
    """Los datos de una cuenta que necesita el panel de administración.

    No incluye la huella de la contraseña y no es un olvido: este objeto se serializa hacia el
    cliente, y un campo que se envía es un campo que algún día se pinta por error. Si no está en el
    objeto, no puede salir.
    """

    usuario_id: UUID
    negocio_id: UUID
    email: str
    nombre: str
    rol: Rol
    estado: str
    ultimo_acceso: datetime | None
    creado_en: datetime

    @property
    def activo(self) -> bool:
        """¿Puede esta cuenta entrar al sistema?"""
        return self.estado in {"activo", "pendiente"}

    def como_diccionario(self) -> dict[str, object]:
        return {
            "usuario_id": str(self.usuario_id),
            "email": self.email,
            "nombre": self.nombre,
            "rol": str(self.rol),
            "estado": self.estado,
            "activo": self.activo,
            "ultimo_acceso": self.ultimo_acceso.isoformat() if self.ultimo_acceso else None,
            "creado_en": self.creado_en.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class NuevaCuenta:
    """Lo que hace falta para dar de alta una cuenta."""

    usuario_id: UUID
    negocio_id: UUID
    email: str
    nombre: str
    rol: Rol
    huella: str
    momento: datetime


class RepositorioUsuarios(Protocol):
    """Alta, baja y consulta de las cuentas de un negocio."""

    async def crear(self, cuenta: NuevaCuenta) -> UUID:
        """Inserta la cuenta y devuelve su identificador.

        Debe fallar si el correo ya está en uso **en cualquier negocio**, no solo en este. Lo
        garantiza un índice único sobre el correo, no una comprobación previa: dos altas simultáneas
        con el mismo correo podrían pasar las dos por una comprobación, y solo el índice las para.
        """
        ...

    async def obtener(self, *, negocio_id: UUID, usuario_id: UUID) -> FichaUsuario | None:
        """Cuenta concreta del negocio. `None` si no existe o no es de este negocio."""
        ...

    async def listar(
        self, *, negocio_id: UUID, incluir_inactivos: bool = False
    ) -> Sequence[FichaUsuario]:
        """Cuentas del negocio, ordenadas por nombre.

        Por defecto deja fuera las dadas de baja: el listado del panel sirve para trabajar con quien
        está dentro, y mezclar las bajas obliga a filtrarlas mentalmente en cada mirada.
        """
        ...

    async def contar_activos(self, *, negocio_id: UUID) -> int:
        """Cuántas cuentas activas o pendientes hay, para respetar el límite del plan."""
        ...

    async def contar_administradores(self, *, negocio_id: UUID) -> int:
        """Cuántos administradores activos hay.

        Se consulta antes de dar de baja a uno para no dejar la empresa sin nadie que pueda
        gestionar cuentas. Recuperarse de eso exige acceso a la base de datos.
        """
        ...

    async def actualizar_huella(
        self, *, negocio_id: UUID, usuario_id: UUID, huella: str, momento: datetime
    ) -> None:
        """Sustituye la contraseña."""
        ...

    async def actualizar_identidad(
        self, *, negocio_id: UUID, usuario_id: UUID, nombre: str, rol: Rol, huella: str | None
    ) -> None:
        """Cambia nombre, rol y, si se indica, la contraseña. Se usa al reactivar una cuenta."""
        ...

    async def cambiar_estado(
        self, *, negocio_id: UUID, usuario_id: UUID, estado: str, momento: datetime
    ) -> None:
        """Activa, desactiva o bloquea una cuenta."""
        ...

    async def eliminar(self, *, negocio_id: UUID, usuario_id: UUID) -> None:
        """Borra la fila definitivamente. Se lleva por delante sus consentimientos."""
        ...


class RegistroAuditoria(Protocol):
    """Anotar una acción en el registro de auditoría.

    Puerto estrecho, por la misma razón que `CierreDeSesiones`: estos casos de uso solo necesitan
    escribir una línea, y añadir el método a `RepositorioCuentas` obligaría a los dobles de prueba
    a saber auditar aunque no lo estén probando.

    La auditoría de la gestión de cuentas no es un adorno: quién creó a quién, quién le cambió la
    contraseña y quién lo dio de baja son las preguntas que se hacen cuando algo va mal, y ninguna
    se puede responder mirando la tabla `usuario`, porque la baja borra o desactiva la fila.
    """

    async def auditar(
        self,
        *,
        accion: str,
        negocio_id: UUID,
        usuario_id: UUID | None = None,
        entidad: str | None = None,
        entidad_id: str | None = None,
        resultado: str | None = None,
        detalle: dict[str, Any] | None = None,
    ) -> None:
        """Escribe la línea. El negocio es obligatorio: la tabla no admite filas sin él."""
        ...


class CierreDeSesiones(Protocol):
    """Cerrar todas las sesiones de una cuenta.

    Es un puerto **estrecho**: describe lo único que estos casos de uso necesitan de las sesiones, y
    nada más. Existe en lugar de añadir el método a `RepositorioSesiones` por una razón concreta:
    ampliar un `Protocol` que ya usan los dobles de prueba obliga a implementar el método nuevo en
    todos ellos, y varios de esos dobles existen precisamente para comprobar que **no** se llama a
    cosas de más. Un puerto nuevo, con una sola operación, no rompe nada y además deja escrito que
    dar de baja una cuenta solo necesita esto.

    Un objeto que ya sepa revocar todas las sesiones lo cumple sin cambiar una línea: la
    comprobación es estructural.
    """

    async def revocar_todas(
        self,
        *,
        negocio_id: UUID,
        usuario_id: UUID,
        motivo: MotivoRevocacion,
        momento: datetime,
    ) -> int:
        """Marca como revocadas todas las sesiones activas de la cuenta. Devuelve cuántas cerró."""
        ...

    async def revocar_todas_salvo(
        self,
        *,
        negocio_id: UUID,
        usuario_id: UUID,
        excepto: UUID | None,
        motivo: MotivoRevocacion,
        momento: datetime,
    ) -> int:
        """Revoca todas las sesiones activas menos la indicada.

        La usa quien cambia su propia contraseña, para no expulsarse a sí mismo. Solo puede
        conservar una sesión suya: la operación está acotada al `usuario_id`.
        """
        ...
