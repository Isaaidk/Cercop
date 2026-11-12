"""Lecturas, requisitos y proformas de una empresa. El PDF no se guarda."""

from __future__ import annotations

import json
import time
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from contratacion.aplicacion.hilos import MemoLru
from contratacion.dominio.errores import EstadoInvalido
from contratacion.dominio.titulos import titulo_libre, titulo_repetido
from contratacion.infraestructura.adaptadores.salida.bd.contexto import (
    contexto_negocio,
    sin_contexto,
)

# La ficha de un proceso casi no cambia, y se pide una vez por sondeo y por persona. Se recuerda un
# minuto; si no existe, solo cinco segundos, para que un proceso recién ingerido aparezca pronto.
_TTL_FICHA_SEG = 60.0
_TTL_FICHA_AUSENTE_SEG = 5.0
_TTL_FICHA_SIN_ITEMS_SEG = 3.0
_MAX_FICHAS = 4096
# Tipos cuyo título no se repite dentro de la empresa (las fichas técnicas sí pueden repetirse).
_TIPOS_CON_TITULO_UNICO = frozenset({"proforma", "cotizacion"})
# Fichas públicas del portal. La llave lleva las fuentes que la persona puede ver: quien no tiene
# la vista de ínfimas no recibe una ficha NCO recordada para otro. LRU acotada.
_FICHAS: MemoLru[tuple[tuple[str, ...], str], tuple[float, dict[str, Any] | None]] = MemoLru(
    _MAX_FICHAS
)


class RepositorioDocumentos:
    def __init__(self, motor: AsyncEngine) -> None:
        self._motor = motor

    async def guardar_lectura(
        self,
        *,
        negocio_id: UUID,
        usuario_id: UUID,
        nombre: str,
        secciones: dict[str, str],
        registro_id: UUID | None = None,
    ) -> dict[str, Any]:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            fila = (
                (
                    await conexion.execute(
                        text(
                            """
                        INSERT INTO lectura_documento
                            (negocio_id, usuario_id, nombre, registro_id, secciones)
                        VALUES
                            (:negocio_id, :usuario_id, :nombre, :registro_id,
                             CAST(:secciones AS jsonb))
                        RETURNING id, nombre, secciones, creado_en
                        """
                        ),
                        {
                            "negocio_id": negocio_id,
                            "usuario_id": usuario_id,
                            "nombre": nombre,
                            "registro_id": registro_id,
                            "secciones": json.dumps(secciones),
                        },
                    )
                )
                .mappings()
                .one()
            )
        return dict(fila)

    async def listar_lecturas(self, *, negocio_id: UUID) -> list[dict[str, Any]]:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            filas = (
                (
                    await conexion.execute(
                        text(
                            """
                        SELECT id, nombre, creado_en
                        FROM lectura_documento
                        WHERE negocio_id = :negocio_id
                        ORDER BY creado_en DESC
                        LIMIT 20
                        """
                        ),
                        {"negocio_id": negocio_id},
                    )
                )
                .mappings()
                .all()
            )
        return [dict(fila) for fila in filas]

    async def lectura(self, *, negocio_id: UUID, lectura_id: UUID) -> dict[str, Any] | None:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            fila = (
                (
                    await conexion.execute(
                        text(
                            """
                        SELECT * FROM lectura_documento
                        WHERE id = :id AND negocio_id = :negocio_id
                        """
                        ),
                        {"id": lectura_id, "negocio_id": negocio_id},
                    )
                )
                .mappings()
                .first()
            )
        return dict(fila) if fila else None

    async def ultima(self, *, negocio_id: UUID) -> dict[str, Any] | None:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            fila = (
                (
                    await conexion.execute(
                        text(
                            """
                        SELECT * FROM lectura_documento
                        WHERE negocio_id = :negocio_id
                        ORDER BY creado_en DESC
                        LIMIT 1
                        """
                        ),
                        {"negocio_id": negocio_id},
                    )
                )
                .mappings()
                .first()
            )
        return dict(fila) if fila else None

    async def guardar_lectura_con_requisitos(
        self,
        *,
        negocio_id: UUID,
        usuario_id: UUID,
        nombre: str,
        secciones: dict[str, str],
        registro_id: UUID | None,
        textos: list[str],
    ) -> dict[str, Any]:
        """La lectura y su lista de requisitos en una sola transacción y con dos sentencias.

        Antes eran una conexión para la lectura y otra para los requisitos, que además se
        insertaban de uno en uno: con cuarenta requisitos, cuarenta viajes a la base por cada
        persona que abría un TDR. Con cientos abriéndolo a la vez eso satura el pool de conexiones.
        """
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            if registro_id is not None:
                # La empresa ya leyó este mismo TDR: se reutiliza. Insertar otra lectura cada vez
                # llenaba la tabla de copias iguales y, peor, dejaba la lista de requisitos de
                # esa persona en blanco aunque ya los hubiera marcado.
                existente = (
                    (
                        await conexion.execute(
                            text(
                                """
                            SELECT id, nombre, secciones, creado_en
                            FROM lectura_documento
                            WHERE negocio_id = :negocio_id AND registro_id = :registro_id
                              AND secciones = CAST(:secciones AS jsonb)
                            ORDER BY creado_en DESC
                            LIMIT 1
                            """
                            ),
                            {
                                "negocio_id": negocio_id,
                                "registro_id": registro_id,
                                "secciones": json.dumps(secciones),
                            },
                        )
                    )
                    .mappings()
                    .first()
                )
                if existente is not None:
                    return {**dict(existente), "reutilizada": True}
            fila = (
                (
                    await conexion.execute(
                        text(
                            """
                        INSERT INTO lectura_documento
                            (negocio_id, usuario_id, nombre, registro_id, secciones)
                        VALUES
                            (:negocio_id, :usuario_id, :nombre, :registro_id,
                             CAST(:secciones AS jsonb))
                        RETURNING id, nombre, secciones, creado_en
                        """
                        ),
                        {
                            "negocio_id": negocio_id,
                            "usuario_id": usuario_id,
                            "nombre": nombre,
                            "registro_id": registro_id,
                            "secciones": json.dumps(secciones),
                        },
                    )
                )
                .mappings()
                .one()
            )
            if textos:
                await conexion.execute(
                    text(
                        """
                        INSERT INTO requisito_proceso (negocio_id, lectura_id, texto, orden)
                        SELECT :negocio_id, :lectura_id, t.texto, t.orden - 1
                        FROM unnest(CAST(:textos AS text[])) WITH ORDINALITY AS t(texto, orden)
                        """
                    ),
                    {"negocio_id": negocio_id, "lectura_id": fila["id"], "textos": textos},
                )
        return dict(fila)

    async def guardar_requisitos(
        self, *, negocio_id: UUID, lectura_id: UUID, textos: list[str]
    ) -> None:
        if not textos:
            return
        # Una sentencia para todos, no un viaje por requisito (igual que en la lectura con
        # requisitos): con cuarenta requisitos eran cuarenta idas y vueltas con la conexión tomada.
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            await conexion.execute(
                text(
                    """
                    INSERT INTO requisito_proceso (negocio_id, lectura_id, texto, orden)
                    SELECT :negocio_id, :lectura_id, t.texto, t.orden - 1
                    FROM unnest(CAST(:textos AS text[])) WITH ORDINALITY AS t(texto, orden)
                    """
                ),
                {"negocio_id": negocio_id, "lectura_id": lectura_id, "textos": list(textos)},
            )

    async def requisitos(
        self, *, negocio_id: UUID, lectura_id: UUID | None = None
    ) -> list[dict[str, Any]]:
        consulta = """
            SELECT id, lectura_id, texto, estado, orden
            FROM requisito_proceso
            WHERE negocio_id = :negocio_id
        """
        params: dict[str, Any] = {"negocio_id": negocio_id}
        if lectura_id is not None:
            consulta += " AND lectura_id = :lectura_id"
            params["lectura_id"] = lectura_id
        consulta += " ORDER BY orden"
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            filas = (await conexion.execute(text(consulta), params)).mappings().all()
        return [dict(fila) for fila in filas]

    async def marcar(self, *, negocio_id: UUID, requisito_id: UUID, estado: str) -> bool:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            resultado = await conexion.execute(
                text(
                    """
                    UPDATE requisito_proceso SET estado = :estado
                    WHERE id = :id AND negocio_id = :negocio_id
                    """
                ),
                {"id": requisito_id, "estado": estado, "negocio_id": negocio_id},
            )
        return bool(resultado.rowcount)

    async def titulos_de_proformas(self, negocio_id: UUID) -> list[str]:
        """Los títulos ya usados por la empresa en proformas y cotizaciones (no en fichas)."""
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            filas = await conexion.execute(
                text(
                    """
                    SELECT DISTINCT titulo FROM proforma
                    WHERE negocio_id = :negocio_id AND tipo IN ('proforma', 'cotizacion')
                      AND titulo IS NOT NULL AND titulo <> ''
                    LIMIT 5000
                    """
                ),
                {"negocio_id": negocio_id},
            )
            return [str(fila[0]) for fila in filas]

    async def guardar_proforma(self, *, negocio_id: UUID, campos: dict[str, Any]) -> dict[str, Any]:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            if campos.get("tipo") in _TIPOS_CON_TITULO_UNICO:
                await self._exigir_titulo_libre(conexion, negocio_id, str(campos.get("titulo")))
            fila = (
                (
                    await conexion.execute(
                        text(
                            """
                        INSERT INTO proforma (
                            negocio_id, usuario_id, registro_id, tipo, titulo, entidad, objeto,
                            contacto, impuesto_porcentaje, lineas, cifras, extras
                        )
                        VALUES (
                            :negocio_id, :usuario_id, :registro_id, :tipo, :titulo, :entidad,
                            :objeto, :contacto, :impuesto_porcentaje,
                            CAST(:lineas AS jsonb), CAST(:cifras AS jsonb), CAST(:extras AS jsonb)
                        )
                        RETURNING id, tipo, titulo, creado_en
                        """
                        ),
                        {
                            "negocio_id": negocio_id,
                            "lineas": json.dumps(campos["lineas"]),
                            "cifras": json.dumps(campos.get("cifras") or {}),
                            "extras": json.dumps(campos.get("extras") or {}, default=str),
                            **{
                                clave: campos.get(clave)
                                for clave in (
                                    "usuario_id",
                                    "registro_id",
                                    "tipo",
                                    "titulo",
                                    "entidad",
                                    "objeto",
                                    "contacto",
                                    "impuesto_porcentaje",
                                )
                            },
                        },
                    )
                )
                .mappings()
                .one()
            )
        return dict(fila)

    @staticmethod
    async def _exigir_titulo_libre(
        conexion: AsyncConnection, negocio_id: UUID, titulo: str
    ) -> None:
        """Vuelve a comprobar el título **dentro** de la transacción que inserta, con un cerrojo.

        El caso de uso ya lo comprueba antes, pero entre su lectura y este `INSERT` otra petición de
        la misma empresa podía guardar el mismo título (dos pestañas, un doble clic). El cerrojo de
        asesoría por empresa (`pg_advisory_xact_lock`) pone en fila solo los guardados de proformas
        de esa empresa, dura lo que la transacción y no bloquea a nadie más.

        No es un índice único porque la regla no es `lower(titulo)`: dos títulos son el mismo si
        solo cambian tildes, guiones o espacios (`dominio.titulos`), y además hay empresas con
        títulos repetidos de antes de la regla que no se deben tocar.
        """
        await conexion.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:clave))"),
            {"clave": f"proforma_titulo:{negocio_id}"},
        )
        existentes = [
            str(fila[0])
            for fila in await conexion.execute(
                text(
                    """
                    SELECT DISTINCT titulo FROM proforma
                    WHERE negocio_id = :negocio_id AND tipo IN ('proforma', 'cotizacion')
                      AND titulo IS NOT NULL AND titulo <> ''
                    """
                ),
                {"negocio_id": negocio_id},
            )
        ]
        if titulo_repetido(titulo, existentes):
            raise EstadoInvalido(
                f"Ya tienes una proforma con el título «{titulo}». Cámbialo, por ejemplo: "
                f"«{titulo_libre(titulo, existentes)}»."
            )

    async def proforma(self, *, negocio_id: UUID, proforma_id: UUID) -> dict[str, Any] | None:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            fila = (
                (
                    await conexion.execute(
                        text(
                            """
                        SELECT * FROM proforma
                        WHERE id = :id AND negocio_id = :negocio_id
                        """
                        ),
                        {"id": proforma_id, "negocio_id": negocio_id},
                    )
                )
                .mappings()
                .first()
            )
        return dict(fila) if fila else None

    async def ficha_publicada(
        self, *, fuentes: tuple[str, ...], codigo: str
    ) -> dict[str, Any] | None:
        if not fuentes or not codigo.strip():
            return None
        llave = (fuentes, codigo.strip().lower())
        ahora = time.monotonic()
        guardada = _FICHAS.get(llave)
        hay_ficha = guardada is not None and guardada[1] is not None
        # Sin los ítems leídos la ficha cambia en segundos (el worker los está leyendo): se recuerda
        # poco, para que el panel vea llegar los ítems sin esperar un minuto.
        con_items = hay_ficha and guardada[1].get("items_recogidos_en") is not None  # type: ignore[index, union-attr]
        vigencia = (
            _TTL_FICHA_SEG
            if con_items
            else (_TTL_FICHA_AUSENTE_SEG if not hay_ficha else _TTL_FICHA_SIN_ITEMS_SEG)
        )
        if guardada is not None and ahora - guardada[0] < vigencia:
            return dict(guardada[1]) if guardada[1] is not None else None
        ficha = await self._buscar_ficha(fuentes=fuentes, codigo=codigo)
        _FICHAS[llave] = (ahora, ficha)
        return dict(ficha) if ficha is not None else None

    async def pedir_items(self, registro_id: UUID) -> None:
        """Marca la ficha para que el worker lea sus ítems primero. Idempotente y barato."""
        async with sin_contexto(self._motor) as conexion:
            await conexion.execute(
                text(
                    """
                    UPDATE registro SET items_prioridad_en = now()
                    WHERE id = :id AND items_recogidos_en IS NULL
                      AND (items_prioridad_en IS NULL
                           OR items_prioridad_en < now() - interval '1 minute')
                    """
                ),
                {"id": registro_id},
            )

    async def datos_de_presupuesto(self, registro_id: UUID) -> dict[str, Any] | None:
        """Lo que la ficha publica sobre el presupuesto, para medir la proforma al guardarla.

        Es dato público del proceso (sin contexto de empresa) y una lectura por clave primaria.
        """
        async with sin_contexto(self._motor) as conexion:
            fila = (
                (
                    await conexion.execute(
                        text(
                            """
                        SELECT datos->>'presupuesto' AS presupuesto,
                               datos->>'cantidad' AS cantidad,
                               datos->>'valor_unitario' AS valor_unitario
                        FROM registro WHERE id = :id
                        """
                        ),
                        {"id": registro_id},
                    )
                )
                .mappings()
                .first()
            )
        return dict(fila) if fila else None

    async def datos_de_entidad(self, *, negocio_id: UUID, registro_id: UUID) -> dict[str, Any]:
        """Lo que la ficha publica de la entidad (código con su RUC, dirección, cantón, contacto) y
        el texto de los anexos de la última lectura de esa ficha por la empresa.

        La ficha es pública (sin contexto); la lectura es de la empresa (con su contexto, RLS).
        """
        async with sin_contexto(self._motor) as conexion:
            ficha = (
                (
                    await conexion.execute(
                        text(
                            """
                        SELECT COALESCE(datos->>'codigo', clave_natural) AS codigo,
                               btrim(coalesce(datos->>'direccion_entrega', '')) AS direccion,
                               btrim(coalesce(datos->>'canton', '')) AS canton,
                               btrim(coalesce(datos->>'provincia', '')) AS provincia,
                               btrim(coalesce(datos->>'contacto', '')) AS contacto,
                               btrim(coalesce(datos->>'telefono', '')) AS telefono
                        FROM registro WHERE id = :id
                        """
                        ),
                        {"id": registro_id},
                    )
                )
                .mappings()
                .first()
            )
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            contexto = (
                await conexion.execute(
                    text(
                        """
                        SELECT secciones->>'contexto_anexos' FROM lectura_documento
                        WHERE negocio_id = :negocio_id AND registro_id = :registro_id
                        ORDER BY creado_en DESC LIMIT 1
                        """
                    ),
                    {"negocio_id": negocio_id, "registro_id": registro_id},
                )
            ).scalar()
        return {**(dict(ficha) if ficha else {}), "contexto_anexos": str(contexto or "")}

    async def _buscar_ficha(
        self, *, fuentes: tuple[str, ...], codigo: str
    ) -> dict[str, Any] | None:
        async with sin_contexto(self._motor) as conexion:
            fila = (
                (
                    await conexion.execute(
                        text(
                            """
                        SELECT r.id,
                               COALESCE(r.datos->>'codigo', r.clave_natural) AS codigo,
                               COALESCE(r.datos->>'objeto_compra', '') AS objeto,
                               btrim(coalesce(r.datos->>'entidad', '')) AS entidad,
                               r.fecha_publicacion,
                               r.plazo_proformas_en AS plazo,
                               r.documentos,
                               r.items,
                               r.items_recogidos_en,
                               r.items_prioridad_en,
                               r.datos->>'presupuesto' AS presupuesto,
                               r.datos->>'monto' AS monto,
                               r.datos->>'cantidad' AS cantidad,
                               r.datos->>'valor_unitario' AS valor_unitario,
                               btrim(coalesce(r.datos->>'direccion_entrega', '')) AS direccion,
                               btrim(coalesce(r.datos->>'canton', '')) AS canton,
                               btrim(coalesce(r.datos->>'provincia', '')) AS provincia,
                               btrim(coalesce(r.datos->>'contacto', '')) AS contacto,
                               btrim(coalesce(r.datos->>'telefono', '')) AS telefono
                        FROM registro r
                        JOIN fuente f ON f.id = r.fuente_id
                        WHERE r.es_vigente
                          AND f.codigo = ANY(CAST(:fuentes AS text[]))
                          AND (
                                upper(r.datos->>'codigo') = upper(:codigo)
                                OR upper(r.clave_natural) = upper(:codigo)
                          )
                        ORDER BY r.fecha_publicacion DESC NULLS LAST
                        LIMIT 1
                        """
                        ),
                        {"fuentes": list(fuentes), "codigo": codigo.strip()},
                    )
                )
                .mappings()
                .first()
            )
        return dict(fila) if fila else None
