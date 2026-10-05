"""Implementación de la plantilla sobre el sistema de archivos del servidor.

Por qué un directorio y no un almacén de objetos
------------------------------------------------
Con el despliegue en un solo servidor, un directorio es gratis, no añade credenciales ni un
adaptador de red, y entra en la copia de seguridad sin configurar nada. Un almacén de objetos
(S3, R2, B2) tendría sentido con varios servidores o para no perder las plantillas si se pierde la
máquina; aquí sería una dependencia de pago para guardar archivos de medio megabyte.

La contrapartida, dicha sin adornos: **si se pierde el servidor y la copia de seguridad no incluye
este directorio, las plantillas se pierden** y cada empresa tendría que volver a subir la suya.
No es una pérdida irrecuperable —cada empresa tiene su archivo— pero sí una molestia. Por eso el
directorio está en un **volumen** del `compose` —y no en la capa del contenedor, que se pierde al
recrearlo— y `deploy/copias.sh` lo archiva en cada copia, aparte del volcado de la base.

Por qué el nombre del archivo lo pone el almacén
------------------------------------------------
Porque la alternativa es un agujero. `guardar` recibe el identificador del negocio —un UUID que
genera el sistema— y compone el nombre a partir de él. El nombre que subió el cliente **no entra en
el camino**: se guarda en la base como etiqueta para mostrarlo, y nunca se toca el disco con él. Un
nombre como `../../etc/passwd` escribiría fuera del directorio, y un nombre con un salto de línea o
un nulo rompería cosas peores.

Por qué el archivo se reemplaza en dos pasos
--------------------------------------------
Se escribe primero en un archivo temporal y se renombra encima del definitivo. El renombrado dentro
del mismo sistema de archivos es **atómico**: quien lea la plantilla verá la versión vieja o la
nueva, pero nunca media. Escribir directamente sobre el archivo bueno dejaría una ventana en la que
la plantilla está a medias, y una exportación que cayera en ese instante generaría un Excel roto sin
que nada fallara.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from uuid import UUID

from contratacion.infraestructura.config.ajustes import obtener_ajustes

registro = logging.getLogger(__name__)

EXTENSION = ".xlsx"


class AlmacenLocal:
    """Plantillas en un directorio del servidor.

    **Todo el trabajo de disco va a un hilo aparte.** Leer o escribir un archivo de medio megabyte
    bloquea el proceso mientras dura, y este proceso atiende a todo el mundo: bloquearlo medio
    segundo con cada exportación sería notarse en las peticiones de los demás. Es la misma razón por
    la que la exportación con openpyxl tiene su propio apartado pendiente.
    """

    def __init__(self, directorio: str | Path) -> None:
        self._directorio = Path(directorio)

    @property
    def directorio(self) -> Path:
        return self._directorio

    def _ruta_de(self, negocio_id: UUID) -> Path:
        """Camino del archivo de un negocio.

        El nombre sale **solo** del UUID, que el cliente no elige. Por eso no hay nada que sanear:
        en este camino no hay ninguna entrada del usuario.
        """
        return self._directorio / f"{negocio_id}{EXTENSION}"

    async def guardar(self, *, negocio_id: UUID, contenido: bytes) -> str:
        destino = self._ruta_de(negocio_id)
        return await asyncio.to_thread(self._escribir, destino, contenido)

    @staticmethod
    def _escribir(destino: Path, contenido: bytes) -> str:
        destino.parent.mkdir(parents=True, exist_ok=True)
        # `with_suffix` conserva el nombre y cambia la extensión: el temporal queda al lado, en el
        # mismo sistema de archivos, que es lo que hace que el renombrado sea atómico.
        temporal = destino.with_suffix(destino.suffix + ".parcial")
        temporal.write_bytes(contenido)
        # `replace` y no `rename`: sobreescribe el destino si existe, sin comprobarlo antes y sin
        # ventana entre la comprobación y la escritura.
        temporal.replace(destino)
        return str(destino)

    async def leer(self, *, ruta: str) -> bytes:
        return await asyncio.to_thread(Path(ruta).read_bytes)

    async def borrar(self, *, ruta: str) -> None:
        await asyncio.to_thread(self._borrar, ruta)

    @staticmethod
    def _borrar(ruta: str) -> None:
        try:
            Path(ruta).unlink()
        except FileNotFoundError:
            # Que ya no esté es el objetivo cumplido, no un error: se llama justo después de quitar
            # la fila, y un reintento tras un fallo parcial pasaría por aquí.
            registro.info("La plantilla ya no estaba en el disco: %s", ruta)
        except OSError as exc:
            # Cualquier otro fallo **sí** se propaga. Dejar un archivo huérfano en el disco no rompe
            # nada y ocupa poco, pero silenciarlo haría que nadie supiera que se está acumulando
            # basura en el servidor.
            registro.warning("No se pudo borrar la plantilla %s: %s", ruta, exc)
            raise


def obtener_almacen() -> AlmacenLocal:
    """Almacén según la configuración del proceso."""
    return AlmacenLocal(obtener_ajustes().plantillas_dir)
