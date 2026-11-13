"""Encolador: turnos acotados para el trabajo pesado, con fila de espera limitada y reparto justo.

El problema que resuelve
------------------------
Leer los anexos de un proceso, pedirle algo a la IA, maquetar un PDF o exportar a Excel cuestan
segundos de CPU o de espera a un servicio ajeno. Ya había topes de simultaneidad
(`hilos.en_hilo`, `ModeloIa`), pero **la fila detrás del tope no tenía fondo**: con una avalancha,
cientos de peticiones quedaban esperando sin límite, cada una con su memoria, su conexión abierta
y su usuario mirando una rueda girar. El sistema no se caía de golpe: se iba volviendo lento para
todos hasta que nada contestaba a tiempo.

Tres reglas
-----------
1. **Turnos**: como mucho `en_paralelo` trabajos de cada tipo a la vez (por proceso del API).
2. **Fila acotada**: como mucho `en_espera` esperando, y ninguno más de `espera_max_seg`. Lo que no
   cabe se rechaza **enseguida** con `Saturado` (HTTP 503 + `Retry-After`): el panel avisa
   «hay mucha demanda, vuelve a intentar en N s» en vez de colgarse. Rechazar pronto es lo que
   mantiene vivo el resto del sistema.
3. **Reparto justo**: una empresa no ocupa más de `por_empresa` turnos de un tipo. Si una empresa
   lanza veinte lecturas, las demás empresas siguen entrando.

Vive en memoria de cada proceso, como los demás topes: con 4 procesos el total es 4 veces lo
configurado, que es justo lo que se quiere (cada proceso protege su propia CPU y su propio pool).
"""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from contratacion.dominio.errores import Saturado


@dataclass
class Encolador:
    """Turnos de un tipo de trabajo. Ver el docstring del módulo."""

    nombre: str
    en_paralelo: int
    en_espera: int
    espera_max_seg: float
    por_empresa: int
    _activos: int = 0
    _esperando: int = 0
    _por_empresa: Counter[str] = field(default_factory=Counter)
    _cambio: asyncio.Condition | None = None

    def _condicion(self) -> asyncio.Condition:
        # Se crea dentro del bucle de eventos que la usa (no al importar el módulo).
        if self._cambio is None:
            self._cambio = asyncio.Condition()
        return self._cambio

    def estado(self) -> dict[str, int | str]:
        return {
            "tipo": self.nombre,
            "activos": self._activos,
            "esperando": self._esperando,
            "en_paralelo": self.en_paralelo,
            "en_espera": self.en_espera,
        }

    def _puede_entrar(self, empresa: str) -> bool:
        return self._activos < self.en_paralelo and self._por_empresa[empresa] < self.por_empresa

    def _rechazo(self) -> Saturado:
        return Saturado(
            "Hay mucha demanda en este momento. Vuelve a intentarlo en unos segundos; lo que ya "
            "tenías guardado no se pierde.",
            reintentar_en=max(5, int(self.espera_max_seg)),
        )

    @asynccontextmanager
    async def turno(self, empresa: str) -> AsyncIterator[None]:
        condicion = self._condicion()
        async with condicion:
            if not self._puede_entrar(empresa):
                if self._esperando >= self.en_espera:
                    raise self._rechazo()
                self._esperando += 1
                limite = time.monotonic() + self.espera_max_seg
                try:
                    while not self._puede_entrar(empresa):
                        restante = limite - time.monotonic()
                        if restante <= 0:
                            raise self._rechazo()
                        try:
                            await asyncio.wait_for(condicion.wait(), timeout=restante)
                        except TimeoutError:
                            if not self._puede_entrar(empresa):
                                raise self._rechazo() from None
                finally:
                    self._esperando -= 1
            self._activos += 1
            self._por_empresa[empresa] += 1
        try:
            yield
        finally:
            async with condicion:
                self._activos -= 1
                self._por_empresa[empresa] -= 1
                if self._por_empresa[empresa] <= 0:
                    del self._por_empresa[empresa]
                # Todos, no uno: el que despierte puede ser de una empresa que ya está en su tope, y
                # el que sí podría entrar se quedaría dormido.
                condicion.notify_all()


# Topes por proceso del API. Calculados para 4 procesos de 1 núcleo cada uno (docs/41 §8): la IA es
# sobre todo espera a un servicio ajeno (admite más en paralelo); leer anexos y maquetar son CPU.
ENCOLADORES: dict[str, Encolador] = {
    "ia": Encolador("ia", en_paralelo=6, en_espera=40, espera_max_seg=40, por_empresa=2),
    "lectura": Encolador("lectura", en_paralelo=3, en_espera=30, espera_max_seg=45, por_empresa=1),
    "documento": Encolador(
        "documento", en_paralelo=4, en_espera=40, espera_max_seg=30, por_empresa=2
    ),
    "exportacion": Encolador(
        "exportacion", en_paralelo=2, en_espera=10, espera_max_seg=60, por_empresa=1
    ),
}


def estado_de_los_encoladores() -> list[dict[str, int | str]]:
    return [encolador.estado() for encolador in ENCOLADORES.values()]
