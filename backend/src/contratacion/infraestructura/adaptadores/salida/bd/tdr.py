"""Cola de TDR. La fila es el pedido; el archivo está en disco.

Pedir dos veces el mismo documento no crea dos filas: la clave es `(registro_id, nombre)`. El
worker toma las que están en `pendiente`. La API no descarga nada.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from contratacion.aplicacion.hilos import MemoLru
from contratacion.infraestructura.adaptadores.salida.bd.contexto import (
    contexto_negocio,
    sin_contexto,
)

# Proceso → fuente. Público e inmutable: se comparte entre empresas sin riesgo.
_FUENTES: MemoLru[UUID, str] = MemoLru(20_000)


class RepositorioTdr:
    def __init__(self, motor: AsyncEngine) -> None:
        self._motor = motor

    async def documentos_del_registro(self, registro_id: UUID) -> list[dict[str, Any]]:
        async with sin_contexto(self._motor) as conexion:
            fila = (
                (
                    await conexion.execute(
                        text(
                            """
                        SELECT documentos, cpc_codigos, provincia, datos
                        FROM registro WHERE id = :id
                        """
                        ),
                        {"id": registro_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if fila is None:
            return []
        documentos = fila["documentos"] or []
        if isinstance(documentos, str):
            documentos = json.loads(documentos)
        return list(documentos)

    async def fuente_de(self, registro_id: UUID) -> str | None:
        """Fuente (`NCO`, `OCDS`) de un proceso, para comprobar la vista de quien lo pide.

        Un proceso no cambia de fuente, así que se recuerda en el proceso (LRU acotada, dato
        público): el estado del TDR se sondea cada pocos segundos y esto no puede costar una
        consulta en cada sondeo.
        """
        conocida = _FUENTES.get(registro_id)
        if conocida is not None:
            return str(conocida)
        async with sin_contexto(self._motor) as conexion:
            codigo = (
                await conexion.execute(
                    text(
                        "SELECT f.codigo FROM registro r JOIN fuente f ON f.id = r.fuente_id "
                        "WHERE r.id = :id"
                    ),
                    {"id": registro_id},
                )
            ).scalar_one_or_none()
        if codigo is not None:
            _FUENTES[registro_id] = str(codigo)
        return str(codigo) if codigo is not None else None

    async def registro(self, registro_id: UUID) -> dict[str, Any] | None:
        async with sin_contexto(self._motor) as conexion:
            fila = (
                (
                    await conexion.execute(
                        text(
                            """
                        SELECT r.id, r.documentos, r.cpc_codigos, r.provincia, r.datos,
                               f.codigo AS fuente
                        FROM registro r
                        LEFT JOIN fuente f ON f.id = r.fuente_id
                        WHERE r.id = :id
                        """
                        ),
                        {"id": registro_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return dict(fila) if fila else None

    async def pedir(self, registro_id: UUID, documento: dict[str, Any]) -> str:
        """Inserta el pedido si no existe. Devuelve el estado actual."""
        async with sin_contexto(self._motor) as conexion:
            await conexion.execute(
                text(
                    """
                    INSERT INTO documento_tdr (registro_id, nombre, url_origen, campos_pedido)
                    VALUES (:registro_id, :nombre, :url, CAST(:campos AS jsonb))
                    ON CONFLICT (registro_id, nombre) DO NOTHING
                    """
                ),
                {
                    "registro_id": registro_id,
                    "nombre": documento.get("nombre") or "tdr",
                    "url": documento.get("enlace") or "",
                    "campos": json.dumps(documento.get("campos_pedido") or []),
                },
            )
            estado: Any = (
                await conexion.execute(
                    text(
                        """
                        SELECT estado FROM documento_tdr
                        WHERE registro_id = :registro_id AND nombre = :nombre
                        """
                    ),
                    {"registro_id": registro_id, "nombre": documento.get("nombre") or "tdr"},
                )
            ).scalar_one()
        return str(estado)

    async def listar(self, registro_id: UUID) -> list[dict[str, Any]]:
        async with sin_contexto(self._motor) as conexion:
            filas = (
                (
                    await conexion.execute(
                        text(
                            """
                        SELECT id, nombre, estado, mime, tamano_bytes, sha256, ruta, error,
                               expira_en, campos_pedido, pedido_en
                        FROM documento_tdr WHERE registro_id = :id
                        """
                        ),
                        {"id": registro_id},
                    )
                )
                .mappings()
                .all()
            )
        return [dict(fila) for fila in filas]

    async def tomar_pendiente(self) -> dict[str, Any] | None:
        pedidos = await self.tomar_pendientes(1)
        return pedidos[0] if pedidos else None

    async def tomar_pendientes(self, limite: int) -> list[dict[str, Any]]:
        """Los pedidos más antiguos sin atender, por orden de llegada, y **reservados**.

        Antes solo se leían: con dos réplicas del worker, las dos bajaban el mismo archivo a la
        vez. Ahora se reservan en la misma sentencia (`FOR UPDATE SKIP LOCKED` + `tomado_en`): otra
        réplica salta las filas que esta ya tiene y toma las siguientes. El estado sigue siendo
        `pendiente` —el panel no ve ningún estado nuevo— y la reserva caduca a los diez minutos,
        por si el worker que la tomó murió a mitad de la bajada.
        """
        async with sin_contexto(self._motor) as conexion:
            filas = (
                (
                    await conexion.execute(
                        text(
                            """
                        UPDATE documento_tdr AS d SET tomado_en = now()
                        FROM (
                            SELECT id FROM documento_tdr
                            WHERE estado = 'pendiente'
                              AND (tomado_en IS NULL OR tomado_en < now() - interval '10 minutes')
                            ORDER BY pedido_en, id
                            LIMIT :limite
                            FOR UPDATE SKIP LOCKED
                        ) AS elegidos
                        WHERE d.id = elegidos.id
                        RETURNING d.id, d.registro_id, d.nombre, d.url_origen, d.pedido_en
                        """
                        ),
                        {"limite": limite},
                    )
                )
                .mappings()
                .all()
            )
        # `RETURNING` no garantiza orden: se vuelve a poner el de llegada.
        return sorted((dict(fila) for fila in filas), key=lambda f: (f["pedido_en"], str(f["id"])))

    async def contar_pendientes(self) -> int:
        async with sin_contexto(self._motor) as conexion:
            return int(
                (
                    await conexion.execute(
                        text("SELECT count(*) FROM documento_tdr WHERE estado = 'pendiente'")
                    )
                ).scalar_one()
            )

    async def marcar_listo(
        self, documento_id: UUID, *, sha256: str, ruta: str, tamano: int, mime: str
    ) -> None:
        async with sin_contexto(self._motor) as conexion:
            await conexion.execute(
                text(
                    """
                    UPDATE documento_tdr
                       SET estado = 'listo', sha256 = :sha, ruta = :ruta, tamano_bytes = :tamano,
                           mime = :mime, descargado_en = now(),
                           expira_en = now() + interval '1 day', error = NULL
                     WHERE id = :id
                    """
                ),
                {
                    "id": documento_id,
                    "sha": sha256,
                    "ruta": ruta,
                    "tamano": tamano,
                    "mime": mime,
                },
            )

    async def marcar_error(self, documento_id: UUID, error: str) -> None:
        async with sin_contexto(self._motor) as conexion:
            await conexion.execute(
                text(
                    """
                    UPDATE documento_tdr SET estado = 'error', error = :error WHERE id = :id
                    """
                ),
                {"id": documento_id, "error": error[:500]},
            )

    async def reabrir(self, documento_id: UUID) -> None:
        """El archivo temporal venció: el worker vuelve a bajarlo."""
        async with sin_contexto(self._motor) as conexion:
            await conexion.execute(
                text(
                    """
                    UPDATE documento_tdr
                       SET estado = 'pendiente', error = NULL, ruta = NULL, expira_en = NULL,
                           pedido_en = now(), tomado_en = NULL
                     WHERE id = :id
                    """
                ),
                {"id": documento_id},
            )

    async def reabrir_fallidos(self, registro_id: UUID) -> None:
        """Un intento nuevo después de un error. No toca los que ya están listos."""
        async with sin_contexto(self._motor) as conexion:
            await conexion.execute(
                text(
                    """
                    UPDATE documento_tdr
                       SET estado = 'pendiente', error = NULL, pedido_en = now(), tomado_en = NULL
                     WHERE registro_id = :id AND estado = 'error'
                    """
                ),
                {"id": registro_id},
            )

    async def uno(self, documento_id: UUID) -> dict[str, Any] | None:
        async with sin_contexto(self._motor) as conexion:
            fila = (
                (
                    await conexion.execute(
                        text("SELECT * FROM documento_tdr WHERE id = :id"),
                        {"id": documento_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return dict(fila) if fila else None

    async def auditar(self, negocio_id: UUID, usuario_id: UUID, registro_id: UUID) -> None:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            await conexion.execute(
                text(
                    """
                    INSERT INTO auditoria (
                        negocio_id, usuario_id, accion, entidad, entidad_id, resultado
                    )
                    VALUES (:negocio_id, :usuario_id, 'tdr.ver', 'registro', :entidad_id, 'ok')
                    """
                ),
                {
                    "negocio_id": negocio_id,
                    "usuario_id": usuario_id,
                    "entidad_id": str(registro_id),
                },
            )
