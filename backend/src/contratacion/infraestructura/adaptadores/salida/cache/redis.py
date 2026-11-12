"""Implementación del puerto de caché sobre Redis.

Acepta la URI tal cual la entrega un proveedor gestionado: `rediss://` (con dos eses) implica TLS y
se respeta automáticamente, así que sirven tanto Redis local como Upstash, Redis Cloud o cualquier
otro servicio compatible.

Los fallos se registran y se propagan como excepción **solo** en las operaciones: el llamador decide
si degrada. `ping` nunca lanza, porque se usa para informar del estado del servicio.

Tiempos límite y cortacircuitos
-------------------------------
El cliente de Redis, por defecto, **no tiene tiempo límite**: con el servidor inalcanzable, cada
comando espera lo que tarde el sistema operativo en rendirse con la conexión (de veinte segundos a
dos minutos). Como el almacén se consulta en casi todas las peticiones —la sesión viva, los
permisos, la generación del caché—, un Redis colgado convertía cada petición del API en una espera
larga aunque el código supiera degradar a la base. Por eso:

- conexión y lectura tienen un tope corto (`cache_timeout_seg`, dos segundos por defecto), y
- todas las operaciones pasan por el cortacircuitos `redis`: tras tres fallos seguidos, durante
  quince segundos ni se intenta y se lanza `ServicioNoDisponible` al instante. Los llamadores ya
  tratan cualquier excepción del caché como «sin caché» (y la sesión viva como «sin respuesta»,
  que pregunta a la base), así que el API sigue entero, solo más lento.
"""

from __future__ import annotations

import logging

from redis.asyncio import Redis

from contratacion.infraestructura.adaptadores.salida.resiliencia import Cortacircuitos, circuito

registro = logging.getLogger(__name__)

TIEMPO_LIMITE_SEG = 2.0


def circuito_redis() -> Cortacircuitos:
    """El circuito del almacén. Lo comparten el caché y la presencia: es el mismo servidor."""
    return circuito(
        "redis",
        mensaje=("El almacén de sesiones no responde ahora. Vuelve a intentarlo en unos minutos."),
        umbral_fallos=3,
        enfriamiento_seg=15.0,
    )


def cliente_redis(url: str, *, tiempo_limite_seg: float = TIEMPO_LIMITE_SEG) -> Redis:
    """Cliente con tiempos límite explícitos de conexión y de lectura."""
    return Redis.from_url(
        url,
        decode_responses=True,
        socket_connect_timeout=tiempo_limite_seg,
        socket_timeout=tiempo_limite_seg,
    )


class CacheRedis:
    """Caché respaldada por Redis."""

    def __init__(self, url: str, *, tiempo_limite_seg: float = TIEMPO_LIMITE_SEG) -> None:
        self._cliente: Redis = cliente_redis(url, tiempo_limite_seg=tiempo_limite_seg)

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
        async with circuito_redis().proteger():
            return self._texto(await self._cliente.get(clave))

    async def obtener_renovando(self, clave: str, ttl_seg: int) -> str | None:
        # `GETEX` lee y reinicia el tiempo de vida en una sola operación, y **no crea la clave si no
        # existe**. Esa segunda mitad es la que importa: con un `SET` posterior a la lectura, un
        # cierre de sesión que ocurriera entre las dos operaciones quedaría deshecho.
        async with circuito_redis().proteger():
            return self._texto(await self._cliente.getex(clave, ex=ttl_seg))

    async def guardar(self, clave: str, valor: str, ttl_seg: int) -> None:
        async with circuito_redis().proteger():
            await self._cliente.set(clave, valor, ex=ttl_seg)

    async def eliminar(self, clave: str) -> None:
        async with circuito_redis().proteger():
            await self._cliente.delete(clave)

    async def incrementar(self, clave: str) -> int:
        async with circuito_redis().proteger():
            return int(await self._cliente.incr(clave))

    async def ping(self) -> bool:
        try:
            # También por el circuito: con Redis caído, `/listo` responde al instante en vez de
            # esperar el tiempo límite en cada sondeo del balanceador.
            async with circuito_redis().proteger():
                respuesta = await self._cliente.ping()
        except Exception:  # noqa: BLE001 - un fallo de caché nunca debe tumbar el servicio
            registro.warning("El caché configurado no responde", exc_info=False)
            return False
        return bool(respuesta)

    async def cerrar(self) -> None:
        await self._cliente.aclose()
