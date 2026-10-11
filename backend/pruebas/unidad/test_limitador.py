"""Pruebas del control de tasa: qué se reintenta y cuándo se rinde.

Existe por un fallo que dejaba necesidades sin CPC sin que nada lo dijera. El limitador se construye
con `reintentos=4` y su documentación promete «reintenta con espera creciente», pero el bucle de
`_solicitar` gastaba los reintentos **solo** en respuestas con un código reintentable —429 y los
5xx—: cualquier fallo de **red** devolvía `None` al primer intento.

No es un caso raro en la tanda de fichas: son cientos de peticiones seguidas por un túnel, donde
una conexión que se cae es lo normal y no la excepción. Cada ficha que se perdía así dejaba una
necesidad sin CPC hasta la vuelta siguiente.

Lo que se protege aquí son las dos mitades de ese contrato: que un fallo de red se reintente como
cualquier otro, y que cuando los intentos se agotan el resultado siga siendo `None` —nunca una
excepción—, porque de eso depende que el ciclo pueda acabar de forma parcial y avisarlo.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx

from contratacion.infraestructura.adaptadores.salida.fuentes.limitador import LimitadorTasa

Manejador = Callable[[httpx.Request], httpx.Response]

REINTENTOS = 3


class LimitadorDePrueba(LimitadorTasa):
    """Limitador con el transporte sustituido: no hay red, hay un manejador.

    Se cambia solo la fábrica del cliente, que es el único punto por el que entra la red. Todo el
    control de tasa —semáforo, intervalo, enfriamiento y el bucle de reintentos— es el de verdad,
    que es lo que se quiere probar. Las esperas se acortan para que la prueba no tarde.
    """

    def __init__(self, manejador: Manejador) -> None:
        super().__init__(
            max_concurrencia=1,
            intervalo_minimo=0.0,
            espera_base=0.001,
            reintentos=REINTENTOS,
        )
        self._manejador = manejador
        self.llamadas = 0

    def _obtener_cliente(self, tiempo_limite: float) -> httpx.AsyncClient:
        if self._cliente is None or self._cliente.is_closed:
            self._cliente = httpx.AsyncClient(
                transport=httpx.MockTransport(self._contar), timeout=tiempo_limite
            )
        return self._cliente

    def _contar(self, peticion: httpx.Request) -> httpx.Response:
        self.llamadas += 1
        return self._manejador(peticion)


async def test_un_fallo_de_red_se_reintenta_y_la_peticion_acaba_saliendo() -> None:
    """El fallo dominante de la salida por túnel no puede gastar la ficha al primer intento."""
    fallos = 0

    def manejador(peticion: httpx.Request) -> httpx.Response:
        nonlocal fallos
        fallos += 1
        if fallos == 1:
            raise httpx.ConnectError("la conexión se cayó")
        return httpx.Response(200, json={"data": [1]})

    limitador = LimitadorDePrueba(manejador)

    assert await limitador.solicitar_json("https://ejemplo/x") == {"data": [1]}
    assert limitador.llamadas == 2


async def test_cuando_la_red_no_vuelve_se_rinde_y_devuelve_none() -> None:
    """Agotados los intentos se devuelve `None`; el registro queda pendiente otra vez."""

    def manejador(peticion: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("la fuente no contesta")

    limitador = LimitadorDePrueba(manejador)

    assert await limitador.solicitar_json("https://ejemplo/x") is None
    assert limitador.llamadas == REINTENTOS


async def test_una_respuesta_reintentable_agota_los_intentos() -> None:
    """Un 5xx se reintenta, pero no para siempre."""

    def manejador(peticion: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    limitador = LimitadorDePrueba(manejador)

    assert await limitador.solicitar_json("https://ejemplo/x") is None
    assert limitador.llamadas == REINTENTOS


async def test_un_404_no_se_reintenta() -> None:
    """Reintentar un error que no lo es gastaría la cuota de todos para nada."""

    def manejador(peticion: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    limitador = LimitadorDePrueba(manejador)

    assert await limitador.solicitar_json("https://ejemplo/x") is None
    assert limitador.llamadas == 1
