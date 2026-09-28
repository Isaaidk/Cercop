"""Adaptador de la fuente OCDS (Datos Abiertos de contratación).

A diferencia de NCO, aquí **sí hay histórico**: el listado se consulta por año, así que al añadir un
término nuevo se puede recuperar lo publicado en años anteriores. Es lo que permite no perder
contrataciones cuando alguien agrega una palabra clave.

El coste es que cada término consume al menos una petición **por año y por página**, así que el
adaptador trabaja siempre contra el presupuesto del ciclo y se detiene cuando se agota.

Sobre el punto de partida (`desde`)
-----------------------------------
La API **no filtra por rango de fechas**: busca por año. Así que `desde` no se traduce a un filtro,
se traduce a **cuántos años hay que mirar**. Un término que se busca por primera vez llega con una
fecha antigua y por eso se revisan varios años; uno que se buscó hace un rato cae en el año en curso
y se revisa solo ese.

Ignorar `desde` —que era lo que hacía antes— funcionaba por accidente y a un precio alto: se
revisaban todos los años configurados en cada ciclo de 15 minutos, para todos los términos. Ahora el
coste es proporcional a lo que de verdad hay que recuperar.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from contratacion.aplicacion.puertos.fuente import ResultadoExtraccion
from contratacion.dominio.ingesta import Presupuesto, clave_natural
from contratacion.infraestructura.adaptadores.salida.fuentes.limitador import LimitadorTasa

CODIGO = "OCDS"
API_URL = "https://datosabiertos.compraspublicas.gob.ec/PLATAFORMA/api"
SEARCH_URL = f"{API_URL}/search_ocds"
PAGINAS_POR_DEFECTO = 3

# Años que se revisan como mucho hacia atrás cuando el punto de partida es antiguo. Es el tope del
# rescate histórico: sin él, un término nuevo con una fecha muy lejana dispararía peticiones sin
# control. Con tres años se cubre de sobra la vida útil de una necesidad de contratación.
ANIOS_MAXIMOS_HACIA_ATRAS = 3

AVISO_PRESUPUESTO = (
    "El presupuesto de peticiones de este ciclo se agotó antes de completar todas las búsquedas. "
    "Los términos pendientes se ingestan en el siguiente ciclo."
)
AVISO_SIN_RESPUESTA = (
    "La fuente de procesos publicados no respondió para algunos términos. "
    "Los resultados pueden estar incompletos."
)


class FuenteOcds:
    """Procesos publicados, consultados por término y año."""

    codigo = CODIGO

    def __init__(
        self,
        terminos: Sequence[str],
        *,
        limitador: LimitadorTasa | None = None,
        paginas_por_termino: int = PAGINAS_POR_DEFECTO,
        anios: Sequence[int] | None = None,
    ) -> None:
        self._terminos = [termino.strip() for termino in terminos if termino.strip()]
        self._limitador = limitador or LimitadorTasa()
        self._paginas_por_termino = max(1, paginas_por_termino)
        # `None` significa «decide tú a partir del punto de partida». Una lista explícita manda.
        self._anios = list(anios) if anios is not None else None

    def _anios_para(self, desde: datetime) -> list[int]:
        """Años que hay que revisar, dado desde cuándo hay que buscar.

        Se acota por abajo con `ANIOS_MAXIMOS_HACIA_ATRAS` para que un punto de partida muy antiguo
        no dispare el número de peticiones, y por arriba con el año en curso.
        """
        if self._anios is not None:
            return list(self._anios)
        actual = datetime.now(UTC).year
        minimo = max(actual - ANIOS_MAXIMOS_HACIA_ATRAS, desde.year)
        return list(range(minimo, actual + 1))

    async def extraer(self, desde: datetime, presupuesto: Presupuesto) -> ResultadoExtraccion:
        resultado = ResultadoExtraccion()
        pendientes = False

        for termino in self._terminos:
            for anio in self._anios_para(desde):
                for pagina in range(1, self._paginas_por_termino + 1):
                    if not presupuesto.consumir():
                        resultado.agoto_presupuesto = True
                        resultado.avisos.append(AVISO_PRESUPUESTO)
                        return resultado

                    payload = await self._limitador.solicitar_json(
                        SEARCH_URL,
                        {"year": anio, "search": termino, "page": pagina},
                        etiqueta=f"{termino} · {anio} · pág. {pagina}",
                    )
                    resultado.peticiones += 1

                    if payload is None:
                        pendientes = True
                        continue

                    registros = payload.get("data") or []
                    if not isinstance(registros, list) or not registros:
                        break  # No hay más páginas para este término y año.

                    for registro in registros:
                        if isinstance(registro, dict):
                            registro["_termino_buscado"] = termino
                            resultado.registros.append(registro)

                    total_paginas = payload.get("pages")
                    if isinstance(total_paginas, int) and pagina >= total_paginas:
                        break

        if pendientes:
            resultado.avisos.append(AVISO_SIN_RESPUESTA)
            resultado.parcial = True

        return resultado

    def clave_natural(self, crudo: Mapping[str, Any]) -> str | None:
        """El `ocid` es el identificador estándar y estable de un proceso."""
        ocid = str(crudo.get("ocid") or "").strip()
        if not ocid:
            return None
        return clave_natural(CODIGO, [ocid])

    def terminos(self, crudo: Mapping[str, Any]) -> Sequence[str]:
        """Término por el que entró el registro, útil para saber por qué está en la base."""
        encontrado = str(crudo.get("_termino_buscado") or "").strip()
        return [encontrado] if encontrado else []

    async def cerrar(self) -> None:
        await self._limitador.cerrar()
