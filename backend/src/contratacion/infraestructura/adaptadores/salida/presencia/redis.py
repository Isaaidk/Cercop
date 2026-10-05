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

**Una sola suscripción para todo el proceso.** El reparto a cada panel se hace en memoria, con una
cola por canal abierto. Suscribirse por panel —una conexión por pestaña— agota mucho antes el
límite de conexiones de un plan gestionado que su memoria o su CPU: con treinta conexiones
disponibles, el sistema dejaba de aceptar paneles hacia la vigésima pestaña.

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
from typing import Any
from uuid import UUID

from redis.asyncio import Redis
from redis.asyncio.client import PubSub

from contratacion.aplicacion.puertos.presencia import Suscripcion
from contratacion.dominio.presencia import (
    PATRON_CANALES,
    EventoPresencia,
    Latido,
    canal_de_negocio,
    clave_latido,
    negocio_de_canal,
    prefijo_de_negocio,
)
from contratacion.infraestructura.adaptadores.salida.presencia.memoria import (
    MAXIMO_AVISOS_EN_COLA,
    deserializar_evento,
    serializar_evento,
)

registro = logging.getLogger(__name__)

# Espera entre intentos de reconexión de la suscripción, en segundos, y su tope. Se empieza corto
# porque el caso normal de una caída es un parpadeo de red, y se dobla hasta el tope para no
# martillear a un servidor que está caído de verdad.
RECONEXION_INICIAL_SEG = 0.5
RECONEXION_MAXIMA_SEG = 30.0

# Cuánto espera como mucho la apertura de un canal a que la suscripción compartida esté escuchando.
# Hay tope a propósito: si el almacén no responde, el panel tiene que abrirse igualmente. Se queda
# sin avisos en vivo y sigue recibiendo la instantánea periódica, que es un estado peor pero
# correcto, y desde luego mejor que una pantalla que no carga.
ESPERA_SUSCRIPCION_SEG = 2.0

# Cuántas claves pide cada paso del recorrido. `SCAN` no bloquea el servidor, y con lotes pequeños
# el recorrido se comporta igual de bien con cien señales que con cien mil sin retenerlo mientras
# dura.
LOTE_DE_RECORRIDO = 100


class _SuscripcionRedis:
    """Canal respaldado por una cola en memoria que llena el reparto del proceso."""

    def __init__(self, cola: asyncio.Queue[EventoPresencia]) -> None:
        self._cola = cola
        self._cerrada = False

    async def siguiente(self, espera_seg: float) -> EventoPresencia | None:
        if self._cerrada:
            return None
        try:
            return await asyncio.wait_for(self._cola.get(), espera_seg)
        except TimeoutError:
            # No llegó nada: quien transmite aprovecha para reenviar la instantánea completa.
            return None

    async def cerrar(self) -> None:
        """Deja de entregar avisos por este canal.

        **No cierra ninguna conexión**, porque ya no hay una por canal: el lector es compartido por
        todos los paneles del proceso, y cancelarlo apagaría el de los demás. La baja de verdad
        —dejar de escuchar el canal del negocio cuando ya nadie lo mira— la hace el gestor de
        contexto de `suscribir`, que es el único que sabe si quedaba alguien más.

        Es idempotente a propósito: el panel se va y, acto seguido, el gestor de contexto cierra el
        canal. Con dos cierres, el segundo no puede fallar.
        """
        self._cerrada = True


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
    """Reparto de avisos por Pub/Sub, con **una sola suscripción por proceso**.

    El lector compartido recibe los avisos y los reparte en memoria a la cola de cada canal abierto.
    El coste en conexiones pasa a ser uno, y —lo que importa— deja de crecer con el número de
    paneles: antes había una conexión por pestaña, que es lo que agota el límite de un plan
    gestionado mucho antes que la memoria o la CPU.

    La suscripción se abre en cuanto hay un canal y **no se cierra al quedarse sin ninguno**:
    quedarse sin paneles es un ir y venir continuo, así que abrir y cerrar con cada pestaña costaría
    más reconexiones que dejarla viva. Se cierra al apagar el proceso, en `cerrar()`.
    """

    def __init__(self, url: str) -> None:
        self._url = url
        # No abre ninguna conexión al construirse: el cliente solo conecta en el primer comando.
        self._cliente: Redis = Redis.from_url(url, decode_responses=True)
        # Reparto en proceso: negocio -> colas de sus paneles abiertos.
        self._canales: dict[UUID, set[asyncio.Queue[EventoPresencia]]] = {}
        # Estado de la suscripción compartida. `_pubsub` es `None` mientras nadie haya abierto un
        # canal y mientras dura una reconexión.
        self._pubsub: PubSub | None = None
        self._lector: asyncio.Task[None] | None = None
        # Se levanta cuando la suscripción está escuchando de verdad. `suscribir` lo espera para no
        # entregar un canal que todavía no recibe nada: sin esto, un aviso publicado justo después
        # de abrirlo se perdería sin que nadie se enterara, porque Pub/Sub no guarda historia.
        self._listo = asyncio.Event()

    async def publicar(self, *, negocio_id: UUID, evento: EventoPresencia) -> None:
        """Publica en el canal del negocio.

        Si no hay nadie escuchando, el aviso se pierde sin más. Pub/Sub no guarda historia y está
        bien que sea así: lo que no puede perderse es el estado, y para eso está la instantánea
        periódica, que se construye leyendo el almacén y no el bus.
        """
        await self._cliente.publish(canal_de_negocio(negocio_id), serializar_evento(evento))

    @asynccontextmanager
    async def suscribir(self, *, negocio_id: UUID) -> AsyncIterator[Suscripcion]:
        cola: asyncio.Queue[EventoPresencia] = asyncio.Queue(maxsize=MAXIMO_AVISOS_EN_COLA)
        self._abrir(negocio_id, cola)
        try:
            # Se espera a que la suscripción escuche antes de entregar el canal. El caso que evita:
            # abrir el panel y que alguien entre en ese mismo instante, con el aviso publicado antes
            # de que este proceso estuviera suscrito. La instantánea lo corrige después, pero el
            # usuario vería el punto cambiar de color con retraso sin motivo.
            await self._esperar_listo()
            yield _SuscripcionRedis(cola)
        finally:
            # En `finally` y no al final del bloque: una transmisión que el cliente corta a medias
            # pasa por aquí igualmente, y sin esto cada pestaña cerrada dejaría una cola colgada
            # hasta que el proceso muriera.
            self._soltar(negocio_id, cola)

    async def cerrar(self) -> None:
        """Para el lector compartido y suelta las conexiones del proceso."""
        if self._lector is not None:
            self._lector.cancel()
            with suppress(asyncio.CancelledError):
                await self._lector
            self._lector = None
        self._pubsub = None
        self._canales.clear()
        await self._cliente.aclose()

    def _abrir(self, negocio_id: UUID, cola: asyncio.Queue[EventoPresencia]) -> None:
        """Registra el canal y arranca el lector compartido si aún no existe.

        Es **síncrona a propósito**: entre comprobar si hay lector y crearlo no puede haber ningún
        `await`, o dos paneles abriéndose a la vez levantarían dos lectores —y dos conexiones— sin
        que nada fallara. Sin puntos de suspensión, el bucle de eventos no puede intercalar nada y
        la comprobación es una garantía en lugar de una probabilidad.
        """
        self._canales.setdefault(negocio_id, set()).add(cola)

        if self._lector is None or self._lector.done():
            self._lector = asyncio.create_task(self._escuchar_bucle(), name="presencia-lector")

    def _soltar(self, negocio_id: UUID, cola: asyncio.Queue[EventoPresencia]) -> None:
        """Da de baja el canal. El lector compartido sigue vivo aunque no quede ninguno."""
        banda = self._canales.get(negocio_id)
        if banda is None:
            return
        banda.discard(cola)
        if not banda:
            self._canales.pop(negocio_id, None)

    async def _esperar_listo(self) -> None:
        """Espera a que la suscripción compartida esté escuchando, con tope de tiempo.

        El tope no es un descuido: si el almacén no responde, el panel tiene que abrirse igual. Se
        quedará sin avisos en vivo y seguirá recibiendo la instantánea periódica, que es un estado
        peor pero correcto —y desde luego mejor que una pantalla que no carga.
        """
        with suppress(TimeoutError):
            await asyncio.wait_for(self._listo.wait(), ESPERA_SUSCRIPCION_SEG)

    async def _escuchar_bucle(self) -> None:
        """Mantiene la suscripción viva, reconectando si el enlace se cae.

        Sin esta reconexión, una caída de la red dejaría el proceso sordo: los canales seguirían
        abiertos y devolviendo `None` —como cuando no pasa nada— y el panel mostraría un estado
        congelado sin un solo error. La instantánea periódica disimula el hueco, y eso es
        precisamente lo que lo vuelve difícil de detectar.
        """
        espera = RECONEXION_INICIAL_SEG
        while True:
            try:
                await self._escuchar()
                espera = RECONEXION_INICIAL_SEG
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - el bus degrada, no se cae
                registro.warning("Se interrumpió la suscripción de presencia", exc_info=True)

            await asyncio.sleep(espera)
            espera = min(espera * 2, RECONEXION_MAXIMA_SEG)

    async def _escuchar(self) -> None:
        """Abre la suscripción por patrón y reparte lo que llegue hasta que algo falle."""
        cliente: Redis = Redis.from_url(self._url, decode_responses=True)
        try:
            pubsub: PubSub = cliente.pubsub(ignore_subscribe_messages=True)
            await pubsub.psubscribe(PATRON_CANALES)
            # El orden importa: primero se publica el estado y después se avisa. Al revés, quien
            # despierte con el aviso podría encontrarse `_pubsub` todavía sin asignar.
            self._pubsub = pubsub
            self._listo.set()

            async for mensaje in pubsub.listen():
                self._repartir(mensaje)
        finally:
            # Se baja la señal al salir, pase lo que pase: mientras el lector no esté escuchando,
            # un canal abierto no debe darse por listo. La siguiente vuelta del bucle la volverá a
            # levantar al reconectar.
            self._listo.clear()
            self._pubsub = None
            with suppress(Exception):
                await cliente.aclose()

    def _repartir(self, mensaje: dict[str, Any]) -> None:
        """Entrega el aviso a las colas de los paneles de ese negocio.

        Un negocio sin paneles en este proceso no tiene banda: el aviso se descarta sin más. No es
        un fallo —el bus no guarda historia y el proceso solo reparte lo suyo— sino la consecuencia
        de escuchar por patrón.
        """
        if mensaje.get("type") != "pmessage":
            return

        canal = mensaje.get("channel")
        if not isinstance(canal, str):
            return

        negocio_id = negocio_de_canal(canal)
        if negocio_id is None:
            return

        bandas = self._canales.get(negocio_id)
        if not bandas:
            return

        evento = deserializar_evento(mensaje["data"], negocio_id)
        if evento is None:
            return

        for cola in tuple(bandas):
            try:
                cola.put_nowait(evento)
            except asyncio.QueueFull:
                # Un panel lento no puede frenar el cierre de sesión de otra persona. El aviso se
                # descarta y la instantánea periódica pondrá su estado en su sitio.
                registro.debug("Se descartó un aviso de presencia: la cola del panel está llena")


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
