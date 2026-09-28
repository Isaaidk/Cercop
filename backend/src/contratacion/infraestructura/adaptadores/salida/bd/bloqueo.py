"""Bloqueo de exclusión mutua para la ingesta.

Un solo proceso puede ingestar una fuente a la vez. Sin esto, dos réplicas del `worker` harían el
mismo trabajo a la vez: peticiones duplicadas a la fuente oficial (que ya está limitada por tasa) y
condiciones de carrera al escribir.

Se usa un **bloqueo de asesoría de PostgreSQL** y no uno de Redis porque:

- El bloqueo se libera solo si el proceso muere: lo hace la propia conexión al caerse.
- Con un bloqueo en Redis habría que elegir un tiempo de vida y decidir qué pasa si la ingesta dura
  más de lo previsto, que es justo el caso de un ciclo con muchos términos.
- No añade una dependencia: la base de datos ya está.

El bloqueo es de sesión, así que la conexión que lo obtiene debe permanecer abierta durante todo el
ciclo.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from contratacion.infraestructura.adaptadores.salida.bd.sesion import obtener_motor


def clave_de_bloqueo(codigo: str) -> int:
    """Convierte el código de una fuente en la clave entera que espera PostgreSQL.

    Se toma la mitad del SHA-256 para que dos fuentes distintas no colisionen por casualidad.
    """
    digest = hashlib.sha256(f"ingesta:{codigo}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


@asynccontextmanager
async def bloqueo_de_ingesta(
    codigo: str, motor: AsyncEngine | None = None
) -> AsyncIterator[AsyncConnection | None]:
    """Cede una conexión con el bloqueo tomado, o `None` si otro proceso ya lo tiene.

    Uso:

        async with bloqueo_de_ingesta("NCO") as conexion:
            if conexion is None:
                return  # otra réplica está ingestando
            ...
    """
    clave = clave_de_bloqueo(codigo)
    motor_efectivo = motor or obtener_motor()

    async with motor_efectivo.connect() as conexion:
        obtenido: bool = bool(
            (
                await conexion.execute(
                    text("SELECT pg_try_advisory_lock(:clave)"), {"clave": clave}
                )
            ).scalar_one()
        )
        if not obtenido:
            yield None
            return
        try:
            yield conexion
        finally:
            await conexion.execute(text("SELECT pg_advisory_unlock(:clave)"), {"clave": clave})
