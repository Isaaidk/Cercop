"""Estado del portal de compras públicas: pausa por mantenimiento y tope de peticiones por hora.

Por qué existe
--------------
El 2026-11-16 el portal pasó el día entero en «Ventana de Mantenimiento». Durante el mantenimiento
**no responde con un error**: cualquier dirección redirige (302) a `app/webroot/compras/index.php`,
que contesta 200 con un HTML de aviso. Para el worker eso parecía una respuesta buena:

- la ficha de cada necesidad se «leía» como una página sin tabla de CPC, se guardaba como *leída y
  sin ítems* y ya no se volvía a pedir nunca (el CPC de esas necesidades se perdía);
- la tanda de fichas seguía a una petición por segundo —1.138 en hora y media, cada una doble por la
  redirección— contra un portal en mantenimiento, desde la IP de la salida de Ecuador, que es la que
  hay que cuidar para que no la bloqueen;
- un TDR pedido en ese rato se «bajaba» como la página de aviso.

Este módulo es la única fuente de verdad del proceso sobre «¿se puede hablar con el portal ahora?»:

1. **Pausa por mantenimiento**: en cuanto una respuesta es la página de mantenimiento, todo el
   tráfico al portal se detiene `PAUSA_MANTENIMIENTO_SEG` y quien pregunta recibe «no» al instante,
   sin petición. Pasado el plazo, la primera petición hace de sonda: si sigue en mantenimiento, otra
   pausa.
2. **Tope por hora**: como cinturón de seguridad, nunca más de `max_por_hora` peticiones en una
   ventana deslizante de una hora, pase lo que pase con los intervalos y presupuestos de arriba.

Vive en la memoria del proceso. Toda la conversación con el portal sale del worker, que es un solo
proceso, así que no hace falta compartirlo por Redis.
"""

from __future__ import annotations

import logging
import os
import time
from collections import deque
from urllib.parse import urlsplit

registro = logging.getLogger(__name__)

PAUSA_MANTENIMIENTO_SEG = 15 * 60.0
# Ritmo normal medido: el listado cada 150 s (24/h) más las fichas nuevas; el relleno del histórico
# llega a 300 fichas por ciclo de 15 min. 1.200/h deja pasar eso y corta cualquier desboque.
MAX_POR_HORA = 1200
VENTANA_SEG = 3600.0

RUTA_MANTENIMIENTO = "/app/webroot/compras/index.php"
MARCA_MANTENIMIENTO = "ventana de mantenimiento"


def es_ruta_mantenimiento(url: object) -> bool:
    """¿Esta dirección es la página a la que el portal redirige cuando está en mantenimiento?"""
    try:
        ruta = urlsplit(str(url)).path.lower()
    except ValueError:
        return False
    return ruta.endswith(RUTA_MANTENIMIENTO)


def es_aviso_mantenimiento(cuerpo: str | bytes | None) -> bool:
    """¿El cuerpo es el aviso de mantenimiento? Solo mira el principio (el aviso es corto)."""
    if not cuerpo:
        return False
    if isinstance(cuerpo, bytes):
        cuerpo = cuerpo[:20_000].decode("utf-8", errors="ignore")
    return MARCA_MANTENIMIENTO in cuerpo[:20_000].lower()


class EstadoPortal:
    """Pausa y tope de peticiones de un proceso. Ver el docstring del módulo."""

    def __init__(
        self,
        *,
        max_por_hora: int = MAX_POR_HORA,
        pausa_seg: float = PAUSA_MANTENIMIENTO_SEG,
    ) -> None:
        self.max_por_hora = max_por_hora
        self.pausa_seg = pausa_seg
        self._pausa_hasta = 0.0
        self._motivo = ""
        self._marcas: deque[float] = deque()
        self._avisado_tope = 0.0

    def segundos_de_pausa(self, momento: float | None = None) -> float:
        momento = time.monotonic() if momento is None else momento
        return max(0.0, self._pausa_hasta - momento)

    def en_pausa(self) -> bool:
        return self.segundos_de_pausa() > 0

    def pausar(self, motivo: str, segundos: float | None = None) -> None:
        """Detiene el tráfico al portal. Solo avisa en el registro al entrar en la pausa."""
        momento = time.monotonic()
        ya_estaba = self.segundos_de_pausa(momento) > 0
        self._pausa_hasta = max(self._pausa_hasta, momento + (segundos or self.pausa_seg))
        self._motivo = motivo
        if not ya_estaba:
            registro.warning(
                "Portal de compras públicas en pausa %.0f min: %s. No se le hará ninguna "
                "petición hasta entonces.",
                (segundos or self.pausa_seg) / 60,
                motivo,
            )

    def permitir(self, etiqueta: str = "") -> bool:
        """¿Puede salir una petición ahora? Si la respuesta es sí, la cuenta para el tope."""
        momento = time.monotonic()
        if self.segundos_de_pausa(momento) > 0:
            return False
        while self._marcas and momento - self._marcas[0] > VENTANA_SEG:
            self._marcas.popleft()
        if len(self._marcas) >= self.max_por_hora:
            if momento - self._avisado_tope > VENTANA_SEG / 4:
                self._avisado_tope = momento
                registro.warning(
                    "Tope de %s peticiones/hora al portal alcanzado (%s); se espera a que se "
                    "libere la ventana.",
                    self.max_por_hora,
                    etiqueta or "sin etiqueta",
                )
            return False
        self._marcas.append(momento)
        return True

    def estado(self) -> dict[str, object]:
        momento = time.monotonic()
        while self._marcas and momento - self._marcas[0] > VENTANA_SEG:
            self._marcas.popleft()
        return {
            "en_pausa": self.segundos_de_pausa(momento) > 0,
            "pausa_restante_seg": round(self.segundos_de_pausa(momento)),
            "motivo": self._motivo if self.segundos_de_pausa(momento) > 0 else "",
            "peticiones_ultima_hora": len(self._marcas),
            "tope_por_hora": self.max_por_hora,
        }


def _tope_configurado() -> int:
    try:
        return max(1, int(os.getenv("PORTAL_MAX_PETICIONES_HORA", "") or MAX_POR_HORA))
    except ValueError:
        return MAX_POR_HORA


_ESTADO = EstadoPortal(max_por_hora=_tope_configurado())


def estado_portal() -> EstadoPortal:
    """El estado compartido del proceso."""
    return _ESTADO
