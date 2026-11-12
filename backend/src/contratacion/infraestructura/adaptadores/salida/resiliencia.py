"""Cortacircuitos y compartimentos: que un servicio caído no arrastre al resto del API.

El problema que resuelve
------------------------
El API habla con servicios que no controla: la consulta de RUC del SRI, los datos abiertos del
SERCOP, el modelo de IA y el almacén (Redis). Cuando uno de ellos **deja de responder** —no cuando
falla rápido, que es inofensivo, sino cuando se queda callado— cada petición que lo necesita espera
su tiempo límite entero. Con quinientas personas usando el panel, esas esperas se acumulan: cada una
retiene una corrutina, a menudo una conexión de la base, y el proceso termina sin sitio para las
peticiones que no tienen nada que ver con el servicio caído. Así es como un SRI lento tumba la
búsqueda de contrataciones.

Tres piezas, cada una para una parte del problema:

- **Tiempo límite**: ninguna llamada espera indefinidamente. Lo pone cada adaptador en su cliente
  HTTP, y el cortacircuitos puede añadir un tope total a la operación (`limite_seg`), que es lo que
  acota los reintentos.
- **Cortacircuitos**: tras `umbral_fallos` fallos seguidos, el circuito se **abre** y durante
  `enfriamiento_seg` las llamadas se rechazan al instante con `ServicioNoDisponible` (un 503 con un
  mensaje que dice qué pasa y que basta con reintentar). Pasado el enfriamiento queda
  **semiabierto**: deja pasar **una** llamada de prueba; si sale bien se cierra, si no, vuelve a
  abrirse. Así el servicio caído deja de costar tiempo y, cuando vuelve, se nota solo.
- **Compartimento** (*bulkhead*): un tope de llamadas simultáneas por servicio. Un servicio lento
  puede ocupar, como mucho, sus propias ranuras; la petición que llega con el compartimento lleno
  espera `espera_turno_seg` y, si no hay sitio, se rechaza en lugar de hacer cola sin fin.

Qué cuenta como fallo
---------------------
Solo lo que dice «el servicio no está bien»: errores de red, tiempos agotados y respuestas 5xx o
429. Un 404, un dato mal formado o un `NoEncontrado` significan que el servicio **respondió**, y
cuentan como éxito: si contaran como fallo, diez personas escribiendo mal su RUC abrirían el
circuito para todas las demás. La comprobación recorre la cadena de causas (`raise … from error`),
porque los adaptadores traducen los errores de red a errores de dominio y la causa original es la
que informa.

Alcance
-------
El estado vive **en la memoria de cada proceso**, y es deliberado. Compartirlo entre procesos
exigiría justo un almacén externo —otro servicio que puede caerse—, y lo que se gana es poco: cada
proceso descubre la caída por su cuenta tras un puñado de fallos rápidos. El estado de todos los
circuitos del proceso se publica en `/listo` para poder vigilarlo.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from enum import StrEnum
from typing import Any

import httpx
from redis.exceptions import ConnectionError as RedisConexion
from redis.exceptions import TimeoutError as RedisTiempo

from contratacion.dominio.errores import ServicioNoDisponible

registro = logging.getLogger(__name__)

MENSAJE_OCUPADO = (
    "Hay demasiadas consultas en curso a este servicio. Vuelve a intentarlo en unos segundos."
)
# Profundidad máxima al recorrer la cadena de causas. Evita un bucle si alguna biblioteca encadena
# una excepción consigo misma, y cinco niveles cubren de sobra «dominio ← httpx ← socket».
_PROFUNDIDAD_CAUSAS = 5


class EstadoCircuito(StrEnum):
    CERRADO = "cerrado"
    ABIERTO = "abierto"
    SEMIABIERTO = "semiabierto"


class FalloDelServicio(Exception):
    """Marca un fallo del servicio que no llega como error de red.

    Un proveedor de IA saturado responde 429 o 503 **con una respuesta válida**: no hay excepción de
    red que encadenar. El adaptador la lanza como causa (`raise EstadoInvalido(...) from
    FalloDelServicio(...)`) para que el cortacircuitos la cuente sin tener que leer mensajes.
    """


def _un_fallo(error: BaseException) -> bool:
    if isinstance(error, ServicioNoDisponible):
        # Lo rechazó otro circuito (o este mismo): no dice nada nuevo sobre el servicio.
        return False
    if isinstance(error, httpx.HTTPStatusError):
        codigo = error.response.status_code
        return codigo >= 500 or codigo == 429
    return isinstance(
        error,
        (httpx.TransportError, RedisConexion, RedisTiempo, OSError, TimeoutError, FalloDelServicio),
    )


def es_fallo_de_servicio(error: BaseException) -> bool:
    """`True` si el error, o alguna de sus causas, dice que el servicio no está bien."""
    actual: BaseException | None = error
    for _ in range(_PROFUNDIDAD_CAUSAS):
        if actual is None:
            return False
        if _un_fallo(actual):
            return True
        actual = actual.__cause__
    return False


class Cortacircuitos:
    """Circuito de un servicio: estado, contador de fallos y compartimento de llamadas."""

    def __init__(
        self,
        nombre: str,
        *,
        mensaje: str,
        umbral_fallos: int = 5,
        enfriamiento_seg: float = 30.0,
        max_concurrencia: int | None = None,
        espera_turno_seg: float = 0.0,
        limite_seg: float | None = None,
        mensaje_ocupado: str = MENSAJE_OCUPADO,
        es_fallo: Callable[[BaseException], bool] = es_fallo_de_servicio,
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        if umbral_fallos < 1:
            raise ValueError("El umbral de fallos tiene que ser al menos 1.")
        self.nombre = nombre
        self._mensaje = mensaje
        self._mensaje_ocupado = mensaje_ocupado
        self._umbral = umbral_fallos
        self._enfriamiento = enfriamiento_seg
        self._max_concurrencia = max_concurrencia
        self._espera_turno = espera_turno_seg
        self._limite = limite_seg
        self._es_fallo = es_fallo
        self._reloj = reloj
        self._turnos = asyncio.Semaphore(max_concurrencia) if max_concurrencia else None

        self._abierto = False
        self._abierto_hasta = 0.0
        self._sonda_en_curso = False
        self._fallos_seguidos = 0
        self.en_vuelo = 0
        self.aperturas = 0
        self.rechazadas = 0

    # --- Estado ---------------------------------------------------------- #

    @property
    def estado(self) -> EstadoCircuito:
        if not self._abierto:
            return EstadoCircuito.CERRADO
        if self._reloj() < self._abierto_hasta:
            return EstadoCircuito.ABIERTO
        return EstadoCircuito.SEMIABIERTO

    def resumen(self) -> dict[str, Any]:
        """Lo que se publica en `/listo`: nada sensible, solo contadores."""
        return {
            "estado": str(self.estado),
            "fallos_seguidos": self._fallos_seguidos,
            "en_vuelo": self.en_vuelo,
            "max_concurrencia": self._max_concurrencia,
            "aperturas": self.aperturas,
            "rechazadas": self.rechazadas,
        }

    def registrar_exito(self) -> None:
        if self._abierto:
            registro.info("El servicio «%s» volvió a responder: circuito cerrado.", self.nombre)
        self._abierto = False
        self._fallos_seguidos = 0

    def registrar_fallo(self) -> None:
        self._fallos_seguidos += 1
        # En semiabierto basta un fallo: la llamada de prueba era la pregunta «¿ya volvió?», y la
        # respuesta es que no.
        if self._abierto or self._fallos_seguidos >= self._umbral:
            if not self._abierto or self.estado is EstadoCircuito.SEMIABIERTO:
                self.aperturas += 1
                registro.warning(
                    "El servicio «%s» no responde (%s fallos seguidos): circuito abierto %.0f s.",
                    self.nombre,
                    self._fallos_seguidos,
                    self._enfriamiento,
                )
            self._abierto = True
            self._abierto_hasta = self._reloj() + self._enfriamiento

    # --- Uso ------------------------------------------------------------- #

    def _admitir(self) -> bool:
        """Decide si la llamada pasa. Devuelve `True` si es la llamada de prueba del semiabierto."""
        estado = self.estado
        if estado is EstadoCircuito.CERRADO:
            return False
        if estado is EstadoCircuito.SEMIABIERTO and not self._sonda_en_curso:
            self._sonda_en_curso = True
            return True
        self.rechazadas += 1
        raise ServicioNoDisponible(self._mensaje)

    async def _ocupar_turno(self) -> None:
        if self._turnos is None:
            return
        try:
            if self._espera_turno > 0:
                await asyncio.wait_for(self._turnos.acquire(), self._espera_turno)
            elif self._turnos.locked():
                raise TimeoutError
            else:
                await self._turnos.acquire()
        except TimeoutError:
            self.rechazadas += 1
            raise ServicioNoDisponible(self._mensaje_ocupado) from None

    @asynccontextmanager
    async def proteger(self) -> AsyncIterator[None]:
        """Envuelve una llamada al servicio.

        Lanza `ServicioNoDisponible` **antes** de llamar si el circuito está abierto o el
        compartimento lleno, y anota el resultado de la llamada al salir. Los errores de la llamada
        se propagan tal cual: el adaptador sigue decidiendo cómo explicarlos.
        """
        sonda = self._admitir()
        try:
            await self._ocupar_turno()
        except BaseException:
            if sonda:
                self._sonda_en_curso = False
            raise
        self.en_vuelo += 1
        try:
            if self._limite is None:
                yield
            else:
                try:
                    async with asyncio.timeout(self._limite):
                        yield
                except TimeoutError as error:
                    # El tope total se agotó: el servicio está, como poco, demasiado lento.
                    self.registrar_fallo()
                    raise ServicioNoDisponible(self._mensaje) from error
        except ServicioNoDisponible:
            raise
        except asyncio.CancelledError:
            # Quien llamó se fue (el cliente cerró la conexión): no dice nada del servicio.
            raise
        except BaseException as error:
            if self._es_fallo(error):
                self.registrar_fallo()
            else:
                self.registrar_exito()
            raise
        else:
            self.registrar_exito()
        finally:
            self.en_vuelo -= 1
            if sonda:
                self._sonda_en_curso = False
            if self._turnos is not None:
                self._turnos.release()


# --- Registro de circuitos del proceso ------------------------------------ #

_CIRCUITOS: dict[str, Cortacircuitos] = {}


def circuito(nombre: str, **configuracion: Any) -> Cortacircuitos:
    """El circuito de un servicio, creado en la primera llamada.

    La configuración solo se usa al crearlo. Los adaptadores lo piden en cada llamada en vez de
    guardarlo, para que `reiniciar_circuitos` deje a todos con un circuito nuevo.
    """
    existente = _CIRCUITOS.get(nombre)
    if existente is None:
        existente = Cortacircuitos(nombre, **configuracion)
        _CIRCUITOS[nombre] = existente
    return existente


def estado_circuitos() -> dict[str, dict[str, Any]]:
    """Resumen de todos los circuitos que este proceso ha usado, para `/listo`."""
    return {nombre: c.resumen() for nombre, c in sorted(_CIRCUITOS.items())}


def reiniciar_circuitos() -> None:
    """Olvida todos los circuitos. Lo usan las pruebas: que una no herede los fallos de otra."""
    _CIRCUITOS.clear()
