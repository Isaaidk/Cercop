"""Puerto del catálogo de términos y de su cola de ingesta.

Un término es global (se ingesta **una sola vez** para todos los negocios) y cada negocio se
suscribe a él. Esa separación es la que evita que diez clientes pidiendo «obras viales» provoquen
diez consultas a la fuente oficial: la suscripción es del negocio, la ingesta es del término.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID


class RepositorioTerminos(Protocol):
    """Catálogo global de términos, suscripciones por negocio y cola de ingesta."""

    async def asegurar_termino(self, texto: str, *, origen: str = "usuario") -> UUID:
        """Devuelve el identificador del término, creándolo si aún no existe.

        Es idempotente por la forma normalizada: «Gestión» y «gestion» resuelven al mismo término.
        """
        ...

    async def suscribir(self, negocio_id: UUID, termino_id: UUID) -> bool:
        """Suscribe el negocio al término. Devuelve `True` si la suscripción es nueva."""
        ...

    async def alta_de_termino(
        self,
        negocio_id: UUID,
        *,
        texto: str,
        maximo_terminos: int,
        origen: str = "usuario",
    ) -> Mapping[str, Any]:
        """Crea el término, suscribe el negocio y devuelve su estado, todo en una transacción.

        Sustituye a la secuencia de llamadas sueltas —enumerar, crear, suscribir, leer estado,
        contar suscriptores— porque cada una abría su propia conexión y, contra una base remota, el
        coste del alta lo dominaban esas idas y vueltas y no el trabajo real.

        Devolver el estado aquí es lo que permite que sea una sola transacción: quien llama recibe
        ya la fecha de última ingesta y el número de suscriptores y no tiene que volver a preguntar.

        Lanza `DatoInvalido` si el negocio alcanzó `maximo_terminos` y la suscripción sería nueva.
        La comprobación ocurre **dentro** de la transacción, así que el tope es exacto aunque dos
        peticiones del mismo negocio lleguen a la vez.
        """
        ...

    async def alta_de_terminos(
        self,
        negocio_id: UUID,
        *,
        textos: Sequence[str],
        maximo_terminos: int,
        origen: str = "usuario",
    ) -> tuple[Mapping[str, Any], ...]:
        """Crea y suscribe **varios** términos de una vez, en una sola transacción.

        Devuelve una fila por término con `termino_id`, `texto` y `suscripcion_nueva`. El tope se
        comprueba contra el total que quedaría, no contra cada palabra por separado, así que un lote
        que se pase se rechaza entero en lugar de dejar la mitad aplicada.
        """
        ...

    async def desuscribir(self, negocio_id: UUID, termino_id: UUID) -> bool:
        """Desactiva la suscripción. Devuelve `True` si existía y estaba activa."""
        ...

    async def terminos_del_negocio(self, negocio_id: UUID) -> Sequence[Mapping[str, Any]]:
        """Términos suscritos, con su estado de ingesta, para pintar los chips del panel."""
        ...

    async def estado_termino(self, termino_id: UUID) -> Mapping[str, Any] | None:
        """Estado de ingesta de un término. `None` si no existe."""
        ...

    async def pendientes_de_ingesta(self, limite: int) -> Sequence[Mapping[str, Any]]:
        """Términos en cola, ordenados por prioridad.

        El orden es: primero los que piden más negocios y después los que llevan más tiempo sin
        ingesta. Así un término popular no queda atrás y ninguno se queda sin atender para siempre.
        """
        ...

    async def suscriptores(self, termino_id: UUID) -> int:
        """Número de negocios suscritos, que decide la prioridad en la cola."""
        ...

    async def suscriptores_de(self, termino_ids: Sequence[UUID]) -> Mapping[UUID, int]:
        """Los suscriptores de **varios** términos, en una sola lectura.

        Existe porque su hermana de arriba se llamaba una vez por término dentro de un bucle, y cada
        llamada es una ida y vuelta a la base: con cuarenta palabras clave, el listado tardaba
        **segundos** en pintarse y no había ningún error que lo explicara, solo una pantalla que
        parecía colgada. Es el N+1 de manual, y la forma de que no vuelva es tener una operación que
        pida todo junto.

        Se devuelve un mapa y no una lista para que quien consulta no tenga que recorrer nada: busca
        por identificador. **Cada identificador preguntado aparece en el mapa**, con cero si el
        término no existe o si nadie está suscrito: no hay claves ausentes, así que quien consulta
        no tiene que tratar la ausencia como un caso aparte. Y un término que se borre entre que se
        lee el listado y se piden los conteos no puede tumbar la pantalla.
        """
        ...

    async def marcar_ingestado(self, termino_id: UUID, momento: datetime) -> None:
        """Registra que el término se acaba de consultar en la fuente."""
        ...
