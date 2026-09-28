"""Fábrica de la presencia.

Es el único sitio donde se decide si la presencia va sobre Redis o sobre la memoria del proceso, y
esa decisión se toma con el mismo criterio que el caché: **si hay `REDIS_URL`, hay Redis**. No hay
una bandera aparte para activar la presencia porque no puede funcionar mejor que el caché del que ya
depende el resto del sistema, y dos banderas que deben ir juntas acaban yendo separadas.

Sin Redis no se degrada a «nada»: se usa la implementación en memoria, que con un solo servidor es
exactamente correcta. Se prefiere eso a un modo apagado que dejaría el panel de presencia como una
pantalla que siempre dice que no hay nadie.

El alcance de lo que se está viendo —compartido entre réplicas o solo en este proceso— no se informa
aquí: viaja en cada respuesta de presencia, al lado del dato que califica. Ponerlo en `/listo` daría
una alarma falsa, porque con un solo servidor la presencia funciona perfectamente.
"""

from __future__ import annotations

import logging

from contratacion.aplicacion.puertos.presencia import BusEventos, RegistroPresencia
from contratacion.infraestructura.adaptadores.salida.presencia.memoria import PresenciaMemoria
from contratacion.infraestructura.adaptadores.salida.presencia.redis import (
    BusRedis,
    PresenciaRedis,
)
from contratacion.infraestructura.config.ajustes import obtener_ajustes

_presencia: RegistroPresencia | None = None
_bus: BusEventos | None = None


def _construir() -> tuple[RegistroPresencia, BusEventos]:
    """Crea el par que corresponde a la configuración, en una sola decisión."""
    ajustes = obtener_ajustes()
    if ajustes.cache_habilitada:
        return PresenciaRedis(ajustes.redis_url), BusRedis(ajustes.redis_url)
    return PresenciaMemoria(), PresenciaMemoria()


def obtener_presencia() -> RegistroPresencia:
    """Almacén de señales de vida, creado en la primera llamada."""
    global _presencia, _bus
    if _presencia is None or _bus is None:
        _presencia, _bus = _construir()
    return _presencia


def obtener_bus() -> BusEventos:
    """Bus de avisos, creado en la primera llamada.

    Comparte construcción con `obtener_presencia` para que las dos mitades sean siempre del mismo
    tipo. Construirlas por separado permitiría acabar con las señales en Redis y los avisos en
    memoria, que es una combinación que parece funcionar en pruebas con un solo proceso y falla en
    cuanto hay dos.
    """
    global _presencia, _bus
    if _presencia is None or _bus is None:
        _presencia, _bus = _construir()
    return _bus


async def cerrar_presencia() -> None:
    """Cierra los clientes al apagar el proceso.

    Cada uno se cierra por separado y con la excepción contenida: un fallo al cerrar el bus no puede
    impedir que se cierre el almacén de señales, porque el apagado es justo el momento en el que
    menos conviene dejar conexiones a medias.
    """
    global _presencia, _bus
    for recurso in (_presencia, _bus):
        if recurso is None:
            continue
        try:
            await recurso.cerrar()
        except Exception:  # noqa: BLE001 - apagar nunca debe propagar
            logging.getLogger(__name__).warning("Fallo al cerrar un recurso de presencia")
    _presencia = None
    _bus = None
