"""Las alertas del worker con el rol de aplicación real (sin superusuario y sin `BYPASSRLS`).

Regresión de la auditoría de seguridad (docs/38-auditoria-seguridad.md). `marcar_revisada` se
ejecutaba sin contexto de empresa y solo funcionaba porque el rol de la base se salta RLS (riesgo
R-05). Con el rol correcto el `UPDATE` no tocaba ninguna fila y el worker volvía a revisar la misma
alerta en cada vuelta. Aquí se comprueba con el rol que se usará en producción:

- con el contexto de su empresa, la alerta queda marcada;
- con el contexto de **otra** empresa, no se toca (aislamiento);
- sin contexto, RLS no deja escribir nada, que es por lo que había que corregirlo.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import NamedTuple

import pytest
from pruebas.integracion.test_aislamiento_negocios import (
    CLAVE_ROL,
    _asegurar_rol,
    _url_admin,
    _url_como_rol,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from contratacion.infraestructura.adaptadores.salida.bd.radar import RepositorioRadar

pytestmark = pytest.mark.skipif(
    os.getenv("PRUEBAS_INTEGRACION") != "1",
    reason="Requiere una base real: ejecutar con PRUEBAS_INTEGRACION=1",
)


class Escenario(NamedTuple):
    negocio: uuid.UUID
    otro: uuid.UUID
    alerta: uuid.UUID
    rol: AsyncEngine
    admin: AsyncEngine


async def _con_contexto(conexion: object, negocio: uuid.UUID) -> None:
    await conexion.execute(  # type: ignore[attr-defined]
        text("SELECT set_config('app.negocio_id', :valor, true)"), {"valor": str(negocio)}
    )


@pytest.fixture
async def escenario() -> AsyncIterator[Escenario]:
    admin = create_async_engine(_url_admin(), pool_pre_ping=True)
    negocio, otro, alerta = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with admin.begin() as conexion:
        await _asegurar_rol(conexion, CLAVE_ROL)
        for identificador in (negocio, otro):
            await _con_contexto(conexion, identificador)
            await conexion.execute(
                text("INSERT INTO negocio (id, nombre, estado) VALUES (:id, 'Alertas', 'activo')"),
                {"id": identificador},
            )
        await _con_contexto(conexion, negocio)
        usuario = (
            await conexion.execute(
                text(
                    "INSERT INTO usuario (negocio_id, email, hash_password, estado, rol) "
                    "VALUES (:negocio, :email, 'x', 'activo', 'usuario') RETURNING id"
                ),
                {"negocio": negocio, "email": f"alertas-{negocio}@seguridad.test"},
            )
        ).scalar_one()
        await conexion.execute(
            text(
                "INSERT INTO alerta (id, negocio_id, usuario_id, nombre) "
                "VALUES (:id, :negocio, :usuario, 'Regresión doc 38')"
            ),
            {"id": alerta, "negocio": negocio, "usuario": usuario},
        )
    rol = create_async_engine(_url_como_rol(CLAVE_ROL), pool_pre_ping=True)

    yield Escenario(negocio=negocio, otro=otro, alerta=alerta, rol=rol, admin=admin)

    await rol.dispose()
    async with admin.begin() as conexion:
        for identificador in (negocio, otro):
            await _con_contexto(conexion, identificador)
            await conexion.execute(
                text("DELETE FROM negocio WHERE id = :id"), {"id": identificador}
            )
    await admin.dispose()


async def _revisada(escenario: Escenario) -> datetime | None:
    async with escenario.admin.begin() as conexion:
        await _con_contexto(conexion, escenario.negocio)
        valor = (
            await conexion.execute(
                text("SELECT revisada_en FROM alerta WHERE id = :id"), {"id": escenario.alerta}
            )
        ).scalar_one()
    return valor  # type: ignore[no-any-return]


async def test_el_rol_de_prueba_no_se_salta_rls(escenario: Escenario) -> None:
    async with escenario.rol.connect() as conexion:
        fila = (
            await conexion.execute(
                text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
            )
        ).one()
    assert (bool(fila[0]), bool(fila[1])) == (False, False)


async def test_sin_contexto_rls_no_deja_marcar_la_alerta(escenario: Escenario) -> None:
    """Es el fallo que había: el `UPDATE` sin contexto no tocaba nada con el rol correcto."""
    await RepositorioRadar(escenario.rol).marcar_revisada(escenario.alerta, datetime.now(UTC))
    assert await _revisada(escenario) is None


async def test_con_el_contexto_de_otra_empresa_no_se_toca(escenario: Escenario) -> None:
    await RepositorioRadar(escenario.rol).marcar_revisada(
        escenario.alerta, datetime.now(UTC), negocio_id=escenario.otro
    )
    assert await _revisada(escenario) is None


async def test_con_el_contexto_de_su_empresa_queda_marcada(escenario: Escenario) -> None:
    momento = datetime.now(UTC)
    await RepositorioRadar(escenario.rol).marcar_revisada(
        escenario.alerta, momento, negocio_id=escenario.negocio
    )
    assert await _revisada(escenario) == momento
