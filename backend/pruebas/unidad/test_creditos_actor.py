"""Créditos de IA: cada empresa empieza con 100 y el super admin usa la IA sin gastar."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID, uuid4

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.creditos_actor import CreditosSinLimite, creditos_de, es_ilimitado
from contratacion.dominio.creditos import REGALO_INICIAL


class _Saldo:
    def __init__(self) -> None:
        self.disponibles = REGALO_INICIAL
        self.devueltos = 0

    async def saldo(self, negocio_id: UUID) -> dict[str, Any]:
        return {"disponibles": self.disponibles}

    async def consumir(
        self, negocio_id: UUID, usuario_id: UUID | None, cantidad: int, motivo: str
    ) -> int:
        self.disponibles -= cantidad
        return self.disponibles

    async def devolver(self, negocio_id: UUID, cantidad: int, motivo: str) -> None:
        self.devueltos += cantidad


def _actor(rol: str) -> Actor:
    return Actor(usuario_id=uuid4(), negocio_id=uuid4(), rol=rol)


def test_cada_empresa_empieza_con_100() -> None:
    assert REGALO_INICIAL == 100


def test_el_super_admin_no_gasta_creditos() -> None:
    actor = _actor("super_admin")
    base = _Saldo()
    creditos = creditos_de(actor, base)
    assert isinstance(creditos, CreditosSinLimite) and es_ilimitado(actor)
    assert asyncio.run(creditos.consumir(actor.negocio_id, actor.usuario_id, 3, "Generar")) == 100
    asyncio.run(creditos.devolver(actor.negocio_id, 3, "Devolución"))
    assert base.disponibles == 100 and base.devueltos == 0
    assert asyncio.run(creditos.saldo(actor.negocio_id))["ilimitado"] is True


def test_los_demas_roles_si_gastan() -> None:
    for rol in ("dueno_empresa", "usuario"):
        actor = _actor(rol)
        base = _Saldo()
        creditos = creditos_de(actor, base)
        assert creditos is base and not es_ilimitado(actor)
        assert (
            asyncio.run(creditos.consumir(actor.negocio_id, actor.usuario_id, 1, "Pregunta")) == 99
        )
