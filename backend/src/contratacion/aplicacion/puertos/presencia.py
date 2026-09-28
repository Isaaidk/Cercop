"""Puertos de presencia y del bus de avisos.

Son **dos** puertos y no uno porque resuelven problemas distintos, aunque en el despliegue los
implemente el mismo Redis:

- `RegistroPresencia` guarda señales de vida que caducan solas. Se consulta para pintar el estado.
- `BusEventos` reparte avisos entre procesos. No guarda nada: si nadie escucha, el aviso se pierde.

Mantenerlos separados permite que la ausencia de uno no arrastre al otro. Sin Redis, las señales
viven en la memoria del proceso y los avisos se reparten dentro de él; el panel sigue funcionando en
un solo servidor, y la respuesta lo dice en lugar de fingir que todo está bien.

La suscripción es un objeto con `siguiente(espera)` y no un iterador asíncrono
--------------------------------------------------------------------------
Un iterador asíncrono se consumiría con `asyncio.wait_for(anext(...))` para poder cerrar el bucle
cuando no llega nada durante un rato, y `wait_for` **cancela** lo que está esperando. Cancelar una
lectura a medias dentro de un generador asíncrono lo termina, y el bucle se rompería en silencio: la
transmisión se quedaría muda sin que nadie se enterara.

Con `siguiente(espera)` la cancelación ocurre sobre una lectura de una cola en memoria, que está
preparada para ello y no pierde lo que ya esté encolado. Se prefiere una interfaz algo menos
elegante a un fallo que solo aparece en producción y solo cuando nadie habla durante un rato.
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Protocol
from uuid import UUID

from contratacion.dominio.presencia import EventoPresencia, Latido


class RegistroPresencia(Protocol):
    """Señales de vida, con caducidad."""

    async def marcar(
        self,
        *,
        usuario_id: UUID,
        sesion_id: UUID,
        negocio_id: UUID,
        momento: datetime,
        ttl_seg: int,
    ) -> None:
        """Anota que una sesión sigue viva, con el tiempo de vigencia indicado.

        Es idempotente: repetirla solo alarga la vigencia. No actualiza `ultimo_uso` de la sesión, y
        eso es deliberado — ver la nota de `aplicacion/casos_uso/presencia.py`.
        """
        ...

    async def olvidar(self, *, negocio_id: UUID, sesion_id: UUID) -> None:
        """Retira la señal de una sesión. Se usa cuando alguien avisa de que se va.

        Borrar la señal no basta para apagar el punto —el color también exige una sesión vigente—,
        pero deja el estado limpio y hace que el listado no dependa de que el almacén caduque la
        clave a tiempo.
        """
        ...

    async def vivas(self, *, negocio_id: UUID) -> tuple[Latido, ...]:
        """Señales del negocio. **Solo** las de ese negocio.

        El aislamiento se resuelve en el almacén, con el prefijo de la clave, y no filtrando
        después: así una implementación que se equivoque al filtrar no puede llegar a devolver datos
        de otra empresa, porque nunca los ha leído.
        """
        ...

    @property
    def compartida(self) -> bool:
        """`True` si las señales las ven todas las réplicas.

        El panel lo publica tal cual. Sin esto, con un solo servidor todo es correcto y con varios
        los usuarios aparecerían desconectados según qué réplica atendiera la consulta, sin ningún
        error visible.
        """
        ...

    async def ping(self) -> bool:
        """`True` si el almacén responde.

        Nunca lanza: sirve para informar del estado del servicio, y un informe que falla no informa.
        """
        ...

    async def cerrar(self) -> None:
        """Libera recursos."""
        ...


class Suscripcion(Protocol):
    """Un canal abierto hacia el negocio, del que se van sacando avisos."""

    async def siguiente(self, espera_seg: float) -> EventoPresencia | None:
        """El siguiente aviso, o `None` si no llegó ninguno en el tiempo indicado.

        Devolver `None` en vez de lanzar excepción es lo que permite que el enrutador tenga un solo
        bucle: cuando no hay avisos, aprovecha para reenviar la instantánea completa. Esa relectura
        es la que corrige el panel cuando un aviso se pierde y la que refleja los rojos por falta de
        señal, que por definición no generan ningún aviso.
        """
        ...

    async def cerrar(self) -> None:
        """Cierra el canal y libera su conexión."""
        ...


class BusEventos(Protocol):
    """Reparto de avisos entre procesos."""

    async def publicar(self, *, negocio_id: UUID, evento: EventoPresencia) -> None:
        """Publica un aviso. Si nadie escucha, se descarta: el bus no guarda historia."""
        ...

    def suscribir(self, *, negocio_id: UUID) -> AbstractAsyncContextManager[Suscripcion]:
        """Abre un canal para el negocio.

        Es un iterador asíncrono **de suscripciones** y no una suscripción, para poder declararlo
        como contexto asíncrono con `asynccontextmanager` y garantizar que el canal se cierra aunque
        el cliente corte la conexión a medias. Una transmisión abandonada que no cierre su conexión
        deja un recurso colgado en el servidor por cada pestaña que alguien cierre.
        """
        ...

    async def cerrar(self) -> None:
        """Libera recursos."""
        ...
