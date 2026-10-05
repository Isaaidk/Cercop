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
from time import monotonic

from contratacion.aplicacion.puertos.cache import Cache
from contratacion.dominio.busqueda import GENERACION_GLOBAL, clave_generacion

registro = logging.getLogger(__name__)

# Memo en proceso: `fuente -> (instante en que caduca, valor)`.
#
# Existe para ahorrar comandos, no para ahorrar latencia. Cada lectura de una página consulta
# primero la generación y después su clave, así que quitar la primera de las dos es la mitad del
# tráfico hacia el almacén: con cientos de usuarios pidiendo pantallas cada poco, eso son millones
# de comandos al día en un servicio que suele facturar por comando.
#
# El memo **no cambia la corrección**: la generación solo sube al cerrar un ciclo de ingesta, y unos
# segundos de desfase sobre una entrada que vive 900 s no pueden servir un dato que ya no
# corresponda. Si el proceso no acierta, consulta; si el almacén falla, se sigue con cero.
_memo: dict[str, tuple[float, int]] = {}

# Tope de lo recordado, por si la configuración trae un valor absurdo: un memo de horas dejaría de
# enterarse de los ciclos y convertiría una optimización en un error difícil de ver.
MEMO_MAXIMO_SEG = 60


def limpiar_memo() -> None:
    """Vacía el memo en proceso.

    Lo necesitan las pruebas, que comparten proceso: sin esto, una prueba vería la generación que
    dejó la anterior y el fallo aparecería en una prueba distinta de la que lo causó.
    """
    _memo.clear()


def _recordar(fuente: str, valor: int, ttl_seg: int) -> None:
    """Guarda el valor si el memo está activo."""
    if ttl_seg <= 0:
        return
    _memo[fuente] = (monotonic() + min(ttl_seg, MEMO_MAXIMO_SEG), valor)


def _recordado(fuente: str) -> int | None:
    """Valor memorizado, si sigue vigente. Caducado se descarta al leerlo."""
    entrada = _memo.get(fuente)
    if entrada is None:
        return None
    if entrada[0] <= monotonic():
        _memo.pop(fuente, None)
        return None
    return entrada[1]


async def leer_generacion(
    cache: Cache, fuente: str = GENERACION_GLOBAL, *, ttl_memo_seg: int = 0
) -> int:
    """Lee el contador de una generación.

    Cero es un valor válido: significa «todavía no hubo ningún cambio». No hace falta inicializar el
    contador, porque el primer incremento parte de cero. Si el caché no responde o guarda algo
    ilegible, se devuelve cero y se sigue: perder el caché cuesta latencia, no corrección.

    Con `ttl_memo_seg` mayor que cero, el valor se recuerda en este proceso durante ese tiempo. Un
    cero devuelto por un caché que **falló** no se recuerda: hacerlo alargaría el propio fallo.
    """
    if ttl_memo_seg > 0:
        memorizado = _recordado(fuente)
        if memorizado is not None:
            return memorizado

    try:
        valor = await cache.obtener(clave_generacion(fuente))
    except Exception:  # noqa: BLE001 - un caché roto no puede impedir una lectura
        registro.warning("No se pudo leer la generación de %s", fuente, exc_info=False)
        return 0

    if valor is None:
        _recordar(fuente, 0, ttl_memo_seg)
        return 0

    try:
        numero = int(valor)
    except ValueError:
        registro.warning("Generación ilegible para %s; se asume cero", fuente, exc_info=False)
        return 0

    _recordar(fuente, numero, ttl_memo_seg)
    return numero


async def subir_generacion(cache: Cache, fuente: str = GENERACION_GLOBAL) -> None:
    """Sube el contador de una generación, invalidando todo lo que dependía de la anterior.

    Un fallo aquí no se propaga: la caché es una optimización. El precio de no poder invalidar es
    servir datos algo más viejos hasta que caduquen por tiempo, nunca servir datos incorrectos.
    """
    try:
        await cache.incrementar(clave_generacion(fuente))
    except Exception:  # noqa: BLE001
        registro.warning("No se pudo subir la generación de %s", fuente, exc_info=False)
        return

    # Quien sube el contador es el que menos puede seguir sirviendo el valor anterior, así que se
    # olvida lo recordado. Se olvida en vez de escribir el valor nuevo porque el incremento puede
    # haber venido de otro proceso, y el que acaba de llegar es el único que importa.
    _memo.pop(fuente, None)
