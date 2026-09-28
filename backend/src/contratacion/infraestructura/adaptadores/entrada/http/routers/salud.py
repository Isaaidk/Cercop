"""Salud y preparación del servicio.

`/salud` responde mientras el proceso viva; es lo que usa un orquestador para reiniciar el
contenedor. `/listo` comprueba las dependencias reales, para que el balanceador no envíe tráfico a
una instancia inservible.

El caché es **opcional**: no tenerlo configurado (`deshabilitada`) no impide que el servicio esté
listo, porque el sistema funciona leyendo de la base de datos. Solo PostgreSQL es imprescindible.

Ambas rutas son públicas y no exponen información sensible ni el inventario de endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from contratacion.infraestructura.adaptadores.salida.bd.sesion import verificar_bd
from contratacion.infraestructura.adaptadores.salida.cache.cliente import estado_cache

router = APIRouter(tags=["Salud"])

NOMBRE_SERVICIO = "contratacion-api"
ESTADOS_ACEPTABLES_CACHE = {"ok", "deshabilitada"}


@router.get("/salud", summary="El proceso está vivo")
async def salud() -> dict[str, str]:
    """Comprobación trivial de vida, sin tocar dependencias."""
    return {"servicio": NOMBRE_SERVICIO, "estado": "ok"}


@router.get("/listo", summary="Las dependencias responden")
async def listo() -> JSONResponse:
    """Verifica PostgreSQL y el caché. Devuelve 503 indicando qué es lo que falla."""
    cache = await estado_cache()
    dependencias = {
        "postgres": "ok" if await verificar_bd() else "error",
        "cache": cache,
    }

    listo_para_servir = dependencias["postgres"] == "ok" and cache in ESTADOS_ACEPTABLES_CACHE
    cuerpo = {
        "servicio": NOMBRE_SERVICIO,
        "listo": listo_para_servir,
        "dependencias": dependencias,
    }
    if listo_para_servir:
        return JSONResponse(status_code=status.HTTP_200_OK, content=cuerpo)
    return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=cuerpo)
