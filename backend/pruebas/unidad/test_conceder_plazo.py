"""El plazo que se elige sustituye al anterior, también si es más corto."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.casos_uso.gestionar_acceso import conceder_acceso, vistas_vigentes
from contratacion.dominio.acceso import AccesoVista, Plazo, Vista
from contratacion.dominio.errores import EmpresaSuspendida

NEGOCIO = uuid4()
USUARIO = uuid4()
ACTOR = Actor(usuario_id=uuid4(), negocio_id=NEGOCIO, rol="super_admin")
AHORA = datetime(2026, 11, 4, 15, 0, tzinfo=UTC)


class CacheMudo:
    habilitada = False

    async def obtener(self, clave: str) -> str | None:
        return None

    async def obtener_renovando(self, clave: str, ttl_seg: int) -> str | None:
        return None

    async def guardar(self, clave: str, valor: str, ttl_seg: int) -> None:
        return None

    async def eliminar(self, clave: str) -> None:
        return None

    async def incrementar(self, clave: str) -> int:
        return 1

    async def ping(self) -> bool:
        return False

    async def cerrar(self) -> None:
        return None


class AccesosQueRecuerdan:
    def __init__(self) -> None:
        self.retiradas: list[Vista] = []
        self.concedidas: list[tuple[Vista, Plazo, datetime]] = []

    async def usuario(self, *, negocio_id: UUID, usuario_id: UUID) -> dict[str, Any]:
        return {"usuario_id": usuario_id, "negocio_id": negocio_id}

    async def retirar(self, *, vista: Vista, **_: Any) -> int:
        self.retiradas.append(vista)
        return 1

    async def conceder(self, *, vista: Vista, plazo: Plazo, vence_en: datetime, **_: Any) -> UUID:
        self.concedidas.append((vista, plazo, vence_en))
        return uuid4()

    async def obtener(self, **_: Any) -> tuple[AccesoVista, ...]:
        if not self.concedidas:
            return ()
        vista, plazo, vence = self.concedidas[-1]
        return (AccesoVista(vista=vista, otorgado_en=AHORA, vence_en=vence, plazo=plazo),)

    async def historial(self, **_: Any) -> tuple[dict[str, Any], ...]:
        return ()

    async def usuarios(self, **_: Any) -> tuple[dict[str, Any], ...]:
        return ()


async def test_un_plazo_mas_corto_sustituye_al_anterior() -> None:
    accesos = AccesosQueRecuerdan()

    resultado = await conceder_acceso(
        ACTOR,
        usuario_id=USUARIO,
        vista_codigo="necesidades",
        plazo_codigo="7d",
        repositorio=accesos,
        cache=CacheMudo(),
        momento=AHORA,
    )

    assert accesos.retiradas == [Vista.NECESIDADES]
    assert accesos.concedidas[0][1] is Plazo.D7
    assert accesos.concedidas[0][2] == AHORA + timedelta(days=7)
    assert resultado.vence_en == AHORA + timedelta(days=7)
    assert resultado.tablero[0].plazo is Plazo.D7


class AccesosConFilas:
    def __init__(self, filas: tuple[AccesoVista, ...]) -> None:
        self.filas = filas

    async def obtener(self, **_: Any) -> tuple[AccesoVista, ...]:
        return self.filas

    async def conceder(self, **_: Any) -> UUID:
        return uuid4()

    async def retirar(self, **_: Any) -> int:
        return 0

    async def historial(self, **_: Any) -> tuple[dict[str, Any], ...]:
        return ()

    async def usuarios(self, **_: Any) -> tuple[dict[str, Any], ...]:
        return ()

    async def usuario(self, **_: Any) -> dict[str, Any] | None:
        return None


async def test_un_plazo_vencido_suspende_la_cuenta() -> None:
    vencido = AccesoVista(
        vista=Vista.NECESIDADES,
        otorgado_en=AHORA - timedelta(days=8),
        vence_en=AHORA - timedelta(days=1),
        plazo=Plazo.D7,
    )

    with pytest.raises(EmpresaSuspendida):
        await vistas_vigentes(
            negocio_id=NEGOCIO,
            usuario_id=USUARIO,
            repositorio=AccesosConFilas((vencido,)),
            cache=CacheMudo(),
            momento=AHORA,
        )


async def test_un_plazo_vigente_no_suspende_la_cuenta() -> None:
    vivo = AccesoVista(
        vista=Vista.NECESIDADES,
        otorgado_en=AHORA,
        vence_en=AHORA + timedelta(days=7),
        plazo=Plazo.D7,
    )

    vigentes = await vistas_vigentes(
        negocio_id=NEGOCIO,
        usuario_id=USUARIO,
        repositorio=AccesosConFilas((vivo,)),
        cache=CacheMudo(),
        momento=AHORA,
    )

    assert Vista.NECESIDADES in vigentes
