"""Comprueba que las dependencias configuradas responden.

**Nunca imprime credenciales, cadenas de conexión ni datos.** Solo el estado de cada dependencia y,
si falla, una causa clasificada, para poder diagnosticar sin exponer secretos en la consola o en los
registros.

    cd backend
    .\\.venv\\Scripts\\python.exe scripts\\verificar_conexiones.py

Código de salida: 0 si todo responde, 1 si algo falla.
"""

from __future__ import annotations

import asyncio
import sys

from pydantic import ValidationError
from sqlalchemy import text

from contratacion.infraestructura.adaptadores.salida.bd.sesion import cerrar_bd, obtener_motor
from contratacion.infraestructura.adaptadores.salida.cache.cliente import (
    ESTADO_DESHABILITADA,
    ESTADO_OK,
    cerrar_cache,
    estado_cache,
)
from contratacion.infraestructura.config.ajustes import obtener_ajustes

CLAVES_CREDENCIALES = ("password authentication", "authentication failed", "invalid password")
CLAVES_HOST = ("getaddrinfo", "nodename nor servname", "name or service not known", "no such host")
CLAVES_TLS = ("ssl", "tls", "certificate")


def _clasificar(excepcion: Exception) -> str:
    """Devuelve una causa legible **sin** exponer el mensaje original ni la cadena de conexión."""
    nombre = type(excepcion).__name__
    mensaje = str(excepcion).lower()

    if any(clave in mensaje for clave in CLAVES_CREDENCIALES):
        return f"{nombre} · credenciales rechazadas"
    if any(clave in mensaje for clave in CLAVES_HOST):
        return f"{nombre} · host no resoluble (revisa la dirección del proyecto)"
    if any(clave in mensaje for clave in CLAVES_TLS):
        return f"{nombre} · problema de cifrado TLS (el servidor puede exigirlo)"
    if "timeout" in mensaje or "timed out" in mensaje:
        return f"{nombre} · tiempo de espera agotado (puerto inaccesible o red lenta)"
    if "refused" in mensaje:
        return f"{nombre} · conexión rechazada (puerto cerrado)"
    if "prepared statement" in mensaje:
        return f"{nombre} · el agrupador de conexiones no admite sentencias preparadas"
    if "controlador" in mensaje or ("not found" in mensaje and "module" in mensaje):
        return f"{nombre} · controlador de base de datos no soportado o ausente"
    return nombre


def _describir_errores_configuracion(excepcion: Exception) -> list[str]:
    """Nombres de campo y tipo de error, **sin** exponer los valores introducidos."""
    obtenedor = getattr(excepcion, "errors", None)
    if not callable(obtenedor):
        return ["no se pudo detallar el error"]

    descripciones: list[str] = []
    for error in obtenedor():
        ubicacion = ".".join(str(parte) for parte in error.get("loc", ()))
        descripciones.append(f"{ubicacion} · {error.get('type', 'desconocido')}")
    return descripciones


async def _probar_bd() -> tuple[bool, str]:
    try:
        async with obtener_motor().connect() as conexion:
            resultado = await conexion.execute(text("SELECT 1"))
            resultado.scalar_one()
    except Exception as exc:  # noqa: BLE001 - cualquier fallo aquí significa "no disponible"
        return False, _clasificar(exc)
    else:
        return True, "ok"
    finally:
        await cerrar_bd()


async def _probar_cache() -> tuple[bool, str]:
    try:
        estado = await estado_cache()
    except Exception as exc:  # noqa: BLE001 - cualquier fallo aquí significa "no disponible"
        return False, _clasificar(exc)
    else:
        if estado == ESTADO_DESHABILITADA:
            return True, "deshabilitada (sin REDIS_URL): el sistema funciona sin caché"
        return estado == ESTADO_OK, estado
    finally:
        await cerrar_cache()


async def main() -> int:
    try:
        obtener_ajustes()
    except ValidationError as exc:
        print("configuracion  FALLO   los valores del entorno no son válidos")
        for descripcion in _describir_errores_configuracion(exc):
            print(f"   - {descripcion}")
        return 1

    resultados = {
        "postgres": await _probar_bd(),
        "redis": await _probar_cache(),
    }

    for nombre, (responde, detalle) in resultados.items():
        etiqueta = "OK" if responde else "FALLO"
        sufijo = f"   {detalle}" if detalle != "ok" else ""
        print(f"{nombre:<10} {etiqueta}{sufijo}")

    return 0 if all(responde for responde, _ in resultados.values()) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
