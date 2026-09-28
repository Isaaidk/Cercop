"""Presencia y bus de avisos sobre Redis.

Es la implementación del despliegue. Redis resuelve las dos cosas que la memoria de un proceso no
puede resolver:

- **Las señales se ven desde todas las réplicas.** Si la API corre en tres contenedores, quien
  pregunta por un usuario puede ser atendido por cualquiera de ellos y la respuesta tiene que ser la
  misma.
- **Los avisos cruzan de un proceso a otro.** Un panel conectado a la réplica A tiene que enterarse
  de que alguien entró por la réplica B. Sin esto, el panel solo vería la mitad de los movimientos y
  lo peor es que parecería funcionar.

Tres decisiones que no son obvias
---------------------------------
**Cliente propio, separado del caché.** Comparten la misma URL, pero no el mismo objeto. La
presencia y el caché de consultas tienen ciclos de vida distintos, y cerrar uno no debe llevarse al
otro por compartir una referencia. El coste es una conexión más.

**El canal se abre con una conexión dedicada.** Redis no admite comandos normales en una conexión
suscrita, así que la suscripción necesita su propio `pubsub`.

**Se lee en una tarea de fondo que llena una cola en memoria.** Así `siguiente()` espera sobre una
cola —donde cancelar es seguro y no pierde lo encolado— en lugar de sobre una lectura de red a
medias, cuya cancelación es justo el detalle que rompe una transmisión en silencio y solo en
producción.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from uuid import UUID

from redis.asyncio import Redis
from redis.asyncio.client import PubSub

from contratacion.aplicacion.puertos.presencia import Suscripcion
from contratacion.dominio.presencia import (
    EventoPresencia,
    Latido,
    canal_de_negocio,
    clave_latido,
    prefijo_de_negocio,
)
from contratacion.infraestructura.adaptadores.salida.presencia.memoria import (
    MAXIMO_AVISOS_EN_COLA,
    deserializar_evento,
    serializar_evento,
)

registro = logging.getLogger(__name__)

# Cuántas claves pide cada paso del recorrido. `SCAN` no bloquea el servidor, y con lotes pequeños
# el recorrido se comporta igual de bien con cien señales que con cien mil sin retenerlo mientras
# dura.
LOTE_DE_RECORRIDO = 100


class _SuscripcionRedis:
    """Canal respaldado por Pub/Sub y una tarea de fondo que lo vacía en una cola."""

    def __init__(self, cola: asyncio.Queue[EventoPresencia], lector: asyncio.Task[None]) -> None:
        self._cola = cola
        self._lector = lector

    async def siguiente(self, espera_seg: float) -> EventoPresencia | None:
        try:
            return await asyncio.wait_for(self._cola.get(), espera_seg)
        except TimeoutError:
            # No llegó nada: quien transmite aprovecha para reenviar la instantánea completa.
            return None

    async def cerrar(self) -> None:
        """Detiene la lectura.

        Los sockets los cierra el gestor de contexto que abrió la suscripción. Aquí solo se para el
        flujo de avisos, para que nadie siga escribiendo en una cola que ya nadie va a leer. Dejar
        el cierre de los recursos a quien los abrió evita el fallo clásico de cerrar dos veces lo
        mismo.
        """
        self._lector.cancel()
        with suppress(asyncio.CancelledError):
            await self._lector


class PresenciaRedis:
    """Señales de vida con caducidad, en Redis."""

    def __init__(self, url: str) -> None:
        self._cliente: Redis = Redis.from_url(url, decode_responses=True)

    @property
    def compartida(self) -> bool:
        return True

    async def marcar(
        self,
        *,
        usuario_id: UUID,
        sesion_id: UUID,
        negocio_id: UUID,
        momento: datetime,
        ttl_seg: int,
    ) -> None:
        """Escribe la señal con caducidad.

        Se usa `SET` con `EX` y no una escritura más una expiración aparte: en un solo comando no
        hay ventana en la que la clave exista sin caducar, que es como se acumularían señales
        eternas afirmando que alguien sigue conectado cuando ya no está.
        """
        await self._cliente.set(
            clave_latido(negocio_id, sesion_id),
            json.dumps(
                {"u": str(usuario_id), "s": str(sesion_id), "m": momento.isoformat()},
                separators=(",", ":"),
            ),
            ex=ttl_seg,
        )

    async def olvidar(self, *, negocio_id: UUID, sesion_id: UUID) -> None:
        await self._cliente.delete(clave_latido(negocio_id, sesion_id))

    async def vivas(self, *, negocio_id: UUID) -> tuple[Latido, ...]:
        """Recorre las claves del negocio con `SCAN` y lee sus valores de una vez.

        El patrón del recorrido **incluye el negocio**, así que esta consulta nunca llega a ver las
        señales de otra empresa: el aislamiento lo garantiza la forma de la clave y no un filtro
        posterior que alguien pueda olvidar al refactorizar.
        """
        claves = [
            clave
            async for clave in self._cliente.scan_iter(
                match=f"{prefijo_de_negocio(negocio_id)}*", count=LOTE_DE_RECORRIDO
            )
        ]
        if not claves:
            return ()

        crudos = await self._cliente.mget(claves)
        senales: list[Latido] = []
        for clave, crudo in zip(claves, crudos, strict=False):
            senal = deserializar_latido(crudo, clave)
            if senal is not None:
                senales.append(senal)
        return tuple(senales)

    async def ping(self) -> bool:
        try:
            return bool(await self._cliente.ping())
        except Exception:  # noqa: BLE001 - informar del estado nunca debe tumbar el servicio
            registro.warning("El almacén de presencia no responde", exc_info=False)
            return False

    async def cerrar(self) -> None:
        await self._cliente.aclose()


class BusRedis:
    """Reparto de avisos por Pub/Sub."""

    def __init__(self, url: str) -> None:
        self._url = url
        # No abre ninguna conexión al construirse: el cliente solo conecta en el primer comando.
        self._cliente: Redis = Redis.from_url(url, decode_responses=True)

    async def publicar(self, *, negocio_id: UUID, evento: EventoPresencia) -> None:
        """Publica en el canal del negocio.

        Si no hay nadie escuchando, el aviso se pierde sin más. Pub/Sub no guarda historia y está
        bien que sea así: lo que no puede perderse es el estado, y para eso está la instantánea
        periódica, que se construye leyendo el almacén y no el bus.
        """
        await self._cliente.publish(canal_de_negocio(negocio_id), serializar_evento(evento))

    @asynccontextmanager
    async def suscribir(self, *, negocio_id: UUID) -> AsyncIterator[Suscripcion]:
        # Conexión propia: Redis no admite comandos normales en una conexión suscrita, así que la
        # suscripción no puede compartir la del publicador.
        cliente: Redis = Redis.from_url(self._url, decode_responses=True)
        pubsub: PubSub = cliente.pubsub(ignore_subscribe_messages=True)
        await pubsub.subscribe(canal_de_negocio(negocio_id))

        cola: asyncio.Queue[EventoPresencia] = asyncio.Queue(maxsize=MAXIMO_AVISOS_EN_COLA)
        lector = asyncio.create_task(_leer(pubsub, cola, negocio_id))
        try:
            yield _SuscripcionRedis(cola, lector)
        finally:
            # En `finally` y no al final del bloque: una transmisión que el cliente corta a medias
            # pasa por aquí igualmente, y sin esto cada pestaña cerrada dejaría una conexión
            # suscrita colgada en el servidor hasta que el proceso muriera.
            lector.cancel()
            with suppress(asyncio.CancelledError):
                await lector
            with suppress(Exception):
                # Cerrar el cliente cierra su grupo de conexiones, y la suscripción vive dentro de
                # ese grupo. Cerrarla por separado sería redundante, y además su método de cierre
                # no está anotado en la biblioteca, así que invocarlo obligaría a silenciar el
                # analizador justo donde no hay nada que silenciar.
                await cliente.aclose()

    async def cerrar(self) -> None:
        await self._cliente.aclose()


async def _leer(pubsub: PubSub, cola: asyncio.Queue[EventoPresencia], negocio_id: UUID) -> None:
    """Tarea de fondo: pasa los mensajes del canal a la cola.

    `listen()` reconecta por su cuenta si el enlace se cae, así que esta tarea solo termina cuando
    alguien la cancela. Y si terminara por un error inesperado, el panel no se queda mudo: sigue
    recibiendo la instantánea periódica, que se construye leyendo el almacén y no depende del bus.
    """
    try:
        async for mensaje in pubsub.listen():
            if mensaje.get("type") != "message":
                continue
            evento = deserializar_evento(mensaje["data"], negocio_id)
            if evento is None:
                continue
            try:
                cola.put_nowait(evento)
            except asyncio.QueueFull:
                # Un panel lento no puede frenar el cierre de sesión de otra persona. El aviso se
                # descarta y la instantánea periódica pondrá su estado en su sitio.
                registro.debug("Se descartó un aviso de presencia: la cola del panel está llena")
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - la transmisión degrada, no se cae
        registro.warning("Se interrumpió la lectura del canal de presencia", exc_info=True)


def deserializar_latido(crudo: object, clave: str) -> Latido | None:
    """Reconstruye una señal. Un valor ilegible se descarta en vez de romper el listado.

    Se registra la clave, que es lo único que identifica la señal corrupta. No contiene datos
    personales: son dos identificadores opacos y una marca de tiempo.
    """
    if crudo is None:
        return None
    texto = crudo.decode() if isinstance(crudo, bytes) else str(crudo)
    try:
        datos = json.loads(texto)
        return Latido(
            usuario_id=UUID(str(datos["u"])),
            sesion_id=UUID(str(datos["s"])),
            momento=datetime.fromisoformat(str(datos["m"])),
        )
    except (KeyError, ValueError, TypeError):
        registro.warning("Señal de presencia ilegible en %s; se descarta", clave, exc_info=False)
        return None
