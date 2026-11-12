"""Perfil y lista de CPC recordados **durante una petición** del asistente.

El inicio del asistente y una respuesta del modelo leen el perfil varias veces: el saludo, las
propuestas, los datos para el modelo y alguna herramienta. Cada lectura del perfil son una docena
de consultas (la ficha y sus tablas), así que repetirla multiplicaba el trabajo de la base por
cada persona que abre el chat.

Estos envoltorios se crean con los servicios de **cada petición** y mueren con ella: no hay nada
compartido entre personas ni entre empresas, y no pueden servir un dato viejo más allá de esa
petición. Lecturas a la vez esperan a la primera en vez de repetirla. Cualquier escritura olvida
lo recordado.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any
from uuid import UUID

from contratacion.aplicacion.puertos.cpc import ClaveCpc, RepositorioCpc
from contratacion.aplicacion.puertos.perfil import RepositorioPerfil


class PerfilRecordado:
    """`RepositorioPerfil` que lee una vez por empresa y por petición."""

    def __init__(self, origen: RepositorioPerfil) -> None:
        self._origen = origen
        self._leidos: dict[UUID, dict[str, Any]] = {}
        self._cerrojo = asyncio.Lock()

    async def leer(self, negocio_id: UUID) -> dict[str, Any]:
        async with self._cerrojo:
            if negocio_id not in self._leidos:
                self._leidos[negocio_id] = await self._origen.leer(negocio_id)
            # Copia superficial: quien la reciba puede añadir claves sin tocar la recordada.
            return dict(self._leidos[negocio_id])

    async def guardar_identidad(self, negocio_id: UUID, campos: dict[str, Any]) -> None:
        self._leidos.pop(negocio_id, None)
        await self._origen.guardar_identidad(negocio_id, campos)

    async def agregar(
        self, negocio_id: UUID, coleccion: str, campos: dict[str, Any]
    ) -> dict[str, Any]:
        self._leidos.pop(negocio_id, None)
        return await self._origen.agregar(negocio_id, coleccion, campos)

    async def quitar(self, negocio_id: UUID, coleccion: str, fila_id: UUID) -> bool:
        self._leidos.pop(negocio_id, None)
        return await self._origen.quitar(negocio_id, coleccion, fila_id)


class CpcRecordado:
    """`RepositorioCpc` que lista una vez por empresa y por petición."""

    def __init__(self, origen: RepositorioCpc) -> None:
        self._origen = origen
        self._listas: dict[UUID, tuple[ClaveCpc, ...]] = {}
        self._cerrojo = asyncio.Lock()

    async def listar(self, *, negocio_id: UUID) -> tuple[ClaveCpc, ...]:
        async with self._cerrojo:
            if negocio_id not in self._listas:
                self._listas[negocio_id] = await self._origen.listar(negocio_id=negocio_id)
            return self._listas[negocio_id]

    async def agregar(
        self,
        *,
        negocio_id: UUID,
        texto: str,
        texto_normalizado: str,
        creado_por: UUID | None,
        momento: datetime,
    ) -> bool:
        self._listas.pop(negocio_id, None)
        return await self._origen.agregar(
            negocio_id=negocio_id,
            texto=texto,
            texto_normalizado=texto_normalizado,
            creado_por=creado_por,
            momento=momento,
        )

    async def quitar(self, *, negocio_id: UUID, texto_normalizado: str) -> bool:
        self._listas.pop(negocio_id, None)
        return await self._origen.quitar(negocio_id=negocio_id, texto_normalizado=texto_normalizado)

    async def limpiar(self, *, negocio_id: UUID) -> int:
        self._listas.pop(negocio_id, None)
        return await self._origen.limpiar(negocio_id=negocio_id)
