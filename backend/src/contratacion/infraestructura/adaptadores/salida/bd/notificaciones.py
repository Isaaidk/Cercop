"""Suscripciones a notificaciones web y avisos pendientes de notificar.

Lo que hace la persona (suscribirse, darse de baja) va con el contexto de su empresa, como todo.
Lo que hace el worker —recorrer las suscripciones y los avisos sin notificar de todas las empresas—
pasa por las funciones `SECURITY DEFINER` de la migración 0046, y lo que escribe después (marcar
notificado, crear avisos) vuelve a ir con el contexto de cada empresa.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from contratacion.infraestructura.adaptadores.salida.bd.contexto import (
    contexto_negocio,
    sin_contexto,
)

# Tras tantos fallos seguidos que no son «ya no existe», la suscripción se da por muerta.
MAX_FALLOS = 5


class RepositorioNotificaciones:
    def __init__(self, motor: AsyncEngine) -> None:
        self._motor = motor

    # --- Lo que hace la persona ------------------------------------------------------------------

    async def guardar_suscripcion(
        self,
        *,
        negocio_id: UUID,
        usuario_id: UUID,
        endpoint: str,
        p256dh: str,
        auth: str,
        avisar_perfil: bool,
    ) -> None:
        """Alta o actualización. El mismo navegador (endpoint) siempre es una sola fila.

        Si ese endpoint era de otra persona (dos cuentas en la misma computadora), pasa a quien se
        acaba de suscribir: el navegador solo puede tener una suscripción.
        """
        async with sin_contexto(self._motor) as conexion:
            # Si ese navegador estaba a nombre de otra cuenta (quizá de otra empresa), deja de
            # estarlo: si no, a esta persona le llegarían las oportunidades de la otra. Borrar una
            # fila ajena necesita saltar el aislamiento: lo hace una función de la migración 0046
            # que solo toca las filas con ese mismo endpoint.
            await conexion.execute(
                text("SELECT soltar_endpoint_ajeno(:endpoint, :negocio_id, :usuario_id)"),
                {"endpoint": endpoint, "negocio_id": negocio_id, "usuario_id": usuario_id},
            )
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            await conexion.execute(
                text(
                    """
                    INSERT INTO suscripcion_push
                        (negocio_id, usuario_id, endpoint, p256dh, auth, avisar_perfil)
                    VALUES (:negocio_id, :usuario_id, :endpoint, :p256dh, :auth, :avisar_perfil)
                    ON CONFLICT (endpoint) DO UPDATE SET
                        p256dh = EXCLUDED.p256dh,
                        auth = EXCLUDED.auth,
                        avisar_perfil = EXCLUDED.avisar_perfil,
                        fallos = 0
                    """
                ),
                {
                    "negocio_id": negocio_id,
                    "usuario_id": usuario_id,
                    "endpoint": endpoint,
                    "p256dh": p256dh,
                    "auth": auth,
                    "avisar_perfil": avisar_perfil,
                },
            )

    async def quitar_suscripcion(
        self, *, negocio_id: UUID, usuario_id: UUID, endpoint: str
    ) -> bool:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            resultado = await conexion.execute(
                text(
                    "DELETE FROM suscripcion_push WHERE endpoint = :endpoint "
                    "AND negocio_id = :negocio_id AND usuario_id = :usuario_id"
                ),
                {"endpoint": endpoint, "negocio_id": negocio_id, "usuario_id": usuario_id},
            )
        return bool(resultado.rowcount)

    async def estado(self, *, negocio_id: UUID, usuario_id: UUID, endpoint: str) -> dict[str, Any]:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            fila = (
                (
                    await conexion.execute(
                        text(
                            "SELECT avisar_perfil FROM suscripcion_push WHERE endpoint = :endpoint "
                            "AND negocio_id = :negocio_id AND usuario_id = :usuario_id"
                        ),
                        {"endpoint": endpoint, "negocio_id": negocio_id, "usuario_id": usuario_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if fila is None:
            return {"suscrito": False, "avisar_perfil": False}
        return {"suscrito": True, "avisar_perfil": bool(fila["avisar_perfil"])}

    # --- Lo que hace el worker -------------------------------------------------------------------

    async def suscripciones(self) -> list[dict[str, Any]]:
        async with sin_contexto(self._motor) as conexion:
            filas = (
                (await conexion.execute(text("SELECT * FROM suscripciones_push_activas()")))
                .mappings()
                .all()
            )
        return [dict(fila) for fila in filas]

    async def avisos_por_notificar(self, tope: int = 500) -> list[dict[str, Any]]:
        async with sin_contexto(self._motor) as conexion:
            filas = (
                (
                    await conexion.execute(
                        text("SELECT * FROM avisos_por_notificar(:tope)"), {"tope": tope}
                    )
                )
                .mappings()
                .all()
            )
        return [dict(fila) for fila in filas]

    async def marcar_notificados(
        self, *, negocio_id: UUID, ids: list[UUID], momento: datetime
    ) -> None:
        if not ids:
            return
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            await conexion.execute(
                text(
                    "UPDATE aviso SET notificado_en = :momento "
                    "WHERE negocio_id = :negocio_id AND id = ANY(CAST(:ids AS uuid[]))"
                ),
                {"negocio_id": negocio_id, "ids": [str(i) for i in ids], "momento": momento},
            )

    async def anotar_resultado(
        self, *, negocio_id: UUID, suscripcion_id: UUID, ok: bool, caducada: bool
    ) -> None:
        """Éxito: contador a cero. Caducada (404/410): se borra. Otro fallo: suma uno."""
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            if caducada:
                await conexion.execute(
                    text("DELETE FROM suscripcion_push WHERE id = :id AND negocio_id = :negocio"),
                    {"id": suscripcion_id, "negocio": negocio_id},
                )
                return
            await conexion.execute(
                text(
                    """
                    UPDATE suscripcion_push SET fallos = CASE WHEN :ok THEN 0 ELSE fallos + 1 END
                    WHERE id = :id AND negocio_id = :negocio
                    """
                ),
                {"id": suscripcion_id, "negocio": negocio_id, "ok": ok},
            )
            await conexion.execute(
                text(
                    "DELETE FROM suscripcion_push WHERE id = :id AND negocio_id = :negocio "
                    "AND fallos >= :maximo"
                ),
                {"id": suscripcion_id, "negocio": negocio_id, "maximo": MAX_FALLOS},
            )

    async def anotar_perfil_revisado(
        self, *, negocio_id: UUID, usuario_id: UUID, momento: datetime
    ) -> None:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            await conexion.execute(
                text(
                    "UPDATE suscripcion_push SET perfil_revisado_en = :momento "
                    "WHERE negocio_id = :negocio_id AND usuario_id = :usuario_id"
                ),
                {"negocio_id": negocio_id, "usuario_id": usuario_id, "momento": momento},
            )

    async def crear_avisos_de_perfil(
        self,
        *,
        negocio_id: UUID,
        usuario_id: UUID,
        avisos: list[dict[str, Any]],
        ya_notificados: bool,
    ) -> int:
        """Avisos `origen='perfil'`; un proceso nunca se avisa dos veces a la misma persona.

        `ya_notificados`: la primera vuelta tras suscribirse guarda lo que ya estaba abierto sin
        mandar notificación (si no, la persona recibiría decenas de golpe al activarlas). Esos
        avisos siguen apareciendo en el panel.
        """
        if not avisos:
            return 0
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            resultado = await conexion.execute(
                text(
                    """
                    INSERT INTO aviso (
                        negocio_id, usuario_id, registro_id, titulo, detalle, puntuacion, origen,
                        notificado_en
                    )
                    SELECT :negocio_id, :usuario_id, a.registro_id, a.titulo, a.detalle,
                           a.puntuacion, 'perfil', CASE WHEN :silencio THEN now() END
                    FROM jsonb_to_recordset(CAST(:avisos AS jsonb)) AS a(
                        registro_id uuid, titulo text, detalle text, puntuacion integer
                    )
                    ON CONFLICT (usuario_id, registro_id) WHERE origen = 'perfil' DO NOTHING
                    """
                ),
                {
                    "negocio_id": negocio_id,
                    "usuario_id": usuario_id,
                    "silencio": ya_notificados,
                    "avisos": json.dumps(avisos, default=str),
                },
            )
        return int(getattr(resultado, "rowcount", 0) or 0)
