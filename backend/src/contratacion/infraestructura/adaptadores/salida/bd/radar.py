"""Oportunidades, alertas, avisos y búsquedas guardadas.

`registro` es compartido: se lee sin contexto de negocio y se limita por las fuentes que la
persona puede ver. El resto de las tablas es de la empresa y se escribe con su `negocio_id`.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from contratacion.dominio.propuestas import condiciones_cpc
from contratacion.dominio.radar import plegar
from contratacion.infraestructura.adaptadores.salida.bd.claves import (
    NORMALIZADO,
    clave_provincia,
)
from contratacion.infraestructura.adaptadores.salida.bd.contexto import (
    contexto_negocio,
    sin_contexto,
)

_CANDIDATOS = """
SELECT r.id, f.codigo AS fuente, r.clave_natural, r.datos, r.cpc_codigos, r.documentos,
       r.fecha_publicacion, r.primera_vez_visto, r.ultima_vez_visto, r.plazo_proformas_en,
       r.provincia, r.texto_busqueda
FROM registro r
JOIN fuente f ON f.id = r.fuente_id
WHERE r.es_vigente
  AND f.codigo = ANY(CAST(:fuentes AS text[]))
  AND (
        cardinality(CAST(:provincias AS text[])) = 0
        OR r.provincia = ANY(CAST(:provincias AS text[]))
      )
  AND (
        CAST(:desde AS timestamptz) IS NULL
        OR r.primera_vez_visto >= CAST(:desde AS timestamptz)
      )
ORDER BY r.fecha_publicacion DESC NULLS LAST
LIMIT :limite
"""


def _numero(valor: Any) -> float | None:
    if valor is None or valor == "":
        return None
    try:
        return float(str(valor).replace(",", ""))
    except ValueError:
        return None


def _monto_publicado(datos: dict[str, Any]) -> float | None:
    """Monto publicado. Un cero no cuenta: la ínfima lo trae cuando no hay valor."""
    for clave in ("presupuesto", "monto", "valor_unitario"):
        numero = _numero(datos.get(clave))
        if numero is not None and numero > 0:
            return numero
    return None


def a_oportunidad(fila: Any) -> dict[str, Any]:
    datos = dict(fila["datos"] or {})
    return {
        "id": fila["id"],
        "fuente": fila["fuente"],
        "clave_natural": fila["clave_natural"],
        "codigo": datos.get("codigo") or fila["clave_natural"],
        "objeto": (
            datos.get("objeto_compra")
            or datos.get("objeto")
            or datos.get("descripcion")
            or datos.get("title")
            or ""
        ),
        "entidad": datos.get("entidad") or datos.get("razon_social") or "",
        "provincia": fila["provincia"] or datos.get("provincia") or "",
        "canton": datos.get("canton") or datos.get("cantón") or "",
        "cpc_codigos": list(fila["cpc_codigos"] or []),
        "presupuesto": _monto_publicado(datos),
        "documentos": list(fila["documentos"] or []),
        "plazo": fila["plazo_proformas_en"],
        "texto": fila["texto_busqueda"] or "",
        "fecha_publicacion": fila["fecha_publicacion"],
        "primera_vez_visto": fila["primera_vez_visto"],
        "ultima_vez_visto": fila["ultima_vez_visto"],
        "tipo_proceso": datos.get("tipo_proceso") or "",
    }


# Ínfimas que aún reciben proformas y encajan con el perfil. El filtro de CPC y de palabras se hace
# aquí, en SQL, y no en Python sobre una muestra: «Propuestas para ti» promete todas, y traer las
# 300 más recientes para filtrar después dejaba fuera justo las que llevan días publicadas.
#
# - Plazo: usa el índice parcial `ix_registro_plazo_proformas` (solo filas con plazo, un 6 %).
# - CPC: la regla es la de `dominio.propuestas.cpc_que_coinciden` —el código de la ínfima empieza
#   por uno del perfil, o es un inicio de uno del perfil—. El índice GIN de `cpc_codigos` sirve para
#   igualdad y no para «empieza por», así que la comparación recorre los códigos de las filas que ya
#   pasaron el plazo, que son pocas.
# - Palabras: contra el texto plegado (minúsculas, sin tildes) del objeto, la entidad y el índice de
#   búsqueda, igual que `coincide_texto`. Python vuelve a comprobarlo todo: esto solo es la criba.
_TEXTO_PLEGADO = NORMALIZADO.format(
    columna=(
        "r.texto_busqueda || ' ' || COALESCE(r.datos ->> 'objeto_compra', '')"
        " || ' ' || COALESCE(r.datos ->> 'objeto', '')"
        " || ' ' || COALESCE(r.datos ->> 'entidad', '')"
    )
)
_INFIMAS_ABIERTAS = f"""
SELECT r.id, r.clave_natural, r.cpc_codigos, r.plazo_proformas_en, r.fecha_publicacion,
       r.ultima_vez_visto, r.provincia AS provincia_clave, r.texto_busqueda,
       jsonb_array_length(r.documentos) AS documentos,
       r.datos ->> 'codigo' AS codigo,
       COALESCE(r.datos ->> 'objeto_compra', r.datos ->> 'objeto', r.datos ->> 'descripcion', '')
           AS objeto,
       COALESCE(r.datos ->> 'entidad', r.datos ->> 'razon_social', '') AS entidad,
       r.datos ->> 'provincia' AS provincia,
       COALESCE(r.datos ->> 'canton', r.datos ->> 'cantón', '') AS canton,
       r.datos ->> 'presupuesto' AS presupuesto,
       r.datos ->> 'monto' AS monto,
       r.datos ->> 'valor_unitario' AS valor_unitario
FROM registro r
JOIN fuente f ON f.id = r.fuente_id
WHERE r.es_vigente
  AND f.codigo = 'NCO'
  AND (
        r.plazo_proformas_en > now()
        OR (CAST(:incluir_sin_plazo AS boolean) AND r.plazo_proformas_en IS NULL)
      )
  AND (
        cardinality(CAST(:provincias AS text[])) = 0
        OR r.provincia = ANY(CAST(:provincias AS text[]))
      )
  AND (
        EXISTS (
            SELECT 1
            FROM unnest(r.cpc_codigos) AS c(codigo)
            WHERE regexp_replace(c.codigo, '[^0-9]', '', 'g') LIKE ANY(CAST(:cpc_empieza AS text[]))
               OR regexp_replace(c.codigo, '[^0-9]', '', 'g') = ANY(CAST(:cpc_es_inicio AS text[]))
        )
        OR {_TEXTO_PLEGADO} LIKE ANY(CAST(:palabras AS text[]))
      )
ORDER BY r.plazo_proformas_en ASC NULLS LAST, r.id
LIMIT :limite
"""


def _patron_like(texto: str) -> str:
    """`%texto%` con los comodines de LIKE escapados: «100%» no debe encontrar «1000»."""
    escapado = texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escapado}%"


def _a_infima(fila: Any) -> dict[str, Any]:
    datos = {
        "presupuesto": fila["presupuesto"],
        "monto": fila["monto"],
        "valor_unitario": fila["valor_unitario"],
    }
    provincia = fila["provincia"] or fila["provincia_clave"] or ""
    # La fuente publica «PROVINCIA - CANTÓN» en algunos registros: la provincia es lo de antes.
    provincia = provincia.split(" - ")[0].strip()
    return {
        "id": fila["id"],
        "fuente": "NCO",
        "codigo": fila["codigo"] or fila["clave_natural"],
        "clave_natural": fila["clave_natural"],
        "objeto": fila["objeto"] or "",
        "entidad": fila["entidad"] or "",
        "provincia": provincia,
        "canton": fila["canton"] or "",
        "cpc_codigos": list(fila["cpc_codigos"] or []),
        "presupuesto": _monto_publicado(datos),
        # La nota del radar solo mira si hay documentos, no cuáles: basta con saber cuántos.
        "documentos": [None] * int(fila["documentos"] or 0),
        "plazo": fila["plazo_proformas_en"],
        "texto": fila["texto_busqueda"] or "",
        "fecha_publicacion": fila["fecha_publicacion"],
        "ultima_vez_visto": fila["ultima_vez_visto"],
    }


class RepositorioRadar:
    def __init__(self, motor: AsyncEngine) -> None:
        self._motor = motor

    async def candidatos(
        self,
        *,
        fuentes: tuple[str, ...],
        provincias: tuple[str, ...],
        desde: datetime | None,
        limite: int,
    ) -> list[dict[str, Any]]:
        if not fuentes:
            return []
        claves = [clave_provincia(provincia) for provincia in provincias]
        async with sin_contexto(self._motor) as conexion:
            filas = (
                (
                    await conexion.execute(
                        text(_CANDIDATOS),
                        {
                            "fuentes": list(fuentes),
                            "provincias": claves,
                            "desde": desde,
                            "limite": limite,
                        },
                    )
                )
                .mappings()
                .all()
            )
        return [a_oportunidad(fila) for fila in filas]

    async def infimas_abiertas(
        self,
        *,
        provincias: tuple[str, ...],
        cpc: tuple[str, ...],
        palabras: tuple[str, ...],
        incluir_sin_plazo: bool,
        limite: int,
    ) -> list[dict[str, Any]]:
        exactos, inicios = condiciones_cpc(cpc)
        planas = dict.fromkeys(plegar(palabra) for palabra in palabras)
        patrones = [_patron_like(plana) for plana in planas if plana]
        if not exactos and not patrones:
            return []
        async with sin_contexto(self._motor) as conexion:
            filas = (
                (
                    await conexion.execute(
                        text(_INFIMAS_ABIERTAS),
                        {
                            "incluir_sin_plazo": incluir_sin_plazo,
                            "provincias": list(
                                dict.fromkeys(clave_provincia(p) for p in provincias)
                            ),
                            # «empieza por un código del perfil» e «es un inicio de un código del
                            # perfil»: las dos mitades de la regla de `cpc_que_coinciden`.
                            "cpc_empieza": [f"{codigo}%" for codigo in exactos],
                            "cpc_es_inicio": inicios,
                            "palabras": patrones,
                            "limite": limite,
                        },
                    )
                )
                .mappings()
                .all()
            )
        return [_a_infima(fila) for fila in filas]

    async def guardar_busqueda(
        self, *, negocio_id: UUID, usuario_id: UUID, nombre: str, parametros: dict[str, Any]
    ) -> dict[str, Any]:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            fila = (
                (
                    await conexion.execute(
                        text(
                            """
                            INSERT INTO busqueda_guardada
                                (negocio_id, usuario_id, nombre, parametros)
                            VALUES (:negocio_id, :usuario_id, :nombre, CAST(:parametros AS jsonb))
                            RETURNING id, nombre, parametros, creado_en
                            """
                        ),
                        {
                            "negocio_id": negocio_id,
                            "usuario_id": usuario_id,
                            "nombre": nombre,
                            "parametros": json.dumps(parametros),
                        },
                    )
                )
                .mappings()
                .one()
            )
        return dict(fila)

    async def listar_busquedas(self, *, negocio_id: UUID, usuario_id: UUID) -> list[dict[str, Any]]:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            filas = (
                (
                    await conexion.execute(
                        text(
                            """
                            SELECT id, nombre, parametros, creado_en
                            FROM busqueda_guardada
                            WHERE negocio_id = :negocio_id AND usuario_id = :usuario_id
                            ORDER BY creado_en DESC
                            """
                        ),
                        {"negocio_id": negocio_id, "usuario_id": usuario_id},
                    )
                )
                .mappings()
                .all()
            )
        return [dict(fila) for fila in filas]

    async def quitar_busqueda(
        self, *, negocio_id: UUID, usuario_id: UUID, busqueda_id: UUID
    ) -> bool:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            resultado = await conexion.execute(
                text(
                    """
                    DELETE FROM busqueda_guardada
                    WHERE id = :id AND negocio_id = :negocio_id AND usuario_id = :usuario_id
                    """
                ),
                {"id": busqueda_id, "negocio_id": negocio_id, "usuario_id": usuario_id},
            )
        return bool(resultado.rowcount)

    async def crear_alerta(
        self, *, negocio_id: UUID, usuario_id: UUID, campos: dict[str, Any]
    ) -> dict[str, Any]:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            fila = (
                (
                    await conexion.execute(
                        text(
                            """
                            INSERT INTO alerta (
                                negocio_id, usuario_id, nombre, cpc, palabras, provincia, canton,
                                presupuesto_min, presupuesto_max, frecuencia, avisar_correo
                            )
                            VALUES (
                                :negocio_id, :usuario_id, :nombre,
                                CAST(:cpc AS text[]), CAST(:palabras AS text[]),
                                :provincia, :canton, :presupuesto_min, :presupuesto_max,
                                :frecuencia, :avisar_correo
                            )
                            RETURNING *
                            """
                        ),
                        {
                            "negocio_id": negocio_id,
                            "usuario_id": usuario_id,
                            "nombre": campos["nombre"],
                            "cpc": campos.get("cpc") or [],
                            "palabras": campos.get("palabras") or [],
                            "provincia": campos.get("provincia") or "",
                            "canton": campos.get("canton") or "",
                            "presupuesto_min": campos.get("presupuesto_min"),
                            "presupuesto_max": campos.get("presupuesto_max"),
                            "frecuencia": campos.get("frecuencia") or "diaria",
                            "avisar_correo": bool(campos.get("avisar_correo")),
                        },
                    )
                )
                .mappings()
                .one()
            )
        return dict(fila)

    async def listar_alertas(self, *, negocio_id: UUID | None = None) -> list[dict[str, Any]]:
        """Sin negocio, las activas de todas las empresas: lo usa el worker."""
        if negocio_id is None:
            async with sin_contexto(self._motor) as conexion:
                filas = (
                    (
                        # Función `SECURITY DEFINER` (migración 0037): con RLS forzada, una consulta
                        # sin contexto de empresa no ve filas en cuanto el rol deja de saltarse RLS.
                        await conexion.execute(text("SELECT * FROM alertas_activas()"))
                    )
                    .mappings()
                    .all()
                )
            return [dict(fila) for fila in filas]
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            filas = (
                (
                    await conexion.execute(
                        text(
                            """
                            SELECT * FROM alerta
                            WHERE negocio_id = :negocio_id
                            ORDER BY creado_en DESC
                            """
                        ),
                        {"negocio_id": negocio_id},
                    )
                )
                .mappings()
                .all()
            )
        return [dict(fila) for fila in filas]

    async def quitar_alerta(self, *, negocio_id: UUID, usuario_id: UUID, alerta_id: UUID) -> bool:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            resultado = await conexion.execute(
                text(
                    """
                    DELETE FROM alerta
                    WHERE id = :id AND negocio_id = :negocio_id AND usuario_id = :usuario_id
                    """
                ),
                {"id": alerta_id, "negocio_id": negocio_id, "usuario_id": usuario_id},
            )
        return bool(resultado.rowcount)

    async def marcar_revisada(
        self, alerta_id: UUID, momento: datetime, *, negocio_id: UUID | None = None
    ) -> None:
        """Anota que la alerta se revisó, **dentro del contexto de su empresa**.

        Antes iba sin contexto, y solo funcionaba porque el rol de la base se salta RLS (riesgo
        R-05). Con el rol correcto el `UPDATE` no tocaba ninguna fila, la alerta no se daba nunca
        por revisada y el worker la volvía a procesar en cada vuelta (auditoría, doc 38).
        """
        if negocio_id is None:
            async with sin_contexto(self._motor) as conexion:
                await conexion.execute(
                    text("UPDATE alerta SET revisada_en = :momento WHERE id = :id"),
                    {"id": alerta_id, "momento": momento},
                )
            return
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            await conexion.execute(
                text(
                    "UPDATE alerta SET revisada_en = :momento "
                    "WHERE id = :id AND negocio_id = :negocio_id"
                ),
                {"id": alerta_id, "momento": momento, "negocio_id": negocio_id},
            )

    async def crear_aviso(self, campos: dict[str, Any]) -> None:
        await self.crear_avisos([campos])

    async def crear_avisos(self, avisos: list[dict[str, Any]]) -> int:
        """Deja los avisos de una revisión en **una** sentencia por empresa. Devuelve los nuevos.

        Antes era una conexión y una transacción por aviso: una alerta diaria que encaja con
        doscientos procesos eran doscientos viajes a la base. Ahora es uno por empresa.

        `ON CONFLICT DO NOTHING` contra el índice único `(alerta_id, registro_id)` (migración 0040):
        si dos réplicas del worker, o una revisión que se repite tras un fallo, avisan del mismo
        proceso para la misma alerta, el segundo aviso no se crea.
        """
        por_negocio: dict[UUID, list[dict[str, Any]]] = {}
        for aviso in avisos:
            por_negocio.setdefault(aviso["negocio_id"], []).append(aviso)
        creados = 0
        for negocio_id, suyos in por_negocio.items():
            async with contexto_negocio(self._motor, negocio_id) as conexion:
                resultado = await conexion.execute(
                    text(
                        """
                        INSERT INTO aviso (
                            negocio_id, usuario_id, alerta_id, registro_id, titulo, detalle,
                            puntuacion
                        )
                        SELECT :negocio_id, a.usuario_id, a.alerta_id, a.registro_id, a.titulo,
                               a.detalle, a.puntuacion
                        FROM jsonb_to_recordset(CAST(:avisos AS jsonb)) AS a(
                            usuario_id uuid, alerta_id uuid, registro_id uuid, titulo text,
                            detalle text, puntuacion integer
                        )
                        ON CONFLICT (alerta_id, registro_id) WHERE alerta_id IS NOT NULL
                        DO NOTHING
                        """
                    ),
                    {
                        "negocio_id": negocio_id,
                        "avisos": json.dumps(
                            [
                                {
                                    "usuario_id": str(aviso["usuario_id"]),
                                    "alerta_id": str(aviso["alerta_id"])
                                    if aviso.get("alerta_id")
                                    else None,
                                    "registro_id": str(aviso["registro_id"])
                                    if aviso.get("registro_id")
                                    else None,
                                    "titulo": aviso.get("titulo"),
                                    "detalle": aviso.get("detalle"),
                                    "puntuacion": aviso.get("puntuacion"),
                                }
                                for aviso in suyos
                            ]
                        ),
                    },
                )
                creados += int(getattr(resultado, "rowcount", 0) or 0)
        return creados

    async def listar_avisos(
        self,
        *,
        negocio_id: UUID,
        usuario_id: UUID,
        fuentes: tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        """Los últimos avisos de la persona.

        Con `fuentes`, los avisos de alertas cuyo proceso es de una fuente que la persona ya no
        puede ver **no salen**: si el superadministrador le oculta una vista, sus alertas viejas no
        pueden seguir enseñándole títulos de esa fuente. Los recordatorios de sus propias proformas
        (sin alerta) salen siempre: son de su trabajo, no del histórico.
        """
        filtro_fuente = ""
        params: dict[str, Any] = {"negocio_id": negocio_id, "usuario_id": usuario_id}
        if fuentes is not None:
            filtro_fuente = " AND (a.alerta_id IS NULL OR f.codigo = ANY(CAST(:fuentes AS text[])))"
            params["fuentes"] = list(fuentes)
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            filas = (
                (
                    await conexion.execute(
                        text(
                            f"""
                            SELECT a.*, r.datos ->> 'codigo' AS codigo
                            FROM aviso a
                            LEFT JOIN registro r ON r.id = a.registro_id
                            LEFT JOIN fuente f ON f.id = r.fuente_id
                            WHERE a.negocio_id = :negocio_id AND a.usuario_id = :usuario_id
                            {filtro_fuente}
                            ORDER BY a.creado_en DESC
                            LIMIT 50
                            """
                        ),
                        params,
                    )
                )
                .mappings()
                .all()
            )
        return [dict(fila) for fila in filas]

    async def marcar_leido(
        self, *, negocio_id: UUID, usuario_id: UUID, aviso_id: UUID, momento: datetime
    ) -> bool:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            resultado = await conexion.execute(
                text(
                    """
                    UPDATE aviso SET leido_en = :momento
                    WHERE id = :id AND negocio_id = :negocio_id AND usuario_id = :usuario_id
                    """
                ),
                {
                    "id": aviso_id,
                    "negocio_id": negocio_id,
                    "usuario_id": usuario_id,
                    "momento": momento,
                },
            )
        return bool(resultado.rowcount)

    async def correo_de(self, *, negocio_id: UUID, usuario_id: UUID) -> str | None:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            return (
                await conexion.execute(
                    text(
                        """
                        SELECT email FROM usuario
                        WHERE id = :usuario_id AND negocio_id = :negocio_id
                        """
                    ),
                    {"usuario_id": usuario_id, "negocio_id": negocio_id},
                )
            ).scalar_one_or_none()
