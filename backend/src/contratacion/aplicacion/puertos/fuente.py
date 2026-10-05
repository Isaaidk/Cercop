"""Contrato de una fuente externa de datos de contratación.

La aplicación ingesta a través de este puerto, nunca hablando con HTTP directamente. Eso permite
probar toda la cadena con una fuente falsa, sin tocar la red ni gastar cuota, que es justo lo que
exige el requisito de que **ninguna petición de usuario llegue a la fuente oficial**.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from contratacion.dominio.cpc import ItemCpc
from contratacion.dominio.ingesta import Presupuesto


@dataclass
class ResultadoExtraccion:
    """Lo que devuelve una fuente en un ciclo."""

    registros: list[dict[str, Any]] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    peticiones: int = 0
    agoto_presupuesto: bool = False
    parcial: bool = False
    # Términos cuya búsqueda se **completó** en este ciclo, para poder darlos por buscados.
    #
    # Se declara aquí, y no solo se escribe desde la fuente que sí busca por término, porque el
    # ciclo lo lee **para todas las fuentes**. Cuando el campo no existía, la fuente que no lo
    # escribía (NCO) hacía que la lectura levantara `AttributeError`; el ciclo lo capturaba como
    # «fallo inesperado», así que el síntoma no era un error visible sino **cero registros en cada
    # ciclo**, con el listado de la fuente leído y descartado. La vacante por defecto dice la
    # verdad para una fuente que no busca por término: no hay nada que marcar.
    terminos_completos: tuple[str, ...] = ()


class FuenteExterna(Protocol):
    """Puerto que implementa cada fuente de datos."""

    codigo: str

    async def extraer(self, desde: datetime, presupuesto: Presupuesto) -> ResultadoExtraccion:
        """Trae los registros publicados desde `desde`.

        Debe respetar el presupuesto: cuando se agota, deja de pedir y marca `agoto_presupuesto`
        en lugar de seguir intentándolo.

        Si la fuente busca por términos, debe declarar en `terminos_completos` **solo** aquellos
        cuya lectura terminó: un término a medio leer que se diera por buscado dejaría un hueco que
        ya no se volvería a cubrir.
        """
        ...

    def clave_natural(self, crudo: Mapping[str, Any]) -> str | None:
        """Identificador estable del registro, o `None` si no sirve y hay que descartarlo."""
        ...

    def terminos(self, crudo: Mapping[str, Any]) -> Sequence[str]:
        """Identificadores de los términos que motivaron la ingesta de este registro."""
        ...


@runtime_checkable
class FuenteConDetalle(Protocol):
    """Fuente que, además del listado, publica una ficha con el detalle de cada registro.

    Es un puerto **aparte** y no un método más de `FuenteExterna` a propósito. Casi todas las
    fuentes no tienen ficha —el listado es todo lo que dan— y obligar a implementar un método que
    se va a quedar vacío llenaría de ruido el contrato común; peor todavía, un método obligatorio
    que devuelve nada es indistinguible de uno que falla. Aquí la ausencia del método **es** la
    respuesta: esta fuente no tiene detalle, y no hay nada que pedirle.

    `items` devuelve `None` cuando **no se pudo traer** (sin presupuesto, sin enlace, o la fuente no
    respondió) y una tupla —posiblemente vacía— cuando la ficha se leyó y no tenía ítems. La
    diferencia importa: lo primero deja el registro pendiente para el ciclo siguiente y lo segundo
    lo da por hecho. Confundirlos haría que una necesidad sin detalle se reintentara para siempre,
    o que una caída de red se diera por buena y no se volviera a pedir nunca.
    """

    async def items(
        self, enlace: str | None, presupuesto: Presupuesto
    ) -> tuple[ItemCpc, ...] | None:
        """Ítems de la ficha del registro, o `None` si no se pudieron obtener."""
        ...
