"""Adaptador de la fuente NCO (Necesidades de Contratación).

Es la fuente principal del producto y la más eficiente: **una sola petición** devuelve el listado
completo de necesidades vigentes (~1,8 MB, 3-6 segundos). No admite paginación ni filtros por fecha.

Consecuencia que hay que tener presente: como no hay filtro por fecha, cada ciclo recibe el listado
íntegro y es la **huella de contenido** la que decide qué es nuevo, qué cambió y qué sigue igual.
Eso hace el ciclo barato en peticiones, no en procesamiento.

Y la limitación de negocio más importante: la fuente **solo publica lo vigente**. No hay histórico.
Lo que no se capture, se pierde para siempre.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from contratacion.aplicacion.puertos.fuente import ResultadoExtraccion
from contratacion.dominio.ingesta import Presupuesto, clave_natural
from contratacion.infraestructura.adaptadores.salida.fuentes.limitador import LimitadorTasa

CODIGO = "NCO"
ENDPOINT = (
    "https://www.compraspublicas.gob.ec/ProcesoContratacion/compras/NCO/NCORetornaRegistros.cpe"
)
TIEMPO_LIMITE_SEG = 120.0

# La fuente exige estas cabeceras: sin ellas trata la petición como un cliente ajeno.
CABECERAS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "X-Requested-With": "XMLHttpRequest",
    "Referer": (
        "https://www.compraspublicas.gob.ec/ProcesoContratacion/compras/NCO/FrmNCOListado.cpe"
    ),
}

AVISO_SIN_RESPUESTA = (
    "La fuente de necesidades no respondió (límite de peticiones o corte de red). "
    "Los resultados de este ciclo pueden estar incompletos."
)


class FuenteNco:
    """Necesidades de Contratación y Recepción de Proformas."""

    codigo = CODIGO

    def __init__(self, limitador: LimitadorTasa | None = None) -> None:
        self._limitador = limitador or LimitadorTasa(cabeceras=CABECERAS)

    async def extraer(self, desde: datetime, presupuesto: Presupuesto) -> ResultadoExtraccion:
        """Trae el listado completo. `desde` no se usa: la fuente no filtra por fecha."""
        if not presupuesto.consumir():
            return ResultadoExtraccion(agoto_presupuesto=True, parcial=True)

        payload = await self._limitador.solicitar_json(
            ENDPOINT,
            {"lot": 1},
            etiqueta="NCO listado",
            tiempo_limite=TIEMPO_LIMITE_SEG,
        )
        if payload is None:
            return ResultadoExtraccion(peticiones=1, avisos=[AVISO_SIN_RESPUESTA], parcial=True)

        registros = payload.get("data") or []
        if not isinstance(registros, list):
            return ResultadoExtraccion(peticiones=1, avisos=[AVISO_SIN_RESPUESTA], parcial=True)

        return ResultadoExtraccion(
            registros=[registro for registro in registros if isinstance(registro, dict)],
            peticiones=1,
        )

    def clave_natural(self, crudo: Mapping[str, Any]) -> str | None:
        """Identificador propio de la necesidad, con el código como respaldo.

        Se prefiere el identificador interno porque el código de contratación puede cambiar de
        formato entre publicaciones, y eso generaría duplicados.
        """
        interno = str(crudo.get("tcom_necesidad_contratacion_id") or "").strip()
        codigo = str(crudo.get("codigo_contratacion") or "").strip()
        if not interno and not codigo:
            return None
        return clave_natural(CODIGO, [interno or codigo])

    def terminos(self, crudo: Mapping[str, Any]) -> Sequence[str]:
        """NCO no depende de términos: se ingesta siempre completo."""
        return ()

    async def cerrar(self) -> None:
        await self._limitador.cerrar()
