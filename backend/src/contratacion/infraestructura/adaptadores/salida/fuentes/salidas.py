"""Varias salidas HTTP hacia el portal, una por dispositivo Tailscale.

Un `tailscaled` solo puede usar un exit node. Cada proxy de esta lista es un proceso distinto
(`localhost:1055`, `localhost:1056`, …) y cada uno tiene su propio cliente y su propio tope de
peticiones. Si una salida falla tres veces seguidas, se enfría dos minutos y el reintento sale por
otra. Si no queda ninguna sana y había proxies configurados, no se sale directo: desde un
datacenter el portal descarta la conexión.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from contratacion.infraestructura.adaptadores.salida.fuentes.limitador import LimitadorTasa

ENFRIAMIENTO_SEG = 120.0
FALLOS_PARA_ENFRIAR = 3


@dataclass
class Salida:
    """Una salida y cuánto se confía en ella ahora mismo."""

    proxy_url: str | None
    limitador: LimitadorTasa
    en_vuelo: int = 0
    fallos: int = 0
    enfriamiento_hasta: float = 0.0

    def sana(self, momento: float | None = None) -> bool:
        return (momento if momento is not None else time.monotonic()) >= self.enfriamiento_hasta

    def anotar(self, ok: bool) -> None:
        if ok:
            self.fallos = 0
            return
        self.fallos += 1
        if self.fallos >= FALLOS_PARA_ENFRIAR:
            self.enfriamiento_hasta = time.monotonic() + ENFRIAMIENTO_SEG
            self.fallos = 0


@dataclass
class PoolSalidas:
    """Reparte las peticiones entre las salidas sanas, por menor carga."""

    salidas: list[Salida] = field(default_factory=list)
    # Sin proxies configurados se permite una salida directa. Es el desarrollo local. En producción
    # la lista trae los proxies y, si todos están fríos, no se inventa una salida directa.
    directo_si_vacio: bool = True

    @classmethod
    def desde_urls(
        cls,
        urls: list[str],
        *,
        cabeceras: dict[str, str] | None = None,
    ) -> PoolSalidas:
        if not urls:
            salida = Salida(None, LimitadorTasa(cabeceras=cabeceras))
            return cls(salidas=[salida], directo_si_vacio=True)
        salidas = [Salida(url, LimitadorTasa(cabeceras=cabeceras, proxy_url=url)) for url in urls]
        return cls(salidas=salidas, directo_si_vacio=False)

    def elegir(self) -> Salida | None:
        momento = time.monotonic()
        sanas = [salida for salida in self.salidas if salida.sana(momento)]
        if not sanas:
            return None
        return min(sanas, key=lambda salida: (salida.en_vuelo, salida.proxy_url or ""))

    def estado(self) -> list[dict[str, Any]]:
        momento = time.monotonic()
        return [
            {
                "proxy": salida.proxy_url or "directo",
                "sana": salida.sana(momento),
                "en_vuelo": salida.en_vuelo,
                "fallos": salida.fallos,
            }
            for salida in self.salidas
        ]

    async def solicitar_texto(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        *,
        etiqueta: str = "",
        tiempo_limite: float = 60.0,
    ) -> str | None:
        salida = self.elegir()
        if salida is None:
            return None
        salida.en_vuelo += 1
        try:
            texto = await salida.limitador.solicitar_texto(
                url, params, etiqueta=etiqueta, tiempo_limite=tiempo_limite
            )
            salida.anotar(texto is not None)
            return texto
        finally:
            salida.en_vuelo -= 1

    async def solicitar_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        *,
        etiqueta: str = "",
        tiempo_limite: float = 60.0,
    ) -> dict[str, Any] | None:
        salida = self.elegir()
        if salida is None:
            return None
        salida.en_vuelo += 1
        try:
            datos = await salida.limitador.solicitar_json(
                url, params, etiqueta=etiqueta, tiempo_limite=tiempo_limite
            )
            salida.anotar(datos is not None)
            return datos
        finally:
            salida.en_vuelo -= 1

    async def cerrar(self) -> None:
        for salida in self.salidas:
            await salida.limitador.cerrar()
