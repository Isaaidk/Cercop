"""Puertos del asistente (chat): dónde se guardan las conversaciones y con qué modelo se conversa.

El caso de uso `asistente` depende de estos contratos y no de PostgreSQL ni del cliente HTTP del
proveedor de IA. Así se prueba entero con dobles en memoria —incluido el bucle de herramientas— y
cambiar de proveedor no toca la lógica.

Incluye también el contrato mínimo de los créditos y de las alertas que usa el asistente: los
adaptadores existentes (`RepositorioCreditos`, `RepositorioRadar`) ya los cumplen sin saberlo.
"""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from contratacion.aplicacion.puertos.radar import CandidatosRadar


class RepositorioConversaciones(Protocol):
    """Conversaciones privadas de cada persona, dentro de su empresa (RLS).

    Toda lectura y escritura lleva el `usuario_id`: una conversación de otra persona de la misma
    empresa no existe para quien pregunta.
    """

    async def listar(
        self, *, negocio_id: UUID, usuario_id: UUID, limite: int = 50
    ) -> list[dict[str, Any]]:
        """`id`, `titulo` y `actualizada_en`, de la más reciente a la más antigua."""
        ...

    async def obtener(
        self, *, negocio_id: UUID, usuario_id: UUID, conversacion_id: UUID
    ) -> dict[str, Any] | None: ...

    async def mensajes(
        self, *, negocio_id: UUID, usuario_id: UUID, conversacion_id: UUID, limite: int = 200
    ) -> list[dict[str, Any]]:
        """Los últimos `limite` mensajes, en orden cronológico."""
        ...

    async def crear(self, *, negocio_id: UUID, usuario_id: UUID, titulo: str) -> dict[str, Any]:
        """Crea la conversación y descarta las más antiguas por encima del tope por persona."""
        ...

    async def agregar_mensaje(
        self,
        *,
        negocio_id: UUID,
        usuario_id: UUID,
        conversacion_id: UUID,
        rol: str,
        texto: str,
        tarjetas: list[dict[str, Any]],
        sugerencias: list[str],
    ) -> dict[str, Any]:
        """Guarda el mensaje, toca `actualizada_en` y recorta los más antiguos sobre el tope."""
        ...

    async def renombrar(
        self, *, negocio_id: UUID, usuario_id: UUID, conversacion_id: UUID, titulo: str
    ) -> dict[str, Any] | None: ...

    async def borrar(
        self, *, negocio_id: UUID, usuario_id: UUID, conversacion_id: UUID
    ) -> bool: ...


class ModeloConversacion(Protocol):
    """Un modelo de chat con la API de herramientas de OpenAI."""

    @property
    def disponible(self) -> bool:
        """Hay un modelo configurado."""
        ...

    @property
    def en_servicio(self) -> bool:
        """Configurado y con el circuito cerrado: se le puede pedir algo ahora."""
        ...

    async def conversar(
        self,
        mensajes: list[dict[str, Any]],
        herramientas: list[dict[str, Any]] | None = None,
        *,
        max_tokens: int = 700,
        temperatura: float = 0.1,
    ) -> dict[str, Any]:
        """El mensaje del asistente: `content` y `tool_calls`. Lanza `EstadoInvalido` si falla."""
        ...


class CreditosIa(Protocol):
    """Saldo de créditos de IA. `consumir` lanza `SinCreditos` si no alcanza."""

    async def saldo(self, negocio_id: UUID) -> dict[str, Any]: ...

    async def consumir(
        self, negocio_id: UUID, usuario_id: UUID | None, cantidad: int, motivo: str
    ) -> int: ...

    async def devolver(self, negocio_id: UUID, cantidad: int, motivo: str) -> None: ...


class AlertasDelUsuario(CandidatosRadar, Protocol):
    """Crear y listar alertas, y los candidatos para contar cuántos procesos coinciden hoy."""

    async def listar_alertas(self, *, negocio_id: UUID | None = None) -> list[dict[str, Any]]: ...

    async def crear_alerta(
        self, *, negocio_id: UUID, usuario_id: UUID, campos: dict[str, Any]
    ) -> dict[str, Any]: ...
