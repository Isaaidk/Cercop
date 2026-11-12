"""Conversaciones del asistente: guardadas por empresa (RLS) y por persona (filtro explícito).

Los topes se aplican al escribir y en la misma transacción que la escritura: así la tabla nunca
pasa de 200 mensajes por conversación ni de 50 conversaciones por persona, sin depender de una
tarea de limpieza que alguien tenga que acordarse de programar.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from contratacion.dominio.errores import NoEncontrado
from contratacion.infraestructura.adaptadores.salida.bd.contexto import contexto_negocio

MAX_MENSAJES = 200
MAX_CONVERSACIONES = 50

_COLUMNAS_CONVERSACION = "id, titulo, actualizada_en"


def _lista(valor: Any) -> list[Any]:
    if isinstance(valor, str):
        try:
            valor = json.loads(valor)
        except ValueError:
            return []
    return list(valor) if isinstance(valor, list) else []


def _mensaje(fila: Any) -> dict[str, Any]:
    datos = dict(fila)
    datos["tarjetas"] = _lista(datos.get("tarjetas"))
    datos["sugerencias"] = _lista(datos.get("sugerencias"))
    return datos


class RepositorioConversacionesBd:
    def __init__(
        self,
        motor: AsyncEngine,
        *,
        max_mensajes: int = MAX_MENSAJES,
        max_conversaciones: int = MAX_CONVERSACIONES,
    ) -> None:
        self._motor = motor
        self._max_mensajes = max_mensajes
        self._max_conversaciones = max_conversaciones

    async def listar(
        self, *, negocio_id: UUID, usuario_id: UUID, limite: int = 50
    ) -> list[dict[str, Any]]:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            filas = (
                (
                    await conexion.execute(
                        text(
                            f"""
                            SELECT {_COLUMNAS_CONVERSACION} FROM asistente_conversaciones
                            WHERE negocio_id = :negocio AND usuario_id = :usuario
                            ORDER BY actualizada_en DESC
                            LIMIT :limite
                            """
                        ),
                        {"negocio": negocio_id, "usuario": usuario_id, "limite": limite},
                    )
                )
                .mappings()
                .all()
            )
        return [dict(fila) for fila in filas]

    async def obtener(
        self, *, negocio_id: UUID, usuario_id: UUID, conversacion_id: UUID
    ) -> dict[str, Any] | None:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            fila = (
                (
                    await conexion.execute(
                        text(
                            f"""
                            SELECT {_COLUMNAS_CONVERSACION} FROM asistente_conversaciones
                            WHERE id = :id AND negocio_id = :negocio AND usuario_id = :usuario
                            """
                        ),
                        {"id": conversacion_id, "negocio": negocio_id, "usuario": usuario_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return dict(fila) if fila else None

    async def mensajes(
        self, *, negocio_id: UUID, usuario_id: UUID, conversacion_id: UUID, limite: int = 200
    ) -> list[dict[str, Any]]:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            filas = (
                (
                    await conexion.execute(
                        text(
                            """
                            SELECT * FROM (
                                SELECT m.id, m.rol, m.texto, m.tarjetas, m.sugerencias, m.creado_en
                                FROM asistente_mensajes m
                                JOIN asistente_conversaciones c ON c.id = m.conversacion_id
                                WHERE m.conversacion_id = :id
                                  AND c.negocio_id = :negocio AND c.usuario_id = :usuario
                                ORDER BY m.creado_en DESC
                                LIMIT :limite
                            ) ultimos
                            ORDER BY creado_en
                            """
                        ),
                        {
                            "id": conversacion_id,
                            "negocio": negocio_id,
                            "usuario": usuario_id,
                            "limite": limite,
                        },
                    )
                )
                .mappings()
                .all()
            )
        return [_mensaje(fila) for fila in filas]

    async def crear(self, *, negocio_id: UUID, usuario_id: UUID, titulo: str) -> dict[str, Any]:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            fila = (
                (
                    await conexion.execute(
                        text(
                            f"""
                            INSERT INTO asistente_conversaciones (negocio_id, usuario_id, titulo)
                            VALUES (:negocio, :usuario, :titulo)
                            RETURNING {_COLUMNAS_CONVERSACION}
                            """
                        ),
                        {"negocio": negocio_id, "usuario": usuario_id, "titulo": titulo},
                    )
                )
                .mappings()
                .one()
            )
            # Las más antiguas por encima del tope se van con sus mensajes (ON DELETE CASCADE).
            await conexion.execute(
                text(
                    """
                    DELETE FROM asistente_conversaciones
                    WHERE id IN (
                        SELECT id FROM asistente_conversaciones
                        WHERE negocio_id = :negocio AND usuario_id = :usuario
                        ORDER BY actualizada_en DESC, creada_en DESC
                        OFFSET :tope
                    )
                    """
                ),
                {"negocio": negocio_id, "usuario": usuario_id, "tope": self._max_conversaciones},
            )
        return dict(fila)

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
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            # El `UPDATE` comprueba de paso que la conversación es de esta persona: sin fila
            # tocada, el mensaje no se guarda.
            tocada = (
                await conexion.execute(
                    text(
                        """
                        UPDATE asistente_conversaciones SET actualizada_en = now()
                        WHERE id = :id AND negocio_id = :negocio AND usuario_id = :usuario
                        RETURNING id
                        """
                    ),
                    {"id": conversacion_id, "negocio": negocio_id, "usuario": usuario_id},
                )
            ).scalar_one_or_none()
            if tocada is None:
                raise NoEncontrado("Esa conversación no está.")
            fila = (
                (
                    await conexion.execute(
                        text(
                            """
                            INSERT INTO asistente_mensajes (
                                conversacion_id, negocio_id, rol, texto, tarjetas, sugerencias
                            )
                            VALUES (
                                :conversacion, :negocio, :rol, :texto,
                                CAST(:tarjetas AS jsonb), CAST(:sugerencias AS jsonb)
                            )
                            RETURNING id, rol, texto, tarjetas, sugerencias, creado_en
                            """
                        ),
                        {
                            "conversacion": conversacion_id,
                            "negocio": negocio_id,
                            "rol": rol,
                            "texto": texto,
                            "tarjetas": json.dumps(tarjetas, ensure_ascii=False),
                            "sugerencias": json.dumps(sugerencias, ensure_ascii=False),
                        },
                    )
                )
                .mappings()
                .one()
            )
            await conexion.execute(
                text(
                    """
                    DELETE FROM asistente_mensajes
                    WHERE id IN (
                        SELECT id FROM asistente_mensajes
                        WHERE conversacion_id = :conversacion
                        ORDER BY creado_en DESC
                        OFFSET :tope
                    )
                    """
                ),
                {"conversacion": conversacion_id, "tope": self._max_mensajes},
            )
        return _mensaje(fila)

    async def renombrar(
        self, *, negocio_id: UUID, usuario_id: UUID, conversacion_id: UUID, titulo: str
    ) -> dict[str, Any] | None:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            fila = (
                (
                    await conexion.execute(
                        text(
                            f"""
                            UPDATE asistente_conversaciones SET titulo = :titulo
                            WHERE id = :id AND negocio_id = :negocio AND usuario_id = :usuario
                            RETURNING {_COLUMNAS_CONVERSACION}
                            """
                        ),
                        {
                            "id": conversacion_id,
                            "negocio": negocio_id,
                            "usuario": usuario_id,
                            "titulo": titulo,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
        return dict(fila) if fila else None

    async def borrar(self, *, negocio_id: UUID, usuario_id: UUID, conversacion_id: UUID) -> bool:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            resultado = await conexion.execute(
                text(
                    """
                    DELETE FROM asistente_conversaciones
                    WHERE id = :id AND negocio_id = :negocio AND usuario_id = :usuario
                    """
                ),
                {"id": conversacion_id, "negocio": negocio_id, "usuario": usuario_id},
            )
        return bool(getattr(resultado, "rowcount", 0))
