"""Contratos de un proveedor en los datos abiertos del SERCOP (OCDS).

Dos consultas públicas y documentadas: `search_ocds` con el filtro `supplier` (por nombre) y
`record` (el proceso completo, con el RUC del adjudicatario y los CPC). La búsqueda por nombre trae
homónimos, así que cada candidato se verifica por RUC en su `record`.

Es una consulta lenta (~3 s por búsqueda, ~1,3 s por proceso) a un servicio ajeno, así que está
acotada: pocos años, pocos procesos, paralelismo limitado y respuesta recordada un rato. Una
persona que pulsa dos veces no cuesta dos recorridos.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from contratacion.aplicacion.hilos import MemoLru
from contratacion.dominio.errores import EstadoInvalido
from contratacion.dominio.historial import contrato_de, resumir_historial, termino_de_busqueda
from contratacion.infraestructura.adaptadores.salida.resiliencia import Cortacircuitos, circuito

_BASE = "https://datosabiertos.compraspublicas.gob.ec/PLATAFORMA/api"
_TIMEOUT = httpx.Timeout(25.0, connect=8.0)
_ENCABEZADOS = {"Accept": "application/json", "User-Agent": "Mozilla/5.0 (CercoApp)"}
ANIOS = 3
MAX_PROCESOS = 12
_TTL_SEG = 1800.0
# Sin resultados puede ser un fallo pasajero del servicio ajeno: se recuerda poco.
_TTL_VACIO_SEG = 60.0
_NO_DISPONIBLE = (
    "No se pudo consultar los datos abiertos del SERCOP en este momento. Inténtalo en unos "
    "minutos o agrega tu experiencia a mano."
)
# Historial público por RUC (datos abiertos): se comparte entre empresas sin riesgo. LRU acotada.
_RECORDADOS: MemoLru[str, tuple[float, dict[str, Any]]] = MemoLru(512)
# Un solo recorrido a la vez por proceso de API: protege al servicio ajeno de las ráfagas.
_TURNOS = asyncio.Semaphore(4)
# El semáforo de arriba reparte las peticiones HTTP; el circuito acota los **recorridos** enteros.
# Sin él, con el servicio lento, cada persona que abre su perfil dejaba una corrutina esperando
# turno sin límite. Seis recorridos a la vez por proceso, y quien llega con todos ocupados espera
# dos segundos antes de recibir «inténtalo en unos segundos». Tres fallos seguidos del listado
# abren el circuito dos minutos.
_CIRCUITO = {
    "mensaje": (
        "Los datos abiertos del SERCOP no responden ahora. Inténtalo en unos minutos o agrega tu "
        "experiencia a mano."
    ),
    "umbral_fallos": 3,
    "enfriamiento_seg": 120.0,
    "max_concurrencia": 6,
    "espera_turno_seg": 2.0,
    "limite_seg": 60.0,
}


def circuito_ocds() -> Cortacircuitos:
    return circuito("ocds_historial", **_CIRCUITO)


class HistorialOcds:
    def __init__(self, *, transporte: httpx.AsyncBaseTransport | None = None) -> None:
        self._transporte = transporte

    async def _json(self, cliente: httpx.AsyncClient, ruta: str, **params: str) -> Any:
        async with _TURNOS:
            respuesta = await cliente.get(f"{_BASE}/{ruta}", params=params)
        respuesta.raise_for_status()
        return respuesta.json()

    async def _listado(self, cliente: httpx.AsyncClient, anio: int, termino: str) -> dict[str, Any]:
        listado: dict[str, Any] = await self._json(
            cliente, "search_ocds", year=str(anio), search="", supplier=termino, page="1"
        )
        return listado

    async def _proceso(
        self, cliente: httpx.AsyncClient, fila: dict[str, Any], ruc: str
    ) -> dict[str, Any] | None:
        try:
            return contrato_de(await self._json(cliente, "record", ocid=str(fila["ocid"])), ruc)
        except (httpx.HTTPError, ValueError, KeyError):
            return None  # un proceso que no responde no tumba el resto

    async def consultar(self, ruc: str, razon_social: str) -> dict[str, Any]:
        termino = termino_de_busqueda(razon_social)
        if len(termino) < 3:
            raise EstadoInvalido("La razón social es muy corta para buscar contratos.")
        guardado = _RECORDADOS.get(ruc)
        if guardado:
            vigencia = _TTL_SEG if guardado[1]["verificados"] else _TTL_VACIO_SEG
            if time.monotonic() - guardado[0] < vigencia:
                return guardado[1]

        anio_actual = datetime.now(UTC).year
        async with (
            circuito_ocds().proteger(),
            httpx.AsyncClient(
                timeout=_TIMEOUT, headers=_ENCABEZADOS, transport=self._transporte
            ) as cliente,
        ):
            try:
                listados = await asyncio.gather(
                    *(self._listado(cliente, anio_actual - n, termino) for n in range(ANIOS))
                )
            except (httpx.HTTPError, ValueError) as error:
                raise EstadoInvalido(_NO_DISPONIBLE) from error
            total = sum(int(listado.get("total") or 0) for listado in listados)
            filas = [
                fila
                for listado in listados
                for fila in listado.get("data") or []
                if isinstance(fila, dict) and fila.get("ocid")
            ]
            filas.sort(key=lambda fila: str(fila.get("date") or ""), reverse=True)
            candidatas = filas[:MAX_PROCESOS]
            resultados = await asyncio.gather(
                *(self._proceso(cliente, fila, ruc) for fila in candidatas)
            )

        contratos = [c for c in resultados if c is not None]
        resumen = resumir_historial(
            ruc, contratos, total=total, revisados=len(candidatas), termino=termino
        )
        _RECORDADOS[ruc] = (time.monotonic(), resumen)
        return resumen


def obtener_historial() -> HistorialOcds:
    return HistorialOcds()
