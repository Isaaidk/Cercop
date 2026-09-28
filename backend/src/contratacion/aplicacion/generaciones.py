"""Contadores de generación del caché.

Una generación es un número que se sube cuando algo cambia y que forma parte de las claves que
dependen de ello. Es la forma de invalidar en bloque **sin borrar nada**: las claves compuestas con
la generación anterior dejan de encontrarse y expiran solas por su tiempo de vida.

La ventaja sobre `DEL` con comodines es que no hace falta enumerar claves ni recorrer el espacio de
nombres, algo que en un almacén gestionado puede ser caro o estar deshabilitado. Y hay una segunda
ventaja, más importante: borrar es una orden que puede llegar tarde, mientras que una clave que ya
no se consulta no puede devolver datos viejos.
"""

from __future__ import annotations

import logging

from contratacion.aplicacion.puertos.cache import Cache
from contratacion.dominio.busqueda import GENERACION_GLOBAL, clave_generacion

registro = logging.getLogger(__name__)


async def leer_generacion(cache: Cache, fuente: str = GENERACION_GLOBAL) -> int:
    """Lee el contador de una generación.

    Cero es un valor válido: significa «todavía no hubo ningún cambio». No hace falta inicializar el
    contador, porque el primer incremento parte de cero. Si el caché no responde o guarda algo
    ilegible, se devuelve cero y se sigue: perder el caché cuesta latencia, no corrección.
    """
    try:
        valor = await cache.obtener(clave_generacion(fuente))
    except Exception:  # noqa: BLE001 - un caché roto no puede impedir una lectura
        registro.warning("No se pudo leer la generación de %s", fuente, exc_info=False)
        return 0
    if valor is None:
        return 0
    try:
        return int(valor)
    except ValueError:
        registro.warning("Generación ilegible para %s; se asume cero", fuente, exc_info=False)
        return 0


async def subir_generacion(cache: Cache, fuente: str = GENERACION_GLOBAL) -> None:
    """Sube el contador de una generación, invalidando todo lo que dependía de la anterior.

    Un fallo aquí no se propaga: la caché es una optimización. El precio de no poder invalidar es
    servir datos algo más viejos hasta que caduquen por tiempo, nunca servir datos incorrectos.
    """
    try:
        await cache.incrementar(clave_generacion(fuente))
    except Exception:  # noqa: BLE001
        registro.warning("No se pudo subir la generación de %s", fuente, exc_info=False)
