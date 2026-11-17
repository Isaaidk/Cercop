"""Contratos adjudicados por RUC (migración 0047): lectura por RUC y reemplazo mensual.

Son datos públicos sin `negocio_id`: no pasan por `contexto_negocio`.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

_LOTE = 2000


class RepositorioContratos:
    def __init__(self, motor: AsyncEngine) -> None:
        self._motor = motor

    async def ultima_importacion(self) -> datetime | None:
        async with self._motor.connect() as conexion:
            valor = (
                await conexion.execute(text("SELECT terminado_en FROM contrato_importacion"))
            ).scalar_one_or_none()
        return valor if isinstance(valor, datetime) else None

    async def proveedores_importados(self) -> int:
        async with self._motor.connect() as conexion:
            valor = (
                await conexion.execute(text("SELECT proveedores FROM contrato_importacion"))
            ).scalar_one_or_none()
        return int(valor or 0)

    async def resumen(
        self, ruc: str
    ) -> tuple[dict[str, Any], dict[str, str], dict[int, str]] | None:
        """El resumen del RUC con los nombres de sus CPC y de sus entidades, o `None`."""
        async with self._motor.connect() as conexion:
            crudo = (
                await conexion.execute(
                    text("SELECT datos FROM contrato_proveedor WHERE ruc = :ruc"), {"ruc": ruc}
                )
            ).scalar_one_or_none()
            if crudo is None:
                return None
            datos: dict[str, Any] = json.loads(crudo)
            codigos = sorted(
                {str(c) for c, _ in datos.get("cpc") or []}
                | {str(e[3]) for e in datos.get("experiencia") or [] if e[3]}
            )
            ids = sorted(
                {int(e) for e, _ in datos.get("entidades") or []}
                | {int(e[0]) for e in datos.get("experiencia") or []}
            )
            cpc = {
                fila[0]: fila[1]
                for fila in (
                    await conexion.execute(
                        text(
                            "SELECT codigo, descripcion FROM contrato_cpc "
                            "WHERE codigo = ANY(:codigos)"
                        ),
                        {"codigos": codigos},
                    )
                ).all()
            }
            entidades = {
                int(fila[0]): fila[1]
                for fila in (
                    await conexion.execute(
                        text("SELECT id, nombre FROM contrato_entidad WHERE id = ANY(:ids)"),
                        {"ids": ids},
                    )
                ).all()
            }
        return datos, cpc, entidades

    async def reemplazar(
        self,
        *,
        proveedores: Sequence[tuple[str, str]],
        cpc: Sequence[tuple[str, str]],
        entidades: Sequence[tuple[int, str]],
        anios: str,
    ) -> None:
        """Cambia todo de una vez: quien consulta ve el conjunto anterior o el nuevo, nunca mezcla.

        Los ids de las entidades se reasignan en cada importación, por eso no se actualiza por
        partes. `TRUNCATE` y no `DELETE`: devuelve el espacio en el acto, en vez de dejar un mes de
        filas muertas que duplicarían lo que ocupa (permiso dado en la migración 0047). Bloquea las
        lecturas los pocos segundos de la transacción; las consultas esperan, no fallan.
        """
        async with self._motor.begin() as conexion:
            await conexion.execute(
                text("TRUNCATE contrato_proveedor, contrato_cpc, contrato_entidad")
            )
            for inicio in range(0, len(cpc), _LOTE):
                await conexion.execute(
                    text("INSERT INTO contrato_cpc (codigo, descripcion) VALUES (:c, :d)"),
                    [{"c": c, "d": d} for c, d in cpc[inicio : inicio + _LOTE]],
                )
            for inicio in range(0, len(entidades), _LOTE):
                await conexion.execute(
                    text("INSERT INTO contrato_entidad (id, nombre) VALUES (:i, :n)"),
                    [{"i": i, "n": n} for i, n in entidades[inicio : inicio + _LOTE]],
                )
            for inicio in range(0, len(proveedores), _LOTE):
                await conexion.execute(
                    text("INSERT INTO contrato_proveedor (ruc, datos) VALUES (:r, :d)"),
                    [{"r": r, "d": d} for r, d in proveedores[inicio : inicio + _LOTE]],
                )
            await conexion.execute(
                text(
                    "INSERT INTO contrato_importacion (id, terminado_en, anios, proveedores) "
                    "VALUES (1, now(), :anios, :n) ON CONFLICT (id) DO UPDATE SET "
                    "terminado_en = now(), anios = EXCLUDED.anios, "
                    "proveedores = EXCLUDED.proveedores"
                ),
                {"anios": anios, "n": len(proveedores)},
            )
