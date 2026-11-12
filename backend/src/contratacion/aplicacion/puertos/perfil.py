"""Puertos del perfil de la empresa y de las fuentes públicas que lo proponen.

El caso de uso `gestionar_perfil` importaba hasta ahora cuatro adaptadores concretos —el repositorio
de PostgreSQL, el cliente del SRI, el de los datos abiertos del SERCOP y el lector de PDF—. Eso
ataba la regla de negocio («qué se puede guardar en el perfil, y quién») a cómo se habla con cada
servicio, y obligaba a levantar la infraestructura para probarla. Con estos contratos la aplicación
depende de **qué** necesita, y la infraestructura decide **cómo** (inversión de dependencias).

Son `Protocol`: los adaptadores existentes los cumplen sin heredar de nada ni saber que existen, y
un doble de pruebas también.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol
from uuid import UUID


class RepositorioPerfil(Protocol):
    """La identidad de la empresa y sus colecciones (actividades, contactos, experiencia…)."""

    async def leer(self, negocio_id: UUID) -> dict[str, Any]: ...

    async def guardar_identidad(self, negocio_id: UUID, campos: dict[str, Any]) -> None: ...

    async def agregar(
        self, negocio_id: UUID, coleccion: str, campos: dict[str, Any]
    ) -> dict[str, Any]: ...

    async def quitar(self, negocio_id: UUID, coleccion: str, fila_id: UUID) -> bool: ...


class ConsultaRuc(Protocol):
    """Lo que el SRI publica de un RUC: el contribuyente y sus establecimientos.

    Lanza `NoEncontrado` si el SRI no lo conoce y `EstadoInvalido` (o su subtipo
    `ServicioNoDisponible`) si no se pudo consultar: el llamador manda a llenar los datos a mano.
    """

    async def consultar(self, ruc: str) -> tuple[dict[str, Any], list[dict[str, Any]]]: ...


class HistorialContratos(Protocol):
    """Los contratos públicos atribuidos a un RUC, resumidos como propuesta para el perfil."""

    async def consultar(self, ruc: str, razon_social: str) -> dict[str, Any]: ...


# Extraer el texto de un PDF. Es una función pura y síncrona (trabajo de CPU): el caso de uso la
# manda a un hilo. Basta un `Callable`; un protocolo de un solo método no añadiría nada.
ExtractorTextoPdf = Callable[[bytes], str]
