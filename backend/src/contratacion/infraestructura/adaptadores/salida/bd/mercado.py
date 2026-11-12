"""Lecturas de mercado sobre `registro`. No habla con el portal.

Las adjudicaciones salen de OCDS, que es donde está el proveedor y el monto. Las necesidades
(NCO) entran en la demanda y en el ranking de entidades porque ahí está lo que se publicó.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from contratacion.dominio.palabras import normalizar
from contratacion.infraestructura.adaptadores.salida.bd.contexto import sin_contexto

_MONTO = (
    "CASE WHEN r.datos->>'monto' ~ '^[0-9]+([.][0-9]+)?$' "
    "AND (r.datos->>'monto')::numeric > 0 "
    "THEN (r.datos->>'monto')::numeric ELSE NULL END"
)
_PRESUPUESTO = (
    "CASE WHEN r.datos->>'presupuesto' ~ '^[0-9]+([.][0-9]+)?$' "
    "AND (r.datos->>'presupuesto')::numeric > 0 "
    "THEN (r.datos->>'presupuesto')::numeric ELSE NULL END"
)
_ANIO = "COALESCE(NULLIF(btrim(r.datos->>'anio'), ''), to_char(r.fecha_publicacion, 'YYYY'))"
_PROVEEDOR = "btrim(coalesce(r.datos->>'proveedor', ''))"
_ENTIDAD = "btrim(coalesce(r.datos->>'entidad', ''))"


def _like(valor: str) -> str:
    limpio = normalizar(valor).replace("%", "").replace("_", "")
    return f"%{limpio}%"


class RepositorioMercado:
    def __init__(self, motor: AsyncEngine) -> None:
        self._motor = motor

    def _condiciones(
        self,
        *,
        fuentes: tuple[str, ...],
        q: str = "",
        cpc: str = "",
        entidad: str = "",
        proveedor: str = "",
        anio: str = "",
        solo_adjudicados: bool = False,
    ) -> tuple[str, dict[str, Any]]:
        partes = [
            "r.es_vigente",
            "f.codigo = ANY(CAST(:fuentes AS text[]))",
        ]
        params: dict[str, Any] = {"fuentes": list(fuentes)}
        if solo_adjudicados:
            partes.append(f"{_PROVEEDOR} <> ''")
        if q.strip():
            partes.append("r.texto_busqueda ILIKE :q")
            params["q"] = _like(q)
        if cpc.strip():
            partes.append(
                "EXISTS (SELECT 1 FROM unnest(r.cpc_codigos) codigo WHERE codigo LIKE :cpc)"
            )
            params["cpc"] = cpc.strip() + "%"
        if entidad.strip():
            partes.append(f"{_ENTIDAD} ILIKE :entidad")
            params["entidad"] = f"%{entidad.strip()}%"
        if proveedor.strip():
            partes.append(f"{_PROVEEDOR} ILIKE :proveedor")
            params["proveedor"] = f"%{proveedor.strip()}%"
        if anio.strip():
            partes.append(f"{_ANIO} = :anio")
            params["anio"] = anio.strip()
        return " AND ".join(partes), params

    async def _leer(self, consulta: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        async with sin_contexto(self._motor) as conexion:
            filas = (await conexion.execute(text(consulta), params)).mappings().all()
        return [dict(fila) for fila in filas]

    async def adjudicaciones(
        self,
        *,
        fuentes: tuple[str, ...],
        q: str = "",
        cpc: str = "",
        entidad: str = "",
        proveedor: str = "",
        anio: str = "",
        limite: int = 60,
    ) -> list[dict[str, Any]]:
        if not fuentes:
            return []
        donde, params = self._condiciones(
            fuentes=fuentes,
            q=q,
            cpc=cpc,
            entidad=entidad,
            proveedor=proveedor,
            anio=anio,
            solo_adjudicados=True,
        )
        params["limite"] = limite
        consulta = f"""
            SELECT r.id,
                   COALESCE(r.datos->>'codigo', r.clave_natural) AS codigo,
                   COALESCE(r.datos->>'objeto_compra', '') AS objeto,
                   {_ENTIDAD} AS entidad,
                   {_PROVEEDOR} AS proveedor,
                   COALESCE(NULLIF(r.datos->>'tipo_proceso', ''), r.datos->>'metodo', '')
                       AS tipo_proceso,
                   {_MONTO} AS monto,
                   {_ANIO} AS anio,
                   COALESCE(r.provincia, '') AS provincia,
                   COALESCE(r.datos->>'canton', '') AS canton,
                   r.cpc_codigos AS cpc,
                   r.fecha_publicacion
            FROM registro r
            JOIN fuente f ON f.id = r.fuente_id
            WHERE {donde}
            ORDER BY r.fecha_publicacion DESC NULLS LAST
            LIMIT :limite
        """
        return await self._leer(consulta, params)

    async def montos(
        self,
        *,
        fuentes: tuple[str, ...],
        q: str = "",
        cpc: str = "",
        anio: str = "",
        limite: int = 400,
    ) -> list[dict[str, Any]]:
        if not fuentes:
            return []
        donde, params = self._condiciones(
            fuentes=fuentes, q=q, cpc=cpc, anio=anio, solo_adjudicados=True
        )
        params["limite"] = limite
        consulta = f"""
            SELECT COALESCE(r.datos->>'codigo', r.clave_natural) AS codigo,
                   COALESCE(r.datos->>'objeto_compra', '') AS objeto,
                   {_ENTIDAD} AS entidad,
                   {_PROVEEDOR} AS proveedor,
                   COALESCE(NULLIF(r.datos->>'tipo_proceso', ''), '') AS tipo_proceso,
                   {_MONTO} AS monto,
                   {_ANIO} AS anio,
                   r.cpc_codigos AS cpc
            FROM registro r
            JOIN fuente f ON f.id = r.fuente_id
            WHERE {donde} AND {_MONTO} IS NOT NULL
            ORDER BY r.fecha_publicacion DESC NULLS LAST
            LIMIT :limite
        """
        return await self._leer(consulta, params)

    async def proveedores(
        self,
        *,
        fuentes: tuple[str, ...],
        q: str = "",
        cpc: str = "",
        anio: str = "",
        limite: int = 30,
    ) -> list[dict[str, Any]]:
        if not fuentes:
            return []
        donde, params = self._condiciones(
            fuentes=fuentes, q=q, cpc=cpc, anio=anio, solo_adjudicados=True
        )
        params["limite"] = limite
        consulta = f"""
            SELECT {_PROVEEDOR} AS nombre,
                   count(*) AS procesos,
                   count({_MONTO}) AS adjudicaciones,
                   coalesce(sum({_MONTO}), 0) AS monto,
                   array_remove(array_agg(DISTINCT NULLIF({_ENTIDAD}, '')), NULL) AS entidades,
                   array_remove(array_agg(DISTINCT NULLIF(r.cpc_codigos[1], '')), NULL)
                       AS categorias,
                   array_remove(array_agg(DISTINCT NULLIF({_ANIO}, '')), NULL) AS anios
            FROM registro r
            JOIN fuente f ON f.id = r.fuente_id
            WHERE {donde}
            GROUP BY 1
            ORDER BY monto DESC, procesos DESC
            LIMIT :limite
        """
        filas = await self._leer(consulta, params)
        serie = await self._leer(
            f"""
            SELECT {_PROVEEDOR} AS nombre, {_ANIO} AS anio,
                   count(*) AS n, coalesce(sum({_MONTO}), 0) AS monto
            FROM registro r
            JOIN fuente f ON f.id = r.fuente_id
            WHERE {donde} AND {_ANIO} <> ''
            GROUP BY 1, 2
            """,
            {clave: valor for clave, valor in params.items() if clave != "limite"},
        )
        return _con_evolucion(filas, serie)

    async def entidades(
        self,
        *,
        fuentes: tuple[str, ...],
        q: str = "",
        cpc: str = "",
        anio: str = "",
        limite: int = 30,
    ) -> list[dict[str, Any]]:
        if not fuentes:
            return []
        donde, params = self._condiciones(fuentes=fuentes, q=q, cpc=cpc, anio=anio)
        params["limite"] = limite
        consulta = f"""
            SELECT {_ENTIDAD} AS nombre,
                   count(*) AS procesos,
                   coalesce(sum({_PRESUPUESTO}), 0) AS publicado,
                   coalesce(sum({_MONTO}), 0) AS adjudicado,
                   array_remove(array_agg(DISTINCT NULLIF({_PROVEEDOR}, '')), NULL)
                       AS proveedores,
                   array_remove(array_agg(DISTINCT NULLIF(r.cpc_codigos[1], '')), NULL)
                       AS categorias,
                   array_remove(array_agg(DISTINCT NULLIF(r.provincia, '')), NULL)
                       AS provincias,
                   array_remove(array_agg(DISTINCT NULLIF({_ANIO}, '')), NULL) AS anios
            FROM registro r
            JOIN fuente f ON f.id = r.fuente_id
            WHERE {donde} AND {_ENTIDAD} <> ''
            GROUP BY 1
            ORDER BY procesos DESC, adjudicado DESC
            LIMIT :limite
        """
        filas = await self._leer(consulta, params)
        serie = await self._leer(
            f"""
            SELECT {_ENTIDAD} AS nombre, {_ANIO} AS anio, count(*) AS n
            FROM registro r
            JOIN fuente f ON f.id = r.fuente_id
            WHERE {donde} AND {_ENTIDAD} <> '' AND {_ANIO} <> ''
            GROUP BY 1, 2
            """,
            {clave: valor for clave, valor in params.items() if clave != "limite"},
        )
        return _con_evolucion(filas, serie)

    async def demanda(
        self,
        *,
        fuentes: tuple[str, ...],
        q: str = "",
        cpc: str = "",
        anio: str = "",
    ) -> dict[str, Any]:
        if not fuentes:
            return {"provincias": [], "cantones": [], "categorias": []}
        donde, params = self._condiciones(fuentes=fuentes, q=q, cpc=cpc, anio=anio)
        provincias = await self._leer(
            f"""
            SELECT COALESCE(NULLIF(r.provincia, ''), 'sin provincia') AS nombre,
                   count(*) AS procesos,
                   coalesce(sum({_MONTO}), 0) AS monto
            FROM registro r
            JOIN fuente f ON f.id = r.fuente_id
            WHERE {donde}
            GROUP BY 1
            ORDER BY procesos DESC
            """,
            params,
        )
        cantones = await self._leer(
            f"""
            SELECT COALESCE(NULLIF(r.provincia, ''), '') AS provincia,
                   btrim(r.datos->>'canton') AS nombre,
                   count(*) AS procesos,
                   coalesce(sum({_MONTO}), 0) AS monto
            FROM registro r
            JOIN fuente f ON f.id = r.fuente_id
            WHERE {donde} AND btrim(coalesce(r.datos->>'canton', '')) <> ''
            GROUP BY 1, 2
            ORDER BY procesos DESC
            LIMIT 40
            """,
            params,
        )
        categorias = await self._leer(
            f"""
            SELECT cpc_item AS nombre, count(*) AS procesos
            FROM registro r
            JOIN fuente f ON f.id = r.fuente_id
            CROSS JOIN LATERAL unnest(r.cpc_codigos) AS cpc_item
            WHERE {donde} AND cpc_item <> ''
            GROUP BY 1
            ORDER BY procesos DESC
            LIMIT 12
            """,
            params,
        )
        return {"provincias": provincias, "cantones": cantones, "categorias": categorias}

    async def comparar(self, *, fuentes: tuple[str, ...], ids: list[UUID]) -> list[dict[str, Any]]:
        if not fuentes or not ids:
            return []
        consulta = f"""
            SELECT r.id,
                   f.codigo AS fuente,
                   COALESCE(r.datos->>'codigo', r.clave_natural) AS codigo,
                   COALESCE(r.datos->>'objeto_compra', '') AS objeto,
                   {_ENTIDAD} AS entidad,
                   COALESCE(r.provincia, '') AS provincia,
                   COALESCE(r.datos->>'canton', '') AS canton,
                   r.cpc_codigos AS cpc,
                   {_PRESUPUESTO} AS presupuesto,
                   {_MONTO} AS monto,
                   COALESCE(NULLIF(r.datos->>'tipo_proceso', ''), '') AS tipo_proceso,
                   r.fecha_publicacion,
                   r.plazo_proformas_en,
                   r.documentos
            FROM registro r
            JOIN fuente f ON f.id = r.fuente_id
            WHERE r.id = ANY(CAST(:ids AS uuid[]))
              AND f.codigo = ANY(CAST(:fuentes AS text[]))
        """
        return await self._leer(consulta, {"ids": ids, "fuentes": list(fuentes)})


def _con_evolucion(
    filas: list[dict[str, Any]], serie: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    por_nombre: dict[str, list[dict[str, Any]]] = {}
    for punto in serie:
        por_nombre.setdefault(str(punto["nombre"]), []).append(
            {
                "anio": punto.get("anio") or "",
                "n": punto.get("n") or 0,
                "monto": punto.get("monto"),
            }
        )
    for fila in filas:
        fila["evolucion"] = sorted(
            por_nombre.get(str(fila["nombre"]), []), key=lambda punto: str(punto["anio"])
        )
        for clave in ("entidades", "categorias", "anios", "proveedores", "provincias"):
            if fila.get(clave):
                fila[clave] = list(fila[clave])[:8]
    return filas
