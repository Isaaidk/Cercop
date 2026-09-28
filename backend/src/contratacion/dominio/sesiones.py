"""Reglas de las sesiones simultáneas.

El requisito es duro: **como máximo dos sesiones por cuenta**, y al tercer inicio de sesión se
expulsa la más antigua en lugar de rechazar la nueva.

- **Rechazar** el tercer inicio dejaría al usuario fuera de su cuenta sin manera de entrar: no puede
  cerrar la sesión que no ve, y el soporte tendría que hacerlo por él.
- **Expulsar la más antigua** permite entrar siempre y deja rastro de por qué se cerró la otra.

Qué cuenta como «la más antigua»
--------------------------------
La de **último uso** más lejano, no la creada primero. Si alguien dejó una sesión abierta en un
equipo que ya no usa, esa es la que estorba; la que creó antes pero usa ahora no. Ordenar por fecha
de creación expulsaría la sesión que el usuario tiene delante.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

MAX_SESIONES_POR_DEFECTO = 2
MAX_SESIONES_ABSOLUTO = 20


class EstadoSesion(StrEnum):
    """Estados posibles de una sesión, alineados con la restricción `CHECK` de la base."""

    ACTIVA = "activa"
    INACTIVA = "inactiva"
    REVOCADA = "revocada"
    EXPIRADA = "expirada"
    REEMPLAZADA = "reemplazada"


class MotivoRevocacion(StrEnum):
    """Por qué se cerró una sesión. Es lo que el panel muestra y lo que se audita."""

    LOGOUT = "logout"
    EVICCION = "eviccion"
    ADMIN = "admin"
    REUSO_DETECTADO = "reuso_detectado"
    CIERRE_VENTANA = "cierre_ventana"


# Texto que ve el usuario y que el panel administrativo muestra al lado del color.
DESCRIPCION_MOTIVO: dict[MotivoRevocacion, str] = {
    MotivoRevocacion.LOGOUT: "Cierre de sesión",
    MotivoRevocacion.EVICCION: "Entró desde otro dispositivo y se superó el máximo de sesiones",
    MotivoRevocacion.ADMIN: "Cerrada por un administrador",
    MotivoRevocacion.REUSO_DETECTADO: "Se detectó un uso indebido del token de renovación",
    MotivoRevocacion.CIERRE_VENTANA: "Se cerró la ventana del navegador",
}


@dataclass(frozen=True, slots=True)
class Sesion:
    """Una sesión registrada."""

    id: UUID
    usuario_id: UUID
    negocio_id: UUID
    creada_en: datetime
    ultimo_uso_en: datetime
    expira_en: datetime
    estado: EstadoSesion = EstadoSesion.ACTIVA
    # Solo tiene valor cuando la sesión dejó de estar activa. Se conserva porque es la explicación
    # que hay que dar: «se le cerró por entrar desde otro dispositivo» es una respuesta, y «está
    # rojo» no lo es. El valor `None` significa que nadie la revocó, no que no sepamos por qué.
    motivo_revocacion: MotivoRevocacion | None = None

    def vigente(self, momento: datetime) -> bool:
        """¿Sirve para autenticar en este instante?

        Se comprueban las dos cosas: que el estado sea «activa» y que no haya pasado su fecha. Mirar
        solo el estado dejaría vivas las sesiones cuya revocación no llegó a marcarse.
        """
        return self.estado is EstadoSesion.ACTIVA and self.expira_en > momento

    def minutos_restantes(self, momento: datetime) -> int:
        restante = self.expira_en - momento
        return max(0, int(restante.total_seconds() // 60))


def sesiones_a_expulsar(
    vigentes: Sequence[Sesion], maximo: int = MAX_SESIONES_POR_DEFECTO
) -> tuple[UUID, ...]:
    """Sesiones que hay que revocar para que la nueva quepa dentro del límite.

    Se reserva un hueco para la que se está creando: con un máximo de dos y dos ya abiertas, hay que
    expulsar una. Se devuelven las de último uso más lejano, y el máximo se acota por arriba para
    que un valor absurdo en la base no deje al usuario sin poder entrar.
    """
    limite = max(1, min(maximo, MAX_SESIONES_ABSOLUTO))
    sobrantes = len(vigentes) - limite + 1
    if sobrantes <= 0:
        return ()
    ordenadas = sorted(vigentes, key=lambda sesion: sesion.ultimo_uso_en)
    return tuple(sesion.id for sesion in ordenadas[:sobrantes])


def sesion_mas_reciente(vigentes: Sequence[Sesion]) -> Sesion | None:
    """La de uso más reciente. `None` si no hay ninguna."""
    if not vigentes:
        return None
    return max(vigentes, key=lambda sesion: sesion.ultimo_uso_en)
