"""Pruebas de integración con dependencias reales.

Se saltan salvo que se indique lo contrario, porque necesitan Postgres y Redis levantados:

    $env:PRUEBAS_INTEGRACION = "1"; pytest pruebas/integracion
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from contratacion.infraestructura.adaptadores.salida.bd.sesion import verificar_bd
from contratacion.infraestructura.adaptadores.salida.cache.cliente import (
    ESTADO_DESHABILITADA,
    ESTADO_OK,
    estado_cache,
)
from contratacion.infraestructura.app import crear_app

pytestmark = pytest.mark.skipif(
    os.getenv("PRUEBAS_INTEGRACION") != "1",
    reason="Requiere Postgres y Redis reales: ejecutar con PRUEBAS_INTEGRACION=1",
)


async def test_postgres_responde() -> None:
    """Comprueba la conexión de `DATABASE_URL` (local o proveedor gestionado como Supabase)."""
    assert await verificar_bd() is True


async def test_cache_esta_operativa_o_deshabilitada() -> None:
    """El caché es opcional: no tenerlo configurado es un estado válido, no un fallo."""
    assert await estado_cache() in {ESTADO_OK, ESTADO_DESHABILITADA}


def test_listo_devuelve_200() -> None:
    """Con PostgreSQL disponible, el servicio está listo aunque no haya caché."""
    respuesta = TestClient(crear_app()).get("/listo")
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["dependencias"]["postgres"] == "ok"
