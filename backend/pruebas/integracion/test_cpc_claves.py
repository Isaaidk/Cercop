"""Pruebas de la lista de términos de CPC contra la base real.

Lo importante aquí es el **aislamiento**, y se comprueba con dos negocios que guardan el mismo
término: si la consulta no filtrara por empresa, cada uno vería la lista del otro —y en este
despliegue no lo taparía la política de RLS, porque el rol de la aplicación se salta las políticas
  (`rolbypassrls`)—. Una lista de vigilancia revela en qué está trabajando una empresa, así que este
es el caso que no puede fallar.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import NamedTuple

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from contratacion.dominio.palabras import normalizar_termino
from contratacion.infraestructura.adaptadores.salida.bd.cpc import RepositorioCpcBd
from contratacion.infraestructura.adaptadores.salida.bd.sesion import normalizar_url_bd
from contratacion.infraestructura.config.ajustes import obtener_ajustes

pytestmark = pytest.mark.skipif(
    os.getenv("PRUEBAS_INTEGRACION") != "1",
    reason="Requiere una base real: ejecutar con PRUEBAS_INTEGRACION=1",
)

AHORA = datetime.now(UTC)


class Escenario(NamedTuple):
    motor: AsyncEngine
    negocio_id: uuid.UUID
    otro_negocio_id: uuid.UUID
    usuario_id: uuid.UUID


@pytest.fixture
async def escenario() -> AsyncIterator[Escenario]:
    """Dos negocios. El segundo existe para poder comprobar que no se ven entre ellos."""
    ajustes = obtener_ajustes()
    motor = create_async_engine(
        normalizar_url_bd(ajustes.database_url).render_as_string(hide_password=False),
        pool_pre_ping=True,
    )
    negocio_id, otro_negocio_id = uuid.uuid4(), uuid.uuid4()
    usuario_id = uuid.uuid4()

    async with motor.begin() as conexion:
        for negocio, nombre in ((negocio_id, "CPC A"), (otro_negocio_id, "CPC B")):
            await conexion.execute(
                text("SELECT set_config('app.negocio_id', :valor, true)"),
                {"valor": str(negocio)},
            )
            await conexion.execute(
                text("INSERT INTO negocio (id, nombre, estado) VALUES (:id, :nombre, 'activo')"),
                {"id": str(negocio), "nombre": nombre},
            )
            await conexion.execute(
                text(
                    "INSERT INTO usuario (id, negocio_id, email, hash_password, nombre, rol, "
                    "estado) VALUES (:id, :negocio, :email, 'x', 'Ana', 'admin_negocio', 'activo')"
                ),
                {
                    "id": str(usuario_id if negocio == negocio_id else uuid.uuid4()),
                    "negocio": str(negocio),
                    "email": f"cpc-{negocio.hex[:12]}@prueba.ec",
                },
            )

    try:
        yield Escenario(motor, negocio_id, otro_negocio_id, usuario_id)
    finally:
        async with motor.begin() as conexion:
            for negocio in (negocio_id, otro_negocio_id):
                await conexion.execute(
                    text("SELECT set_config('app.negocio_id', :valor, true)"),
                    {"valor": str(negocio)},
                )
                # `cpc_clave` cae con `ON DELETE CASCADE`, así que basta con borrar el negocio.
                await conexion.execute(
                    text("DELETE FROM negocio WHERE id = :id"), {"id": str(negocio)}
                )
        await motor.dispose()


async def _guardar(escenario: Escenario, negocio: uuid.UUID, texto: str) -> bool:
    return await RepositorioCpcBd(escenario.motor).agregar(
        negocio_id=negocio,
        texto=texto,
        texto_normalizado=normalizar_termino(texto),
        creado_por=escenario.usuario_id if negocio == escenario.negocio_id else None,
        momento=AHORA,
    )


async def test_guardar_y_listar(escenario: Escenario) -> None:
    repositorio = RepositorioCpcBd(escenario.motor)

    assert await _guardar(escenario, escenario.negocio_id, "LAVADO Y ENGRASADO DE AUTOMOTORES")

    claves = await repositorio.listar(negocio_id=escenario.negocio_id)
    assert [clave.texto for clave in claves] == ["LAVADO Y ENGRASADO DE AUTOMOTORES"]


async def test_el_texto_se_guarda_tal_como_se_escribio(escenario: Escenario) -> None:
    """La ficha enseña lo que la persona reconoce, no el término normalizado de la búsqueda."""
    repositorio = RepositorioCpcBd(escenario.motor)

    await _guardar(escenario, escenario.negocio_id, "Gestión")

    claves = await repositorio.listar(negocio_id=escenario.negocio_id)
    assert claves[0].texto == "Gestión"


async def test_guardar_dos_veces_deja_una_sola_fila(escenario: Escenario) -> None:
    repositorio = RepositorioCpcBd(escenario.motor)

    assert await _guardar(escenario, escenario.negocio_id, "lavado") is True
    assert await _guardar(escenario, escenario.negocio_id, "LAVADO") is False

    assert len(await repositorio.listar(negocio_id=escenario.negocio_id)) == 1


async def test_dos_negocios_no_ven_la_lista_del_otro(escenario: Escenario) -> None:
    """El caso que no puede fallar: la misma consulta sin filtro devolvería la lista de todos."""
    repositorio = RepositorioCpcBd(escenario.motor)

    await _guardar(escenario, escenario.negocio_id, "lavado")
    await _guardar(escenario, escenario.otro_negocio_id, "lavado")

    mio = await repositorio.listar(negocio_id=escenario.negocio_id)
    suyo = await repositorio.listar(negocio_id=escenario.otro_negocio_id)

    assert len(mio) == 1
    assert len(suyo) == 1
    # Y quitar el mío no toca el suyo, aunque el término sea idéntico.
    await repositorio.quitar(negocio_id=escenario.negocio_id, texto_normalizado="lavado")
    assert await repositorio.listar(negocio_id=escenario.negocio_id) == ()
    assert len(await repositorio.listar(negocio_id=escenario.otro_negocio_id)) == 1


async def test_quitar_y_vaciar(escenario: Escenario) -> None:
    repositorio = RepositorioCpcBd(escenario.motor)
    await _guardar(escenario, escenario.negocio_id, "lavado")
    await _guardar(escenario, escenario.negocio_id, "aseo")

    assert await repositorio.quitar(negocio_id=escenario.negocio_id, texto_normalizado="lavado")
    assert [clave.texto for clave in await repositorio.listar(negocio_id=escenario.negocio_id)] == [
        "aseo"
    ]

    assert await repositorio.limpiar(negocio_id=escenario.negocio_id) == 1
    assert await repositorio.listar(negocio_id=escenario.negocio_id) == ()


async def test_quitar_lo_que_no_esta_no_falla(escenario: Escenario) -> None:
    repositorio = RepositorioCpcBd(escenario.motor)

    assert await repositorio.quitar(negocio_id=escenario.negocio_id, texto_normalizado="nada") is (
        False
    )
    assert await repositorio.limpiar(negocio_id=escenario.negocio_id) == 0
