"""Presencia y bus de avisos dentro de un solo proceso, sin Redis.

Existe por una razón muy concreta: **el sistema tiene que funcionar en local**. Si sin Redis las
señales de vida no se guardaran en ninguna parte, todo el mundo aparecería desconectado y el panel
de presencia sería una pantalla que siempre miente. Esta implementación hace que con un solo
servidor —que es el caso de desarrollo y el de un despliegue pequeño— todo sea correcto.

Su límite, dicho sin adornos: las señales viven en la memoria de este proceso. Con dos réplicas, un
usuario conectado a una aparece desconectado en la otra. No falla ni avisa: da una respuesta
equivocada con toda tranquilidad. Por eso `compartida` devuelve `False` y el panel publica ese dato,
para que quien lo mire sepa qué está viendo en lugar de creérselo.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID

from contratacion.aplicacion.puertos.presencia import Suscripcion
from contratacion.dominio.presencia import (
    EstadoPresencia,
    EventoPresencia,
    Latido,
    Motivo,
    Presencia,
    TipoEvento,
    clave_latido,
    prefijo_de_negocio,
)

registro = logging.getLogger(__name__)

# Una cola por panel que esté mirando. Se acota porque un consumidor lento no puede frenar a quien
# publica: si se llena, el aviso se descarta y la relectura periódica del panel lo corrige. Bloquear
# una petición de latido —o el cierre de otra persona— esperando a que un panel termine de pintar
# sería trasladar el problema de uno a todos.
MAXIMO_AVISOS_EN_COLA = 200


class _SuscripcionMemoria:
    """Canal local: una cola que llena quien publica."""

    def __init__(self, cola: asyncio.Queue[EventoPresencia]) -> None:
        self._cola = cola

    async def siguiente(self, espera_seg: float) -> EventoPresencia | None:
        try:
            return await asyncio.wait_for(self._cola.get(), espera_seg)
        except TimeoutError:
            # No llegó nada. Es la señal para que quien transmite reenvíe la instantánea.
            return None

    async def cerrar(self) -> None:
        return None


class PresenciaMemoria:
    """Guarda las señales en memoria y reparte los avisos dentro del proceso.

    Implementa los dos puertos a la vez, que es correcto aquí y solo aquí: sin almacén compartido,
    el almacén de señales y el reparto de avisos son la misma cosa —el estado de este proceso— y
    separarlos en dos objetos solo daría la apariencia de que pueden desplegarse por separado.
    """

    def __init__(self) -> None:
        # Clave -> (caducidad, señal). Se guarda la caducidad explícita en lugar de confiar en que
        # alguien limpie: así una lectura puede descartar lo vencido sin recorrer nada más.
        self._senales: dict[str, tuple[datetime, Latido]] = {}
        self._canales: dict[str, set[asyncio.Queue[EventoPresencia]]] = {}

    @property
    def compartida(self) -> bool:
        """`False`: esta implementación no ve más allá de su propio proceso."""
        return False

    async def marcar(
        self,
        *,
        usuario_id: UUID,
        sesion_id: UUID,
        negocio_id: UUID,
        momento: datetime,
        ttl_seg: int,
    ) -> None:
        self._limpiar_vencidas()
        self._senales[clave_latido(negocio_id, sesion_id)] = (
            momento + timedelta(seconds=ttl_seg),
            Latido(usuario_id=usuario_id, sesion_id=sesion_id, momento=momento),
        )

    async def olvidar(self, *, negocio_id: UUID, sesion_id: UUID) -> None:
        self._senales.pop(clave_latido(negocio_id, sesion_id), None)

    async def vivas(self, *, negocio_id: UUID) -> tuple[Latido, ...]:
        self._limpiar_vencidas()
        prefijo = prefijo_de_negocio(negocio_id)
        return tuple(
            senal for clave, (_, senal) in self._senales.items() if clave.startswith(prefijo)
        )

    async def publicar(self, *, negocio_id: UUID, evento: EventoPresencia) -> None:
        for cola in tuple(self._canales.get(str(negocio_id), ())):
            try:
                cola.put_nowait(evento)
            except asyncio.QueueFull:
                # Se descarta a propósito. El panel se corrige con la instantánea periódica, y nadie
                # que esté cerrando la pestaña se queda esperando a que otro termine de pintar.
                registro.debug("Se descartó un aviso de presencia: la cola del panel está llena")

    @asynccontextmanager
    async def suscribir(self, *, negocio_id: UUID) -> AsyncIterator[Suscripcion]:
        cola: asyncio.Queue[EventoPresencia] = asyncio.Queue(maxsize=MAXIMO_AVISOS_EN_COLA)
        banda = self._canales.setdefault(str(negocio_id), set())
        banda.add(cola)
        try:
            yield _SuscripcionMemoria(cola)
        finally:
            # En `finally` y no al final del bloque: una transmisión que el cliente corta a medias
            # pasa por aquí igualmente, y sin esto cada pestaña cerrada dejaría una cola colgada.
            banda.discard(cola)
            if not banda:
                self._canales.pop(str(negocio_id), None)

    async def ping(self) -> bool:
        return True

    async def cerrar(self) -> None:
        self._senales.clear()
        self._canales.clear()

    def _limpiar_vencidas(self) -> None:
        """Descarta lo caducado usando el reloj de este proceso.

        Que el reloj pueda estar mal no rompe nada: el dominio vuelve a comprobar la vigencia de
        cada señal contra el momento de la consulta. Esta limpieza solo evita que el diccionario
        crezca sin freno; la decisión de si una señal vale no se toma aquí.
        """
        ahora = datetime.now(UTC)
        for clave in [clave for clave, (caduca, _) in self._senales.items() if caduca <= ahora]:
            self._senales.pop(clave, None)


def serializar_evento(evento: EventoPresencia) -> str:
    """Convierte un aviso a JSON. Lo usan las dos implementaciones, para que el formato no varíe."""
    return json.dumps(evento.como_diccionario(), ensure_ascii=False)


def deserializar_evento(crudo: str | bytes, negocio_id: UUID) -> EventoPresencia | None:
    """Reconstruye un aviso recibido del canal.

    Un mensaje ilegible se descarta en lugar de propagarse: el bus transporta avisos, y un dato
    corrupto no puede convertirse en un error que corte la transmisión de alguien que solo estaba
    mirando el panel. La instantánea periódica pondrá el estado en su sitio.
    """
    try:
        datos = json.loads(crudo)
        usuario = datos.get("usuario") or {}
        return EventoPresencia(
            tipo=TipoEvento(str(datos["tipo"])),
            negocio_id=negocio_id,
            momento=datetime.fromisoformat(str(datos["momento"])),
            presencias=(),
            presencia=None if not usuario else _presencia_de(usuario),
        )
    except (KeyError, ValueError, TypeError):
        registro.warning("Aviso de presencia ilegible; se descarta", exc_info=False)
        return None


def _presencia_de(datos: dict[str, object]) -> Presencia:
    """Reconstruye la presencia de un aviso.

    No se valida en exceso: es un dato para pintar un punto, no uno con el que se vaya a decidir un
    permiso. Si llegara corrupto, el aviso se descarta unos párrafos más arriba.
    """
    ultimo = datos.get("ultimo_latido_en")
    dispositivos = datos.get("dispositivos")
    return Presencia(
        usuario_id=UUID(str(datos["usuario_id"])),
        estado=EstadoPresencia(str(datos["estado"])),
        motivo=Motivo(str(datos["motivo"])),
        sesion_id=UUID(str(datos["sesion_id"])) if datos.get("sesion_id") else None,
        ultimo_latido_en=datetime.fromisoformat(str(ultimo)) if ultimo else None,
        dispositivos=dispositivos if isinstance(dispositivos, int) else 0,
    )
