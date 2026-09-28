"""Fábrica del caché.

Redis es la primera parada de toda lectura en el diseño final, pero **es opcional**: si no hay
`REDIS_URL` configurada, se usa una implementación nula y el sistema sigue funcionando leyendo de la
base de datos. Eso permite desarrollar sin Redis y conectar el almacén gestionado al desplegar.

Estados posibles, tal y como se informan en `/listo`:

| Estado | Significado |
|---|---|
| `ok` | Configurada y responde |
| `deshabilitada` | No hay `REDIS_URL`: es intencional, no un fallo |
| `error` | Configurada pero no responde: hay que revisarla |
"""

from __future__ import annotations

from contratacion.aplicacion.puertos.cache import Cache
from contratacion.infraestructura.adaptadores.salida.cache.nula import CacheNula
from contratacion.infraestructura.adaptadores.salida.cache.redis import CacheRedis
from contratacion.infraestructura.config.ajustes import obtener_ajustes

ESTADO_OK = "ok"
ESTADO_DESHABILITADA = "deshabilitada"
ESTADO_ERROR = "error"

_cache: Cache | None = None


def obtener_cache() -> Cache:
    """Devuelve el caché compartido, creándolo en la primera llamada."""
    global _cache
    if _cache is None:
        ajustes = obtener_ajustes()
        _cache = CacheRedis(ajustes.redis_url) if ajustes.cache_habilitada else CacheNula()
    return _cache


async def estado_cache() -> str:
    """Estado del caché para el informe de preparación del servicio."""
    if not obtener_ajustes().cache_habilitada:
        return ESTADO_DESHABILITADA
    return ESTADO_OK if await obtener_cache().ping() else ESTADO_ERROR


async def verificar_cache() -> bool:
    """`True` solo si el caché está configurado y responde.

    Ojo: devuelve `False` también cuando está deshabilitado, que es un estado válido. Para
    distinguir «deshabilitado» de «roto» hay que usar `estado_cache`.
    """
    return await estado_cache() == ESTADO_OK


async def cerrar_cache() -> None:
    """Cierra el cliente al apagar el proceso."""
    global _cache
    if _cache is not None:
        await _cache.cerrar()
    _cache = None
