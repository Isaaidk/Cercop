"""Créditos de IA según quién los usa: el super admin no gasta.

El cliente lo pidió así: cada empresa empieza con 100 créditos y los gasta en la IA; el super admin
usa la IA sin límite, porque es quien administra la plataforma y quien otorga créditos a los demás.

En vez de repetir «si es super admin, no cobres» en cada caso de uso, el repositorio de créditos se
envuelve: para el super admin, `consumir` y `devolver` no tocan el saldo y `saldo` lo marca como
ilimitado. Los casos de uso siguen igual y nadie más puede saltarse el cobro.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from contratacion.aplicacion.actor import Actor
from contratacion.dominio.roles import Rol


class CreditosSinLimite:
    """Envuelve un repositorio de créditos: lee el saldo, pero no lo descuenta ni lo devuelve."""

    def __init__(self, base: Any) -> None:
        self._base = base

    async def saldo(self, negocio_id: UUID) -> dict[str, Any]:
        datos = dict(await self._base.saldo(negocio_id))
        return {**datos, "ilimitado": True}

    async def consumir(
        self, negocio_id: UUID, usuario_id: UUID | None, cantidad: int, motivo: str
    ) -> int:
        datos = await self._base.saldo(negocio_id)
        return int(datos.get("disponibles") or 0)

    async def devolver(self, negocio_id: UUID, cantidad: int, motivo: str) -> None:
        return None

    def __getattr__(self, nombre: str) -> Any:
        return getattr(self._base, nombre)


def es_ilimitado(actor: Actor) -> bool:
    return str(actor.rol) == Rol.SUPER_ADMIN.value


def creditos_de[T](actor: Actor, creditos: T) -> T:
    """El repositorio que corresponde a quien pide: sin límite para el super admin."""
    return cast(T, CreditosSinLimite(creditos)) if es_ilimitado(actor) else creditos
