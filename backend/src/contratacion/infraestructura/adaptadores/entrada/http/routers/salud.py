"""Salud y preparación del servicio.

`/salud` responde mientras el proceso viva; es lo que usa un orquestador para reiniciar el
contenedor. `/listo` comprueba las dependencias reales, para que el balanceador no envíe tráfico a
una instancia inservible.

El caché es **opcional**: no tenerlo configurado (`deshabilitada`) no impide que el servicio esté
listo, porque el sistema funciona leyendo de la base de datos. Solo PostgreSQL es imprescindible.

Y tenerlo configurado **pero caído** (`error`) tampoco lo impide, aunque antes sí. Era un fallo de
diseño con un efecto desproporcionado: al caer Redis, **todas** las réplicas respondían 503 a la
vez, el balanceador las sacaba de la rotación y el API entero dejaba de servir, cuando el código
sabe funcionar sin caché (las lecturas van a la base y la sesión viva se comprueba en PostgreSQL).
Ahora la respuesta dice `"degradado": true` y nombra lo que falla, para vigilarlo, pero sigue en
200: una dependencia opcional caída degrada el servicio, no lo apaga.

La respuesta incluye también el estado de los **cortacircuitos** del proceso (SRI, datos abiertos,
IA, Redis): cuáles están abiertos y cuántas llamadas se rechazaron. No afectan a `listo`, porque son
servicios externos de funciones concretas y el resto del API funciona sin ellos.

Ambas rutas son públicas y no exponen información sensible ni el inventario de endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from contratacion.infraestructura.adaptadores.salida.bd.sesion import estado_bd
from contratacion.infraestructura.adaptadores.salida.cache.cliente import estado_cache
from contratacion.infraestructura.adaptadores.salida.resiliencia import (
    EstadoCircuito,
    estado_circuitos,
)

router = APIRouter(tags=["Salud"])

NOMBRE_SERVICIO = "contratacion-api"
ESTADOS_ACEPTABLES_CACHE = {"ok", "deshabilitada"}


@router.get("/salud", summary="El proceso está vivo")
async def salud() -> dict[str, str]:
    """Comprobación trivial de vida, sin tocar dependencias."""
    return {"servicio": NOMBRE_SERVICIO, "estado": "ok"}


@router.get("/listo", summary="Las dependencias responden")
async def listo() -> JSONResponse:
    """Verifica PostgreSQL y el caché. Devuelve 503 solo si falla PostgreSQL, diciendo por qué.

    Cuando Postgres no responde se añade **el motivo**, en las palabras de este repositorio: «no se
    pudo resolver el nombre del servidor», «credenciales rechazadas». No es información sensible
    —nunca es el mensaje del controlador, así que no puede llevar la cadena de conexión— y es la
    diferencia entre saber qué arreglar y adivinar. La frase la elige `motivo_legible` de una lista
    cerrada, y en el peor caso es el nombre del tipo de excepción.
    """
    cache = await estado_cache()
    postgres_responde, motivo = await estado_bd()
    dependencias = {
        "postgres": "ok" if postgres_responde else "error",
        "cache": cache,
    }

    circuitos = estado_circuitos()
    abiertos = sorted(
        nombre
        for nombre, resumen in circuitos.items()
        if resumen["estado"] != EstadoCircuito.CERRADO
    )
    listo_para_servir = postgres_responde
    cuerpo: dict[str, object] = {
        "servicio": NOMBRE_SERVICIO,
        "listo": listo_para_servir,
        "degradado": cache not in ESTADOS_ACEPTABLES_CACHE or bool(abiertos),
        "dependencias": dependencias,
        "circuitos": circuitos,
    }
    if listo_para_servir:
        return JSONResponse(status_code=status.HTTP_200_OK, content=cuerpo)
    if not postgres_responde:
        cuerpo["motivo"] = motivo
    return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=cuerpo)
