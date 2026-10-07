"""Puerto de mantenimiento del histórico: vencimientos y retención.

Son los dos trabajos que no son ni ingesta ni consulta, y que por eso no tenían sitio en los puertos
que ya existían:

- **Vencimientos.** El estado de una ínfima cuantía no lo publica la fuente: se deduce de su fecha
  límite de proformas. Lo único que hay que hacer con él es saber si **cruzó** desde la vuelta
  anterior, porque eso es lo que invalida unas estadísticas que ya no son ciertas.
- **Retención.** Una ínfima cuyo plazo venció hace días ya no es una oportunidad, y su fila pesa
  unos dos kilobytes. El histórico es el activo del producto —la fuente no publica el pasado—, así
  que borrar es una decisión de política, no un detalle de limpieza: el plazo de retención es un
  ajuste y se puede desactivar.

Los dos se apoyan en la misma columna, `registro.plazo_proformas_en`, y en el mismo índice parcial.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ResultadoPurga:
    """Lo que borró —o borraría— una vuelta de la retención."""

    registros: int
    historial: int
    #: `True` cuando solo se contó: la consulta es la misma y no escribe nada.
    simulado: bool = False


class RepositorioMantenimiento(Protocol):
    """Escrituras sobre el histórico que no vienen de la fuente."""

    async def contar_vencimientos(self, *, desde: datetime, hasta: datetime) -> int:
        """Cuántos registros tenían su plazo dentro de la ventana y ya lo pasaron.

        Cuenta por **instante de vencimiento**, no por «vencidos hasta ahora»: lo primero es «qué ha
        cambiado desde la vuelta anterior» y lo segundo sería una constante que crece despacio y no
        distingue una vuelta tranquila de una que dejó pasar veinte vencimientos.

        Como la ventana la marca el intervalo entre vueltas, cada vencimiento se cuenta **una sola
        vez**, en la vuelta siguiente. Un `count` sobre un rango estrecho de un índice parcial.
        """
        ...

    async def contar_vencidas(self, antes_de: datetime) -> int:
        """Cuántos registros llevan vencidos más de lo que dura la retención.

        Es el tamaño de la purga, y se pide aparte de la purga para poder informar del trabajo
        pendiente sin borrar nada.
        """
        ...

    async def purgar_vencidas(
        self, antes_de: datetime, maximo: int, *, simular: bool = False
    ) -> ResultadoPurga:
        """Retira, como mucho `maximo`, los registros vencidos antes de `antes_de`.

        `maximo` no es un tope de comodidad: cada fila se lleva por delante su copia en el histórico
        y su punto de contacto, y borrar cinco mil de golpe mantendría bloqueadas las filas el
        tiempo suficiente para que el resto del sistema lo notara. La vuelta siguiente sigue donde
        quedó.

        Con `simular=True` se cuenta lo que se borraría y **no se escribe**: así se puede enseñar el
        tamaño de la retención antes de activarla.
        """
        ...
