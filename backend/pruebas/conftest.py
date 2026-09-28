"""Configuración común de las pruebas.

Fija variables de entorno válidas **antes** de que las pruebas importen la configuración, para que
la suite no dependa de un archivo `.env` real ni de credenciales de desarrollo.

Dos advertencias que conviene tener presentes:

1. Las **variables de entorno tienen prioridad sobre el archivo `.env`**. Por eso los valores
   ficticios de la base de datos solo se inyectan fuera del modo integración: si se inyectaran
   siempre, taparían la configuración real y las pruebas de integración fallarían sin motivo.
2. Se usa `setdefault`: si la máquina ya define una variable, esa gana.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest

from contratacion.infraestructura.adaptadores.salida.bd.sesion import cerrar_bd
from contratacion.infraestructura.adaptadores.salida.cache.cliente import cerrar_cache

PRUEBAS_INTEGRACION = os.getenv("PRUEBAS_INTEGRACION") == "1"

# Valores que nunca deben venir del entorno del desarrollador.
VALORES_DE_PRUEBA: dict[str, str] = {
    "ENTORNO": "dev",
    "JWT_SECRETO": "s" * 48,
    "CLAVE_CIFRADO_DATOS": "c" * 44,
    "CLAVE_PEPPER_HMAC": "p" * 44,
    "CORS_ORIGINS": "http://localhost:5173",
}

if not PRUEBAS_INTEGRACION:
    # Destinos ficticios: la suite de unidad no debe tocar nada real.
    VALORES_DE_PRUEBA["DATABASE_URL"] = "postgresql+asyncpg://prueba:prueba@127.0.0.1:5432/prueba"
    VALORES_DE_PRUEBA["REDIS_URL"] = "redis://127.0.0.1:6379/15"

for _clave, _valor in VALORES_DE_PRUEBA.items():
    os.environ.setdefault(_clave, _valor)


@pytest.fixture(autouse=True)
async def liberar_dependencias() -> AsyncIterator[None]:
    """Libera los recursos compartidos después de cada prueba.

    El motor de base de datos y el cliente de caché son globales al módulo, y una conexión creada
    en un bucle de eventos no se puede reutilizar en otro. Sin esta limpieza, la segunda prueba que
    toca la base falla con «Event loop is closed».

    Es una limitación conocida del diseño actual: en la fase 1 el motor pasará a crearse y cerrarse
    con el ciclo de vida de la aplicación, en lugar de con una variable global perezosa.
    """
    yield
    await cerrar_cache()
    await cerrar_bd()
