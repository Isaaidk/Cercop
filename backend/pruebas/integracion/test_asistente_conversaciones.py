"""Conversaciones del asistente contra la base real: privacidad por persona y topes de tamaño.

Una conversación es de una persona: un compañero de la misma empresa no la ve, ni otra empresa
aunque pase su identificador. Y la tabla no crece sin límite: los mensajes y las conversaciones
más antiguos se descartan al escribir, en la misma transacción.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from typing import NamedTuple

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from contratacion.dominio.errores import NoEncontrado
from contratacion.infraestructura.adaptadores.salida.bd.asistente import (
    RepositorioConversacionesBd,
)
from contratacion.infraestructura.adaptadores.salida.bd.sesion import normalizar_url_bd
from contratacion.infraestructura.config.ajustes import obtener_ajustes

pytestmark = pytest.mark.skipif(
    os.getenv("PRUEBAS_INTEGRACION") != "1",
    reason="Requiere una base real: ejecutar con PRUEBAS_INTEGRACION=1",
)


class Escenario(NamedTuple):
    motor: AsyncEngine
    negocio_id: uuid.UUID
    otro_negocio_id: uuid.UUID
    usuario_id: uuid.UUID
    companero_id: uuid.UUID


@pytest.fixture
async def escenario() -> AsyncIterator[Escenario]:
    ajustes = obtener_ajustes()
    motor = create_async_engine(
        normalizar_url_bd(ajustes.database_url).render_as_string(hide_password=False),
        pool_pre_ping=True,
    )
    negocio_id, otro_negocio_id = uuid.uuid4(), uuid.uuid4()
    usuario_id, companero_id, ajeno_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    usuarios = {negocio_id: (usuario_id, companero_id), otro_negocio_id: (ajeno_id,)}
    async with motor.begin() as conexion:
        for negocio, ids in usuarios.items():
            await conexion.execute(
                text("SELECT set_config('app.negocio_id', :valor, true)"),
                {"valor": str(negocio)},
            )
            await conexion.execute(
                text("INSERT INTO negocio (id, nombre, estado) VALUES (:id, 'Chat', 'activo')"),
                {"id": str(negocio)},
            )
            for usuario in ids:
                await conexion.execute(
                    text(
                        "INSERT INTO usuario (id, negocio_id, email, hash_password, nombre, rol, "
                        "estado) VALUES (:id, :negocio, :email, 'x', 'Ana', 'usuario', 'activo')"
                    ),
                    {
                        "id": str(usuario),
                        "negocio": str(negocio),
                        "email": f"chat-{usuario.hex[:12]}@prueba.ec",
                    },
                )
    try:
        yield Escenario(motor, negocio_id, otro_negocio_id, usuario_id, companero_id)
    finally:
        async with motor.begin() as conexion:
            for negocio in usuarios:
                await conexion.execute(
                    text("SELECT set_config('app.negocio_id', :valor, true)"),
                    {"valor": str(negocio)},
                )
                await conexion.execute(
                    text("DELETE FROM negocio WHERE id = :id"), {"id": str(negocio)}
                )
        await motor.dispose()


async def test_los_mensajes_se_recortan_y_quedan_en_orden(escenario: Escenario) -> None:
    repo = RepositorioConversacionesBd(escenario.motor, max_mensajes=3)
    conv = await repo.crear(
        negocio_id=escenario.negocio_id, usuario_id=escenario.usuario_id, titulo="Hola"
    )
    for numero in range(5):
        await repo.agregar_mensaje(
            negocio_id=escenario.negocio_id,
            usuario_id=escenario.usuario_id,
            conversacion_id=conv["id"],
            rol="usuario" if numero % 2 == 0 else "asistente",
            texto=f"m{numero}",
            tarjetas=[{"tipo": "datos", "titulo": "x", "campos": []}] if numero == 4 else [],
            sugerencias=["Mis alertas"],
        )
    mensajes = await repo.mensajes(
        negocio_id=escenario.negocio_id,
        usuario_id=escenario.usuario_id,
        conversacion_id=conv["id"],
    )
    assert [m["texto"] for m in mensajes] == ["m2", "m3", "m4"]
    assert mensajes[-1]["tarjetas"][0]["tipo"] == "datos"
    assert mensajes[-1]["sugerencias"] == ["Mis alertas"]


async def test_las_conversaciones_tienen_tope_por_persona(escenario: Escenario) -> None:
    repo = RepositorioConversacionesBd(escenario.motor, max_conversaciones=2)
    for titulo in ("a", "b", "c"):
        await repo.crear(
            negocio_id=escenario.negocio_id, usuario_id=escenario.usuario_id, titulo=titulo
        )
    lista = await repo.listar(negocio_id=escenario.negocio_id, usuario_id=escenario.usuario_id)
    assert [c["titulo"] for c in lista] == ["c", "b"]


async def test_una_conversacion_es_privada(escenario: Escenario) -> None:
    repo = RepositorioConversacionesBd(escenario.motor)
    conv = await repo.crear(
        negocio_id=escenario.negocio_id, usuario_id=escenario.usuario_id, titulo="Mía"
    )
    assert (
        await repo.obtener(
            negocio_id=escenario.negocio_id,
            usuario_id=escenario.companero_id,
            conversacion_id=conv["id"],
        )
        is None
    )
    assert (
        await repo.obtener(
            negocio_id=escenario.otro_negocio_id,
            usuario_id=escenario.usuario_id,
            conversacion_id=conv["id"],
        )
        is None
    )
    with pytest.raises(NoEncontrado):
        await repo.agregar_mensaje(
            negocio_id=escenario.negocio_id,
            usuario_id=escenario.companero_id,
            conversacion_id=conv["id"],
            rol="usuario",
            texto="intruso",
            tarjetas=[],
            sugerencias=[],
        )
    assert not await repo.borrar(
        negocio_id=escenario.negocio_id,
        usuario_id=escenario.companero_id,
        conversacion_id=conv["id"],
    )
    renombrada = await repo.renombrar(
        negocio_id=escenario.negocio_id,
        usuario_id=escenario.usuario_id,
        conversacion_id=conv["id"],
        titulo="Nuevo",
    )
    assert renombrada is not None and renombrada["titulo"] == "Nuevo"
    assert await repo.borrar(
        negocio_id=escenario.negocio_id,
        usuario_id=escenario.usuario_id,
        conversacion_id=conv["id"],
    )
