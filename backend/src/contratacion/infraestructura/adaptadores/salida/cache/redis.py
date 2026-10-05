"""Implementación del puerto de caché sobre Redis.

Acepta la URI tal cual la entrega un proveedor gestionado: `rediss://` (con dos eses) implica TLS y
se respeta automáticamente, así que sirven tanto Redis local como Upstash, Redis Cloud o cualquier
otro servicio compatible.

Los fallos se registran y se propagan como excepción **solo** en las operaciones: el llamador decide
si degrada. `ping` nunca lanza, porque se usa para informar del estado del servicio.
"""

from __future__ import annotations

import logging

from redis.asyncio import Redis

registro = logging.getLogger(__name__)


class CacheRedis:
    """Caché respaldada por Redis."""

    def __init__(self, url: str) -> None:
        self._cliente: Redis = Redis.from_url(url, decode_responses=True)

    @property
    def habilitada(self) -> bool:
        return True

    @staticmethod
    def _texto(valor: object) -> str | None:
        if valor is None:
            return None
        # El cliente se crea con `decode_responses=True`, pero se contempla el caso de `bytes` para
        # no depender de esa opción.
        return valor.decode() if isinstance(valor, bytes) else str(valor)

    async def obtener(self, clave: str) -> str | None:
        return self._texto(await self._cliente.get(clave))

    async def obtener_renovando(self, clave: str, ttl_seg: int) -> str | None:
        # `GETEX` lee y reinicia el tiempo de vida en una sola operación, y **no crea la clave si no
        # existe**. Esa segunda mitad es la que importa: con un `SET` posterior a la lectura, un
        # cierre de sesión que ocurriera entre las dos operaciones quedaría deshecho.
        return self._texto(await self._cliente.getex(clave, ex=ttl_seg))

    async def guardar(self, clave: str, valor: str, ttl_seg: int) -> None:
        await self._cliente.set(clave, valor, ex=ttl_seg)

    async def eliminar(self, clave: str) -> None:
        await self._cliente.delete(clave)

    async def incrementar(self, clave: str) -> int:
        return int(await self._cliente.incr(clave))

    async def ping(self) -> bool:
        try:
            respuesta = await self._cliente.ping()
        except Exception:  # noqa: BLE001 - un fallo de caché nunca debe tumbar el servicio
            registro.warning("El caché configurado no responde", exc_info=False)
            return False
        return bool(respuesta)

    async def cerrar(self) -> None:
        await self._cliente.aclose()
