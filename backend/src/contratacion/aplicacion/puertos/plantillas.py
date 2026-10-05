"""Puertos de la plantilla de Excel de cada empresa.

Dos puertos y no uno, aunque casi siempre se usen juntos, porque **son dos cosas distintas con dos
formas de fallar distintas**: la fila en la base y el archivo en el disco. Mezclarlos obligaría a
que el repositorio supiera escribir archivos, y entonces no habría forma de probar la lógica sin
tocar el disco.

Esa separación es la que permite además razonar sobre el caso incómodo —la fila existe y el archivo
no, o al revés— en lugar de dar por hecho que los dos cambios ocurren siempre a la vez. No ocurren:
son dos sistemas, y uno puede fallar.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PlantillaGuardada:
    """La plantilla de una empresa: la fila, con la referencia al archivo.

    **No lleva el contenido.** Traerlo obligaría a leer del disco en cada consulta de metadatos,
    y la pantalla que solo quiere decir «tienes una plantilla subida el día 12» acabaría cargando
    un archivo de medio megabyte para mostrarlo.
    """

    negocio_id: UUID
    nombre_archivo: str
    ruta: str
    hash_contenido: str
    tamano_bytes: int
    actualizado_en: datetime

    def como_diccionario(self) -> dict[str, Any]:
        return {
            "nombre_archivo": self.nombre_archivo,
            "tamano_bytes": self.tamano_bytes,
            "actualizado_en": self.actualizado_en.isoformat(),
        }


class RepositorioPlantillas(Protocol):
    """La fila: qué plantilla tiene cada empresa y dónde está su archivo."""

    async def obtener(self, *, negocio_id: UUID) -> PlantillaGuardada | None:
        """La plantilla del negocio, o `None` si no ha subido ninguna."""
        ...

    async def reemplazar(
        self,
        *,
        negocio_id: UUID,
        nombre_archivo: str,
        ruta: str,
        hash_contenido: str,
        tamano_bytes: int,
        subida_por: UUID | None,
        momento: datetime,
    ) -> None:
        """Deja esta plantilla como la del negocio, sustituyendo la anterior si la había.

        Es una sola operación de escritura y no un «borrar y luego insertar»: si se hiciera en dos
        pasos y fallara el segundo, la empresa se quedaría **sin plantilla** por haber intentado
        cambiarla, que es el peor resultado posible de una acción que solo pretendía actualizarla.
        """
        ...

    async def eliminar(self, *, negocio_id: UUID) -> PlantillaGuardada | None:
        """Quita la plantilla y devuelve **cuál era**, para poder borrar su archivo.

        Devuelve la fila en lugar de un booleano porque quien llama necesita la ruta del archivo que
        hay que borrar del disco, y después de borrar la fila ya no hay dónde preguntarlo.
        """
        ...


class AlmacenPlantillas(Protocol):
    """El archivo: dónde vive y cómo se lee."""

    async def guardar(self, *, negocio_id: UUID, contenido: bytes) -> str:
        """Escribe el archivo del negocio y devuelve su ruta.

        La ruta la decide el almacén y **nunca el cliente**: si el nombre del archivo subido formara
        parte del camino, un nombre como `../../etc/algo` escribiría fuera del directorio previsto.
        El nombre original se guarda solo como etiqueta para mostrarlo.
        """
        ...

    async def leer(self, *, ruta: str) -> bytes:
        """Devuelve el contenido del archivo. Lanza si no está."""
        ...

    async def borrar(self, *, ruta: str) -> None:
        """Borra el archivo. **No lanza si ya no estaba.**

        Es idempotente a propósito: se llama justo después de quitar la fila, y que el archivo ya no
        existiera no es un fallo, es el objetivo cumplido.
        """
        ...
