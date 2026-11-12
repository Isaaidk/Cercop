"""Trabajo de CPU fuera del bucle de eventos, con un tope.

Leer un PDF, maquetar una proforma o armar un Word consume CPU de corrido. Hecho dentro de una
petición `async`, bloquea el bucle: mientras una persona espera su PDF, las demás peticiones del
mismo proceso —incluso las más ligeras— se quedan en cola. Con cientos de usuarios eso se nota como
«el sistema se congela».

`en_hilo` lo ejecuta en un hilo y limita cuántos corren a la vez. Sin el tope, quinientas peticiones
simultáneas lanzarían quinientos hilos peleando por los mismos núcleos y todas irían más lentas;
con el tope, las que sobran esperan su turno sin gastar CPU.
"""

from __future__ import annotations

import asyncio
import os
import threading
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

# Uno por núcleo, entre dos y ocho: el trabajo es de CPU, no de espera.
_SIMULTANEOS = max(2, min(8, (os.cpu_count() or 2)))
_TURNOS = asyncio.Semaphore(_SIMULTANEOS)


async def en_hilo[T](funcion: Callable[..., T], *args: Any) -> T:
    async with _TURNOS:
        return await asyncio.to_thread(funcion, *args)


class CacheLru:
    """Caché pequeña en memoria, segura entre hilos. La llave es el resumen del archivo."""

    def __init__(self, maximo: int) -> None:
        self._maximo = maximo
        self._datos: OrderedDict[str, Any] = OrderedDict()
        self._cerrojo = threading.Lock()

    def obtener(self, llave: str) -> Any | None:
        with self._cerrojo:
            valor = self._datos.get(llave)
            if valor is not None:
                self._datos.move_to_end(llave)
            return valor

    def guardar(self, llave: str, valor: Any) -> None:
        with self._cerrojo:
            self._datos[llave] = valor
            self._datos.move_to_end(llave)
            while len(self._datos) > self._maximo:
                self._datos.popitem(last=False)


class MemoLru[K, V](OrderedDict[K, V]):
    """Diccionario con tope: al pasarse, olvida lo **menos usado**, no todo de golpe.

    Sustituye al patrón `if len(memo) > N: memo.clear()` de las memorias en proceso. Vaciarlo todo
    de golpe es una ráfaga de fallos justo en hora punta: miles de personas que estaban acertando
    pasan a pedir a la base (o al servicio ajeno) a la vez. Con LRU se va solo la entrada más vieja.

    Es para el bucle de eventos (un solo hilo): no lleva cerrojo. Para memorias que se tocan desde
    hilos está `CacheLru`. Las llaves de lo que es de una empresa deben llevar su `negocio_id`;
    estas memorias guardan datos **públicos** (fichas del portal, historial OCDS, vistas previas).
    """

    def __init__(self, maximo: int) -> None:
        super().__init__()
        self._maximo = max(1, maximo)

    def __getitem__(self, llave: K) -> V:
        valor = super().__getitem__(llave)
        self.move_to_end(llave)
        return valor

    def get(self, llave: K, defecto: V | None = None) -> V | None:  # type: ignore[override]
        if llave in self:
            return self[llave]
        return defecto

    def __setitem__(self, llave: K, valor: V) -> None:
        super().__setitem__(llave, valor)
        self.move_to_end(llave)
        while len(self) > self._maximo:
            self.popitem(last=False)
