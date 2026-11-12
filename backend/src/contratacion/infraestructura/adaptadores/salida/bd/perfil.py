"""Lectura y escritura del perfil de una empresa.

Todas las consultas corren dentro del contexto RLS de esa empresa. Una fila de otra empresa no
sale aunque alguien pase su identificador: la política exige `app.negocio_id`.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from contratacion.infraestructura.adaptadores.salida.bd.contexto import contexto_negocio

_COLUMNAS_NEGOCIO = (
    "razon_social",
    "nombre_comercial",
    "tipo_persona",
    "ruc",
    "sitio_web",
    "estado_rup",
    "fecha_inicio_actividades",
    "obligado_contabilidad",
    "regimen_tributario",
    "email_contacto",
    "telefono",
    "direccion",
    "ciudad",
    "nombre",
    "presupuesto_min",
    "presupuesto_max",
    "capacidad_ejecucion",
)

_TABLAS = {
    "dedicaciones": "negocio_dedicacion",
    "contactos": "negocio_contacto",
    "actividades": "negocio_actividad",
    "cobertura": "negocio_cobertura",
    "documentos": "negocio_documento",
    "experiencia": "negocio_experiencia",
    "personal": "negocio_personal",
    "equipo": "negocio_equipo",
    "ofertas": "negocio_oferta",
    "palabras": "negocio_palabra",
}


class RepositorioPerfil:
    """Perfil de la empresa del actor."""

    def __init__(self, motor: AsyncEngine) -> None:
        self._motor = motor

    async def leer(self, negocio_id: UUID) -> dict[str, Any]:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            fila = (
                (
                    await conexion.execute(
                        text(
                            f"""
                            SELECT {", ".join(_COLUMNAS_NEGOCIO)}
                            FROM negocio WHERE id = :id
                            """
                        ),
                        {"id": negocio_id},
                    )
                )
                .mappings()
                .one()
            )
            perfil = {clave: fila[clave] for clave in _COLUMNAS_NEGOCIO}
            for nombre, tabla in _TABLAS.items():
                filas = (
                    (
                        await conexion.execute(
                            text(f"SELECT * FROM {tabla} WHERE negocio_id = :id ORDER BY id"),
                            {"id": negocio_id},
                        )
                    )
                    .mappings()
                    .all()
                )
                perfil[nombre] = [dict(item) for item in filas]
        return perfil

    async def guardar_identidad(self, negocio_id: UUID, campos: dict[str, Any]) -> None:
        asignables = {clave: valor for clave, valor in campos.items() if clave in _COLUMNAS_NEGOCIO}
        if not asignables:
            return
        conjuntos = ", ".join(f"{clave} = :{clave}" for clave in asignables)
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            await conexion.execute(
                text(f"UPDATE negocio SET {conjuntos} WHERE id = :id"),
                {**asignables, "id": negocio_id},
            )

    async def agregar(
        self, negocio_id: UUID, coleccion: str, campos: dict[str, Any]
    ) -> dict[str, Any]:
        tabla = _TABLAS[coleccion]
        columnas = ["negocio_id", *campos]
        valores = [" :negocio_id", *[f" :{clave}" for clave in campos]]
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            fila = (
                (
                    await conexion.execute(
                        text(
                            f"""
                            INSERT INTO {tabla} ({", ".join(columnas)})
                            VALUES ({",".join(valores)})
                            RETURNING *
                            """
                        ),
                        {"negocio_id": negocio_id, **campos},
                    )
                )
                .mappings()
                .one()
            )
        return dict(fila)

    async def quitar(self, negocio_id: UUID, coleccion: str, fila_id: UUID) -> bool:
        tabla = _TABLAS[coleccion]
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            resultado = await conexion.execute(
                text(f"DELETE FROM {tabla} WHERE id = :id AND negocio_id = :negocio_id"),
                {"id": fila_id, "negocio_id": negocio_id},
            )
        return bool(resultado.rowcount)
