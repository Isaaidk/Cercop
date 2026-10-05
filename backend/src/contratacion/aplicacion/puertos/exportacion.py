"""Puerto de la selección de columnas que llevan las exportaciones de una empresa.

Va aparte del puerto de la plantilla aunque los dos sean «configuración de la exportación», y la
razón es que son decisiones independientes: una empresa puede tener plantilla y no querer tocar las
columnas —se exporta todo, como siempre—, o no tener plantilla y aun así querer un archivo más
corto. Meterlas en la misma tabla obligaría a tener plantilla para poder elegir columnas, y eso no
tiene ninguna relación con el problema.

El puerto guarda **claves del catálogo**, no etiquetas ni posiciones. Las etiquetas son del idioma
de la interfaz y las posiciones son de cada plantilla: guardar cualquiera de las dos ataría la
selección a la pantalla del día que se hizo, y al día siguiente el archivo saldría con otras
columnas sin que nadie hubiera tocado nada.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class SeleccionDeColumnas:
    """Las columnas que la empresa eligió para sus exportaciones, y cuándo lo hizo."""

    negocio_id: UUID
    columnas: tuple[str, ...]
    actualizado_en: datetime

    def como_diccionario(self) -> dict[str, Any]:
        return {
            "columnas": list(self.columnas),
            "actualizado_en": self.actualizado_en.isoformat(),
        }


class RepositorioColumnasExportacion(Protocol):
    """La selección de columnas por empresa."""

    async def obtener(self, *, negocio_id: UUID) -> SeleccionDeColumnas | None:
        """La selección guardada, o `None` si la empresa no ha elegido ninguna.

        `None` **no** es lo mismo que una lista vacía, aunque las dos acaben exportando todo: la
        lista vacía es una decisión —«lo quité»— y `None` es la ausencia de decisión. La pantalla
        las distingue para poder decir «no has elegido columnas: salen todas».
        """
        ...

    async def guardar(
        self,
        *,
        negocio_id: UUID,
        columnas: Sequence[str],
        actualizado_por: UUID | None,
        momento: datetime,
    ) -> None:
        """Deja esta selección como la de la empresa, reemplazando la anterior si la había.

        Una lista vacía es una elección legítima y significa «todas»: se guarda como tal en lugar de
        borrar la fila, para que la pantalla pueda decir desde cuándo no hay columnas excluidas.
        """
        ...
