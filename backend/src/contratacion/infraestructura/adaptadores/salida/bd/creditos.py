"""Saldo de créditos de IA, consumo y solicitudes de compra.

El descuento es un `UPDATE ... WHERE disponibles >= :n`: dos peticiones a la vez no pueden gastar
el mismo crédito, porque la segunda ve el saldo ya rebajado y no encuentra fila.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from contratacion.dominio.creditos import REGALO_INICIAL, Paquete
from contratacion.dominio.errores import EstadoInvalido, NoEncontrado, SinCreditos
from contratacion.infraestructura.adaptadores.salida.bd.contexto import (
    contexto_negocio,
    sin_contexto,
)

_ABRIR = text(
    """
    WITH nuevo AS (
        INSERT INTO saldo_ia (negocio_id, disponibles) VALUES (:negocio, :regalo)
        ON CONFLICT (negocio_id) DO NOTHING
        RETURNING negocio_id
    )
    INSERT INTO movimiento_ia (negocio_id, tipo, cantidad, motivo)
    SELECT negocio_id, 'regalo', :regalo, 'Créditos de bienvenida' FROM nuevo
    """
)


class RepositorioCreditos:
    def __init__(self, motor: AsyncEngine) -> None:
        self._motor = motor

    async def saldo(self, negocio_id: UUID) -> dict[str, Any]:
        leer_saldo = text(
            "SELECT disponibles, usados, actualizado_en FROM saldo_ia WHERE negocio_id = :negocio"
        )
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            # Se lee primero y solo se abre el saldo si aún no existe. Antes cada lectura del saldo
            # (el inicio del asistente, la pantalla de créditos) empezaba por un `INSERT … ON
            # CONFLICT DO NOTHING`: una escritura intentada en cada consulta para algo que pasa una
            # vez en la vida de la empresa. Si dos peticiones llegan a la vez la primera vez, el
            # `ON CONFLICT` sigue garantizando un solo saldo y un solo regalo.
            fila = (await conexion.execute(leer_saldo, {"negocio": negocio_id})).mappings().first()
            if fila is None:
                await conexion.execute(_ABRIR, {"negocio": negocio_id, "regalo": REGALO_INICIAL})
                fila = (
                    (await conexion.execute(leer_saldo, {"negocio": negocio_id})).mappings().one()
                )
            compras = (
                (
                    await conexion.execute(
                        text(
                            """
                        SELECT id, paquete, creditos, precio_usd, estado, creado_en, resuelto_en
                        FROM compra_ia WHERE negocio_id = :negocio
                        ORDER BY creado_en DESC LIMIT 10
                        """
                        ),
                        {"negocio": negocio_id},
                    )
                )
                .mappings()
                .all()
            )
        return {**dict(fila), "compras": [dict(c) for c in compras]}

    async def movimientos(self, negocio_id: UUID, limite: int = 50) -> list[dict[str, Any]]:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            filas = (
                (
                    await conexion.execute(
                        text(
                            """
                        SELECT tipo, cantidad, motivo, creado_en FROM movimiento_ia
                        WHERE negocio_id = :negocio ORDER BY creado_en DESC LIMIT :limite
                        """
                        ),
                        {"negocio": negocio_id, "limite": limite},
                    )
                )
                .mappings()
                .all()
            )
        return [dict(f) for f in filas]

    async def consumir(
        self, negocio_id: UUID, usuario_id: UUID | None, cantidad: int, motivo: str
    ) -> int:
        """Descuenta o lanza `SinCreditos`. Devuelve lo que queda."""
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            await conexion.execute(_ABRIR, {"negocio": negocio_id, "regalo": REGALO_INICIAL})
            queda = (
                await conexion.execute(
                    text(
                        """
                        UPDATE saldo_ia SET disponibles = disponibles - :n,
                               usados = usados + :n, actualizado_en = now()
                        WHERE negocio_id = :negocio AND disponibles >= :n
                        RETURNING disponibles
                        """
                    ),
                    {"negocio": negocio_id, "n": cantidad},
                )
            ).scalar_one_or_none()
            if queda is None:
                raise SinCreditos(
                    "Se acabaron los créditos de IA de tu empresa. Compra un paquete para seguir."
                )
            await conexion.execute(
                text(
                    """
                    INSERT INTO movimiento_ia (negocio_id, usuario_id, tipo, cantidad, motivo)
                    VALUES (:negocio, :usuario, 'consumo', :n, :motivo)
                    """
                ),
                {"negocio": negocio_id, "usuario": usuario_id, "n": -cantidad, "motivo": motivo},
            )
        return int(queda)

    async def devolver(self, negocio_id: UUID, cantidad: int, motivo: str) -> None:
        """Repone lo cobrado cuando el modelo falló después del descuento."""
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            await conexion.execute(
                text(
                    """
                    UPDATE saldo_ia SET disponibles = disponibles + :n,
                           usados = GREATEST(usados - :n, 0), actualizado_en = now()
                    WHERE negocio_id = :negocio
                    """
                ),
                {"negocio": negocio_id, "n": cantidad},
            )
            await conexion.execute(
                text(
                    "INSERT INTO movimiento_ia (negocio_id, tipo, cantidad, motivo) "
                    "VALUES (:negocio, 'ajuste', :n, :motivo)"
                ),
                {"negocio": negocio_id, "n": cantidad, "motivo": motivo},
            )

    async def solicitar_compra(
        self, negocio_id: UUID, usuario_id: UUID, elegido: Paquete
    ) -> dict[str, Any]:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            pendientes: Any = (
                await conexion.execute(
                    text(
                        "SELECT count(*) FROM compra_ia "
                        "WHERE negocio_id = :negocio AND estado = 'pendiente'"
                    ),
                    {"negocio": negocio_id},
                )
            ).scalar_one()
            if pendientes >= 3:
                raise EstadoInvalido(
                    "Ya tienes tres compras esperando confirmación. Espera a que se resuelvan."
                )
            fila = (
                (
                    await conexion.execute(
                        text(
                            """
                        INSERT INTO compra_ia
                            (negocio_id, usuario_id, paquete, creditos, precio_usd)
                        VALUES (:negocio, :usuario, :paquete, :creditos, :precio)
                        RETURNING id, paquete, creditos, precio_usd, estado, creado_en
                        """
                        ),
                        {
                            "negocio": negocio_id,
                            "usuario": usuario_id,
                            "paquete": elegido.codigo,
                            "creditos": elegido.creditos,
                            "precio": elegido.precio_usd,
                        },
                    )
                )
                .mappings()
                .one()
            )
        return dict(fila)

    async def compras_pendientes(self) -> list[dict[str, Any]]:
        async with sin_contexto(self._motor) as conexion:
            filas = (
                (await conexion.execute(text("SELECT * FROM compras_ia_pendientes()")))
                .mappings()
                .all()
            )
        return [
            {
                "id": f["id_compra"],
                "negocio_id": f["id_negocio"],
                "negocio": f["nombre_empresa"],
                "paquete": f["paquete_compra"],
                "creditos": f["creditos_compra"],
                "precio_usd": f["precio_compra"],
                "creado_en": f["creada_en"],
            }
            for f in filas
        ]

    async def resolver_compra(
        self, negocio_id: UUID, compra_id: UUID, *, pagada: bool, por: UUID
    ) -> dict[str, Any]:
        """Confirma o anula. Al confirmar suma los créditos en la misma transacción."""
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            fila = (
                (
                    await conexion.execute(
                        text(
                            """
                        UPDATE compra_ia SET estado = :estado, resuelto_en = now(),
                               resuelto_por = :por
                        WHERE id = :id AND estado = 'pendiente'
                        RETURNING id, negocio_id, creditos, paquete, estado
                        """
                        ),
                        {"id": compra_id, "estado": "pagada" if pagada else "anulada", "por": por},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if fila is None:
                raise NoEncontrado("Esa compra no existe o ya se resolvió.")
            if pagada:
                await conexion.execute(
                    text(
                        """
                        INSERT INTO saldo_ia (negocio_id, disponibles) VALUES (:negocio, :n)
                        ON CONFLICT (negocio_id) DO UPDATE
                        SET disponibles = saldo_ia.disponibles + :n, actualizado_en = now()
                        """
                    ),
                    {"negocio": fila["negocio_id"], "n": fila["creditos"]},
                )
                await conexion.execute(
                    text(
                        "INSERT INTO movimiento_ia "
                        "(negocio_id, usuario_id, tipo, cantidad, motivo) "
                        "VALUES (:negocio, :por, 'compra', :n, :motivo)"
                    ),
                    {
                        "negocio": fila["negocio_id"],
                        "por": por,
                        "n": fila["creditos"],
                        "motivo": f"Paquete {fila['paquete']}",
                    },
                )
        return dict(fila)

    async def otorgar(
        self, negocio_id: UUID, cantidad: int, motivo: str, *, por: UUID
    ) -> dict[str, Any]:
        """Suma créditos a una empresa sin pasar por una compra y deja el movimiento anotado."""
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            existe = (
                await conexion.execute(
                    text("SELECT 1 FROM negocio WHERE id = :negocio"), {"negocio": negocio_id}
                )
            ).scalar_one_or_none()
            if existe is None:
                raise NoEncontrado("Esa empresa no existe.")
            disponibles = (
                await conexion.execute(
                    text(
                        """
                        INSERT INTO saldo_ia (negocio_id, disponibles) VALUES (:negocio, :n)
                        ON CONFLICT (negocio_id) DO UPDATE
                        SET disponibles = saldo_ia.disponibles + :n, actualizado_en = now()
                        RETURNING disponibles
                        """
                    ),
                    {"negocio": negocio_id, "n": cantidad},
                )
            ).scalar_one()
            await conexion.execute(
                text(
                    "INSERT INTO movimiento_ia (negocio_id, usuario_id, tipo, cantidad, motivo) "
                    "VALUES (:negocio, :por, 'ajuste', :n, :motivo)"
                ),
                {"negocio": negocio_id, "por": por, "n": cantidad, "motivo": motivo},
            )
        return {"negocio_id": negocio_id, "otorgados": cantidad, "disponibles": int(disponibles)}
