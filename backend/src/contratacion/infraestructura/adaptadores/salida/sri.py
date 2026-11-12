"""Consulta pública de RUC del SRI, la misma que usa el portal «Consulta de RUC».

No es una API documentada ni con garantía de servicio: es el servicio REST que alimenta la página
pública del SRI. Por eso todo error de red o de forma de respuesta se traduce a un mensaje que
manda al usuario a llenar los datos a mano, y nada del resto del sistema depende de que responda.

Solo se consultan datos que el SRI publica para cualquiera: razón social, estado, régimen,
representante legal y establecimientos. No se guarda la respuesta cruda.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from contratacion.dominio.errores import EstadoInvalido, NoEncontrado
from contratacion.infraestructura.adaptadores.salida.resiliencia import Cortacircuitos, circuito

_BASE = "https://srienlinea.sri.gob.ec/sri-catastro-sujeto-servicio-internet/rest"
_TIMEOUT = httpx.Timeout(12.0, connect=6.0)
_ENCABEZADOS = {"Accept": "application/json", "User-Agent": "Mozilla/5.0 (CercoApp)"}
_NO_DISPONIBLE = (
    "No se pudo consultar el SRI en este momento. Inténtalo de nuevo en unos minutos o llena los "
    "datos a mano."
)

# El SRI se consulta al registrarse y al completar el perfil: pocas veces por persona, pero en
# ráfaga cuando muchas empresas se dan de alta a la vez. Ocho consultas en vuelo por proceso bastan
# para ese ritmo, y son el máximo de corrutinas que un SRI colgado puede retener aquí. Cinco fallos
# seguidos abren el circuito un minuto: durante ese minuto la respuesta es inmediata y manda a
# llenar a mano.
_CIRCUITO = {
    "mensaje": (
        "El SRI no responde ahora. Inténtalo en unos minutos o llena los datos a mano mientras "
        "tanto."
    ),
    "umbral_fallos": 5,
    "enfriamiento_seg": 60.0,
    "max_concurrencia": 8,
    "espera_turno_seg": 3.0,
    # Tope de la operación completa (dos consultas en paralelo de 12 s cada una como mucho).
    "limite_seg": 20.0,
}


def circuito_sri() -> Cortacircuitos:
    return circuito("sri", **_CIRCUITO)


class ConsultaSri:
    """Cliente de la consulta de RUC. Un cliente HTTP por consulta: se usa muy de vez en cuando.

    Cada consulta pasa por el cortacircuitos `sri` (ver `resiliencia.py`): con el SRI caído, la
    petición no espera doce segundos, se responde al instante con `ServicioNoDisponible`, que hereda
    de `EstadoInvalido` y por tanto sigue llevando al usuario a llenar los datos a mano.
    """

    def __init__(self, *, transporte: httpx.AsyncBaseTransport | None = None) -> None:
        self._transporte = transporte

    async def _pedir(self, cliente: httpx.AsyncClient, ruta: str, ruc: str) -> Any:
        try:
            respuesta = await cliente.get(f"{_BASE}/{ruta}", params={"ruc": ruc, "numeroRuc": ruc})
            respuesta.raise_for_status()
            return respuesta.json()
        except (httpx.HTTPError, ValueError) as error:
            raise EstadoInvalido(_NO_DISPONIBLE) from error

    async def consultar(self, ruc: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """El contribuyente y sus establecimientos. `NoEncontrado` si el SRI no lo conoce."""
        async with (
            circuito_sri().proteger(),
            httpx.AsyncClient(
                timeout=_TIMEOUT, headers=_ENCABEZADOS, transport=self._transporte
            ) as cliente,
        ):
            contribuyentes, establecimientos = await asyncio.gather(
                self._pedir(cliente, "ConsolidadoContribuyente/obtenerPorNumerosRuc", ruc),
                self._pedir(cliente, "Establecimiento/consultarPorNumeroRuc", ruc),
            )
        if not isinstance(contribuyentes, list) or not contribuyentes:
            raise NoEncontrado("El SRI no tiene un contribuyente con ese RUC.")
        if not isinstance(contribuyentes[0], dict):
            raise EstadoInvalido(_NO_DISPONIBLE)
        lista = establecimientos if isinstance(establecimientos, list) else []
        return contribuyentes[0], [fila for fila in lista if isinstance(fila, dict)]


def obtener_sri() -> ConsultaSri:
    return ConsultaSri()
