"""Entorno de Alembic.

Las migraciones se escriben **a mano**, no con autogeneración: el esquema usa particionado
declarativo y políticas de Row Level Security, que la autogeneración no cubre, y una migración
autogenerada contra una base gestionada (Supabase) podría proponer cambios destructivos sobre
objetos ajenos al proyecto.

`target_metadata` se deja en `None` a propósito por el mismo motivo.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from contratacion.infraestructura.adaptadores.salida.bd.sesion import normalizar_url_bd
from contratacion.infraestructura.config.ajustes import obtener_ajustes

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def _url_de_conexion() -> str:
    """URL resuelta desde la configuración de la aplicación (una sola fuente de verdad)."""
    url = normalizar_url_bd(obtener_ajustes().database_url)
    return url.render_as_string(hide_password=False)


def run_migrations_offline() -> None:
    """Genera el SQL sin conectarse (útil para revisar antes de aplicar)."""
    context.configure(
        url=_url_de_conexion(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _aplicar(conexion: Connection) -> None:
    context.configure(connection=conexion, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _run_online() -> None:
    motor = create_async_engine(_url_de_conexion(), pool_pre_ping=True)
    try:
        async with motor.connect() as conexion:
            await conexion.run_sync(_aplicar)
    finally:
        await motor.dispose()


def run_migrations_online() -> None:
    asyncio.run(_run_online())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
