"""Casos de uso: subir, consultar y quitar la plantilla de Excel de la empresa.

Tres operaciones con una regla común: **solo un rol administrativo toca la plantilla**. No es por
celo: la plantilla decide cómo se ve **todo** lo que la empresa exporta, y la reciben todas las
personas a las que se les manda un archivo. Que cualquiera con acceso de lectura pudiera cambiarla
sería tanto como dejar que reescriba los documentos que salen de la empresa con su membrete. Quien
consulta sí puede **ver** que existe y cuál es, porque no hay nada reservado en un nombre de archivo
y una fecha; lo que no puede es cambiarla.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.plantillas import HOJA_DE_DATOS, revisar_plantilla
from contratacion.aplicacion.puertos.plantillas import (
    AlmacenPlantillas,
    PlantillaGuardada,
    RepositorioPlantillas,
)
from contratacion.dominio.errores import DatoInvalido

registro = logging.getLogger(__name__)


async def consultar(
    actor: Actor,
    *,
    repositorio: RepositorioPlantillas,
) -> PlantillaGuardada | None:
    """La plantilla de la empresa, o `None` si no hay ninguna.

    La lee cualquier rol: es información sobre la configuración de la empresa, no un secreto.
    """
    return await repositorio.obtener(negocio_id=actor.negocio_id)


async def leer_contenido(
    actor: Actor,
    *,
    repositorio: RepositorioPlantillas,
    almacen: AlmacenPlantillas,
) -> bytes | None:
    """Los bytes de la plantilla de la empresa, o `None` si no hay o no se puede leer.

    **Nunca lanza.** Un archivo que se borró del disco, un volumen que no está montado, un permiso
    cambiado: cualquiera de esas cosas convertiría la descarga en un error si se dejara propagar, y
    dejar a alguien sin su Excel por un problema de formato es peor que darle el libro genérico. Se
    avisa en el registro —para que se pueda arreglar— y se sigue.

    Vive aquí y no en el enrutador que la usa porque la usan **dos**: la exportación —que rellena
    la plantilla— y el análisis —que dice dónde entrarían los datos—. Una copia en cada sitio se
    separaría en el primer cambio, y la que se quedara atrás daría una respuesta distinta sobre el
    mismo archivo.
    """
    guardada = await repositorio.obtener(negocio_id=actor.negocio_id)
    if guardada is None:
        return None
    try:
        return await almacen.leer(ruta=guardada.ruta)
    except Exception:  # noqa: BLE001 - una plantilla ilegible no puede impedir exportar
        registro.warning(
            "No se pudo leer la plantilla de Excel del negocio %s en %s; se sigue sin ella",
            actor.negocio_id,
            guardada.ruta,
            exc_info=False,
        )
        return None


async def subir(
    actor: Actor,
    *,
    nombre_archivo: str,
    contenido: bytes,
    repositorio: RepositorioPlantillas,
    almacen: AlmacenPlantillas,
    momento: datetime | None = None,
) -> PlantillaGuardada:
    """Reemplaza la plantilla de la empresa por la que se acaba de subir.

    El orden de los pasos es la decisión importante de esta función, y va del revés de lo que parece
    natural:

    1. **Se comprueba el archivo entero** antes de escribir nada. Si no sirve, no se ha tocado ni la
       plantilla anterior ni el disco.
    2. **Se escribe el archivo nuevo** —reemplazando al viejo de forma atómica— y solo entonces se
       actualiza la fila.

    Ese orden tiene una consecuencia deliberada: si fallara la actualización de la fila, el disco
    tendría el archivo nuevo y la base seguiría apuntando a la ruta vieja —que es **la misma ruta**,
    porque el nombre lo compone el identificador del negocio—. Es decir: el resultado sería una
    plantilla nueva con metadatos viejos, y el único dato que quedaría desfasado es la huella. Al
    revés —fila primero, archivo después— una caída dejaría la fila apuntando a un archivo que no
    existe, y **todas** las exportaciones de esa empresa fallarían hasta que alguien lo notara.

    Se devuelve la plantilla guardada y no un «ok» para que la respuesta pueda decir cuál quedó y
    desde cuándo, que es lo que la pantalla necesita mostrar.
    """
    instante = momento or datetime.now(UTC)

    actor.exigir_administrativo()
    revisar_plantilla(nombre_archivo, contenido)

    ruta = await almacen.guardar(negocio_id=actor.negocio_id, contenido=contenido)

    await repositorio.reemplazar(
        negocio_id=actor.negocio_id,
        nombre_archivo=nombre_archivo,
        ruta=ruta,
        hash_contenido=_huella(contenido),
        tamano_bytes=len(contenido),
        subida_por=actor.usuario_id,
        momento=instante,
    )

    registro.info(
        "Plantilla de Excel actualizada para el negocio %s (%s, %s bytes)",
        actor.negocio_id,
        nombre_archivo,
        len(contenido),
    )

    guardada = await repositorio.obtener(negocio_id=actor.negocio_id)
    if guardada is None:
        # No debería poder pasar: se acaba de escribir. Si pasa, es que no ha funcionado, y
        # devolver un objeto inventado ocultaría el problema.
        raise DatoInvalido(
            "La plantilla se guardó pero no se ha podido volver a leer. "
            "Vuelve a intentarlo y, si se repite, avisa al administrador."
        )
    return guardada


async def quitar(
    actor: Actor,
    *,
    repositorio: RepositorioPlantillas,
    almacen: AlmacenPlantillas,
) -> bool:
    """Deja la empresa sin plantilla. Devuelve si había alguna que quitar.

    Se borra **primero la fila y después el archivo**, al revés que al subir, y por la misma razón
    llevada al otro lado: si fallara el borrado del disco después de quitar la fila, quedaría un
    archivo huérfano que nadie usa —molesto, inofensivo—. Al revés, un fallo dejaría la fila
    apuntando a un archivo inexistente y las exportaciones fallarían.
    """
    actor.exigir_administrativo()

    quitada = await repositorio.eliminar(negocio_id=actor.negocio_id)
    if quitada is None:
        return False
    await almacen.borrar(ruta=quitada.ruta)
    registro.info("Plantilla de Excel retirada del negocio %s", actor.negocio_id)
    return True


def _huella(contenido: bytes) -> str:
    """Identifica el contenido del archivo sin guardarlo.

    Es lo que permite detectar que el archivo del disco ya no es el que se subió, y también contar
        dos veces el mismo archivo si hiciera falta. `sha256` y no un hash corto: esto no es una
        clave de caché, es una comprobación de integridad, y no hay prisa que justifique acortarla.
    """
    return hashlib.sha256(contenido).hexdigest()


def nombre_de_la_hoja() -> str:
    """Dónde escribe el sistema dentro de la plantilla. Expuesto para la respuesta y la ayuda."""
    return HOJA_DE_DATOS
