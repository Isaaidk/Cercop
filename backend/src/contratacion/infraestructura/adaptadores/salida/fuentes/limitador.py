"""Control de tasa hacia la fuente oficial.

Portado del sistema anterior, donde está **verificado en producción**: el SERCOP responde 429 ante
ráfagas, con un `Retry-After` que puede llegar a 21 segundos. Tres mecanismos bastan para no quedar
bloqueados:

1. **Semáforo** que limita cuántas peticiones hay en vuelo a la vez.
2. **Intervalo mínimo** entre peticiones consecutivas.
3. **Enfriamiento global** tras un 429: si la fuente pide espera, espera todo el proceso, no solo
   la petición que falló.

Además reintenta con espera creciente y respeta el `Retry-After` de la respuesta.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

registro = logging.getLogger(__name__)

CODIGOS_REINTENTABLES = frozenset({429, 500, 502, 503, 504})
MAX_CONCURRENCIA = 2
INTERVALO_MINIMO = 0.6
ESPERA_BASE = 1.5
MAX_ESPERA = 30.0
TIEMPO_LIMITE = 60.0


class LimitadorTasa:
    """Cliente HTTP compartido con control de tasa."""

    def __init__(
        self,
        *,
        max_concurrencia: int = MAX_CONCURRENCIA,
        intervalo_minimo: float = INTERVALO_MINIMO,
        espera_base: float = ESPERA_BASE,
        reintentos: int = 4,
        tiempo_limite: float = TIEMPO_LIMITE,
        cabeceras: dict[str, str] | None = None,
    ) -> None:
        self._semaforo = asyncio.Semaphore(max_concurrencia)
        self._cerrojo = asyncio.Lock()
        self._ultima_llamada = 0.0
        self._enfriar_hasta = 0.0
        self._intervalo_minimo = intervalo_minimo
        self._espera_base = espera_base
        self._reintentos = reintentos
        self._cabeceras = cabeceras or {}
        self._cliente: httpx.AsyncClient | None = None
        self.codigos_recibidos: list[int] = []

    def _obtener_cliente(self, tiempo_limite: float) -> httpx.AsyncClient:
        if self._cliente is None or self._cliente.is_closed:
            self._cliente = httpx.AsyncClient(
                timeout=tiempo_limite,
                headers=self._cabeceras,
                follow_redirects=True,
            )
        return self._cliente

    def _marcar_enfriamiento(self, segundos: float) -> None:
        """Suspende globalmente las llamadas: un 429 afecta a todo el proceso, no a una petición."""
        self._enfriar_hasta = max(self._enfriar_hasta, time.monotonic() + segundos)

    async def _esperar_turno(self) -> None:
        """Serializa y espacia las peticiones consecutivas."""
        async with self._cerrojo:
            momento = time.monotonic()
            if self._enfriar_hasta > momento:
                await asyncio.sleep(self._enfriar_hasta - momento)
                momento = time.monotonic()
            espera = self._intervalo_minimo - (momento - self._ultima_llamada)
            if espera > 0:
                await asyncio.sleep(espera)
            self._ultima_llamada = time.monotonic()

    def _espera_sugerida(self, respuesta: httpx.Response, intento: int) -> float:
        cabecera = respuesta.headers.get("Retry-After")
        if cabecera:
            try:
                return max(1.0, min(float(cabecera), MAX_ESPERA))
            except ValueError:
                pass
        factor: float = 2.0 ** (intento - 1)
        espera: float = min(self._espera_base * factor, MAX_ESPERA)
        return espera

    async def solicitar_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        *,
        etiqueta: str = "",
        tiempo_limite: float = TIEMPO_LIMITE,
    ) -> dict[str, Any] | None:
        """GET con reintentos y control de tasa.

        Devuelve el JSON, o `None` si se agotaron los intentos. El llamador decide cómo informar del
        fallo; aquí nunca se lanza excepción por un problema de la fuente, porque la ingesta debe
        poder terminar de forma parcial y avisar.
        """
        cliente = self._obtener_cliente(tiempo_limite)
        async with self._semaforo:
            for intento in range(1, self._reintentos + 1):
                await self._esperar_turno()
                try:
                    respuesta = await cliente.get(url, params=params)
                    self.codigos_recibidos.append(respuesta.status_code)
                    respuesta.raise_for_status()
                    datos = respuesta.json()
                    return datos if isinstance(datos, dict) else {"data": datos}
                except httpx.HTTPStatusError as exc:
                    codigo = exc.response.status_code
                    self.codigos_recibidos.append(codigo)
                    if codigo not in CODIGOS_REINTENTABLES or intento == self._reintentos:
                        registro.error("La fuente respondió %s (%s)", codigo, etiqueta)
                        return None
                    espera = self._espera_sugerida(exc.response, intento)
                    if codigo == 429:
                        self._marcar_enfriamiento(espera)
                    registro.warning(
                        "La fuente respondió %s en %s; reintento en %.1fs (%s/%s)",
                        codigo,
                        etiqueta or url,
                        espera,
                        intento,
                        self._reintentos,
                    )
                    await asyncio.sleep(espera)
                except Exception as exc:  # noqa: BLE001 - un fallo de red no debe tumbar la ingesta
                    registro.error("Error consultando la fuente (%s): %s", etiqueta, exc)
                    return None
        return None

    async def cerrar(self) -> None:
        if self._cliente is not None and not self._cliente.is_closed:
            await self._cliente.aclose()
        self._cliente = None
