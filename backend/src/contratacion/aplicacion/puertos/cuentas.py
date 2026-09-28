"""Puertos de cuentas y sesiones.

Aquí está el problema más difícil del sistema multi-inquilino, y conviene tenerlo escrito porque la
solución no es evidente.

**Para iniciar sesión hay que leer `usuario`, y `usuario` está protegido por RLS.** Las políticas
comparan `negocio_id` con el negocio del contexto, y al iniciar sesión todavía **no se sabe a qué
negocio pertenece quien llama**: es justo lo que se está averiguando. Sin contexto, la consulta no
devuelve ninguna fila y el inicio de sesión sería imposible.

La solución no puede ser abrir la tabla a la aplicación: anularía el aislamiento para todo lo demás.
Se usa una función de base de datos que devuelve **solo dos identificadores** —usuario y negocio—,
sin contraseñas, sin correo y sin ningún dato personal. Con ellos, la aplicación fija el contexto y
lee la fila completa por la vía normal, con RLS aplicándose.

Esa separación es deliberada: si la aplicación se viera comprometida, lo único extra que podría
obtener es el par correo → identificadores, no las contraseñas ni los datos de los clientes.

El correo que no existe y el que existe pero está bloqueado **no se distinguen** desde fuera: el
caso de uso devuelve el mismo error y el mismo tiempo de respuesta en ambos casos.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from contratacion.dominio.sesiones import MotivoRevocacion, Sesion


@dataclass(frozen=True, slots=True)
class Cuenta:
    """Lo que hace falta para autenticar y autorizar a un usuario."""

    usuario_id: UUID
    negocio_id: UUID
    email: str
    nombre: str
    rol: str
    estado: str
    hash_password: str
    intentos_fallidos: int
    bloqueado_hasta: datetime | None
    debe_aceptar_politica_version: int | None

    @property
    def activa(self) -> bool:
        return self.estado == "activo"

    @property
    def puede_iniciar_sesion(self) -> bool:
        """Un usuario pendiente puede entrar: es como acepta los términos en el primer acceso.

        Un usuario inactivo o bloqueado, no. Distinguirlos aquí evita decidirlo en cada caso de uso
        y en cada enrutador.
        """
        return self.estado in {"activo", "pendiente"}


@dataclass(frozen=True, slots=True)
class SesionGuardada:
    """Una sesión con la huella de su token de renovación."""

    sesion: Sesion
    refresh_hash: str


class RepositorioCuentas(Protocol):
    """Lectura y actualización del estado de las cuentas."""

    async def resolver(self, email: str) -> tuple[UUID, UUID] | None:
        """Devuelve `(usuario_id, negocio_id)` del correo, o `None` si no hay cuenta.

        Es la única lectura que se hace sin contexto de negocio, y devuelve **solo identificadores**
        a propósito. Está implementada sobre una función de base de datos `SECURITY DEFINER` para
        poder atravesar RLS sin exponer nada más.
        """
        ...

    async def obtener(self, *, negocio_id: UUID, usuario_id: UUID) -> Cuenta | None:
        """Cuenta completa, ya dentro del contexto del negocio."""
        ...

    async def registrar_acceso_correcto(
        self, *, negocio_id: UUID, usuario_id: UUID, momento: datetime
    ) -> None:
        """Reinicia el contador de fallos y anota el último acceso."""
        ...

    async def registrar_fallo(
        self,
        *,
        negocio_id: UUID,
        usuario_id: UUID,
        intentos: int,
        bloqueado_hasta: datetime | None,
    ) -> None:
        """Anota un intento fallido y, si toca, hasta cuándo bloquear."""
        ...

    async def actualizar_huella(self, *, negocio_id: UUID, usuario_id: UUID, huella: str) -> None:
        """Sustituye la huella de la contraseña cuando el algoritmo se ha quedado atrás."""
        ...

    async def cambiar_estado(
        self,
        *,
        negocio_id: UUID,
        usuario_id: UUID,
        estado: str,
        momento: datetime,
    ) -> None:
        """Activa, desactiva o bloquea una cuenta."""
        ...

    async def listar(
        self, *, negocio_id: UUID, estado: str | None = None
    ) -> Sequence[dict[str, Any]]:
        """Cuentas del negocio, para el panel administrativo."""
        ...

    async def auditar(
        self,
        *,
        accion: str,
        negocio_id: UUID,
        usuario_id: UUID | None = None,
        entidad: str | None = None,
        entidad_id: str | None = None,
        resultado: str | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
        detalle: dict[str, Any] | None = None,
    ) -> None:
        """Escribe una línea en el registro de auditoría.

        El negocio es **obligatorio**: la tabla es del plano de negocio y su política no admite
        filas sin él. Un intento fallido con un correo desconocido no se puede auditar aquí, y se
        anota en el registro de la aplicación.
        """
        ...


class RepositorioSesiones(Protocol):
    """Ciclo de vida de las sesiones."""

    async def vigentes(
        self, *, negocio_id: UUID, usuario_id: UUID, momento: datetime
    ) -> Sequence[Sesion]:
        """Sesiones activas y no caducadas, para decidir a quién se expulsa."""
        ...

    async def crear(
        self,
        *,
        sesion_id: UUID,
        negocio_id: UUID,
        usuario_id: UUID,
        refresh_hash: str,
        expira_en: datetime,
        momento: datetime,
        dispositivo: str | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> UUID:
        """Registra una sesión nueva con el identificador que se ha firmado en el token.

        El identificador se decide **antes** y se emite el token con él, en vez de dejar que lo
        genere la base y firmar después: así no puede existir un token válido que apunte a una
        sesión que todavía no está registrada.
        """
        ...

    async def por_id(self, *, negocio_id: UUID, sesion_id: UUID) -> SesionGuardada | None:
        """Sesión e huella de su token de renovación."""
        ...

    async def rotar(
        self,
        *,
        negocio_id: UUID,
        sesion_id: UUID,
        refresh_hash: str,
        ultimo_uso_en: datetime,
    ) -> None:
        """Guarda la huella del token de renovación nuevo y actualiza el último uso."""
        ...

    async def revocar(
        self,
        *,
        negocio_id: UUID,
        sesion_id: UUID,
        motivo: MotivoRevocacion,
        momento: datetime,
    ) -> None:
        """Marca una sesión como revocada."""
        ...

    async def revocar_varias(
        self,
        *,
        negocio_id: UUID,
        sesion_ids: Sequence[UUID],
        motivo: MotivoRevocacion,
        momento: datetime,
    ) -> int:
        """Revoca varias sesiones de golpe. Devuelve cuántas se marcaron."""
        ...

    async def revocar_todas(
        self, *, negocio_id: UUID, usuario_id: UUID, motivo: MotivoRevocacion, momento: datetime
    ) -> int:
        """Cierra todas las sesiones de una cuenta."""
        ...

    async def activas_del_negocio(self, *, negocio_id: UUID, momento: datetime) -> Sequence[Sesion]:
        """Todas las sesiones vigentes del negocio, sin filtrar por usuario.

        Es la lectura que necesita el cuadro de presencia para saber quién *podría* estar conectado.
        Está acotada por construcción —a lo sumo el máximo de sesiones por el número de cuentas— así
        que no hace falta limitarla ni paginarla.
        """
        ...

    async def revocadas_del_negocio(
        self, *, negocio_id: UUID, limite: int = 500
    ) -> Sequence[Sesion]:
        """Sesiones que ya no están activas, las de uso más reciente primero.

        Sirve para **explicar** los rojos: sin esto, el panel podría decir que alguien no está
        conectado, pero no que se le expulsó por entrar desde otro dispositivo o que un
        administrador le cerró la sesión, que es lo que el administrador necesita saber.

        Solo devuelve las que dejaron de estarlo. Mezclarlas con las activas sería arriesgado,
        porque el cuadro de presencia comprueba la vigencia sesión a sesión y una sesión cerrada no
        debe poder colarse en esa comprobación.
        """
        ...
