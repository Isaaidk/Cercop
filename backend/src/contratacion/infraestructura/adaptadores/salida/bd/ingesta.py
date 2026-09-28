"""Repositorio de ingesta: acceso a las tablas del plano compartido.

Se implementa como clase —y no como funciones sueltas— porque necesita mantener el motor y recibir
dependencias inyectadas, lo que permite probar el ciclo completo contra una base real sin tocar la
red.

Las tablas del plano compartido **no tienen RLS** a propósito: los datos del SERCOP son públicos e
idénticos para todos los negocios, así que se ingestan una sola vez. El aislamiento se aplica al
plano de negocio.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncEngine

from contratacion.aplicacion.mapeo import MapeoCampo

ESTADO_OK = "ok"
ESTADO_PARCIAL = "parcial"
ESTADO_ERROR = "error"


class RepositorioIngesta:
    """Operaciones de escritura y lectura de la ingesta."""

    def __init__(self, motor: AsyncEngine) -> None:
        self._motor = motor

    # ------------------------------------------------------------------ #
    # Configuración de fuentes y mapeos
    # ------------------------------------------------------------------ #
    async def asegurar_fuente(
        self,
        codigo: str,
        nombre: str,
        endpoint_base: str,
        *,
        intervalo_min: int,
        ventana_solape_ciclos: int,
        presupuesto_peticiones_ciclo: int,
    ) -> UUID:
        """Crea la fuente si no existe y devuelve su identificador."""
        async with self._motor.begin() as conexion:
            fila = await conexion.execute(
                text(
                    """
                    INSERT INTO fuente (
                        codigo, nombre, endpoint_base, intervalo_min,
                        ventana_solape_ciclos, presupuesto_peticiones_ciclo
                    )
                    VALUES (:codigo, :nombre, :endpoint, :intervalo, :solape, :presupuesto)
                    ON CONFLICT (codigo) DO UPDATE
                        SET nombre = EXCLUDED.nombre,
                            endpoint_base = EXCLUDED.endpoint_base,
                            actualizado_en = now()
                    RETURNING id
                    """
                ),
                {
                    "codigo": codigo,
                    "nombre": nombre,
                    "endpoint": endpoint_base,
                    "intervalo": intervalo_min,
                    "solape": ventana_solape_ciclos,
                    "presupuesto": presupuesto_peticiones_ciclo,
                },
            )
            return fila.scalar_one()

    async def obtener_mapeos(self, fuente_id: UUID) -> list[MapeoCampo]:
        """Reglas de mapeo activas, ordenadas para que el resultado sea reproducible."""
        async with self._motor.connect() as conexion:
            filas = await conexion.execute(
                text(
                    """
                    SELECT clave_cruda, campo_canonico, tipo_dato, transformacion, requerido
                    FROM campo_mapeo
                    WHERE fuente_id = :fuente AND activo
                    ORDER BY orden, clave_cruda
                    """
                ),
                {"fuente": str(fuente_id)},
            )
            return [
                MapeoCampo(
                    clave_cruda=fila.clave_cruda,
                    campo_canonico=fila.campo_canonico,
                    tipo_dato=fila.tipo_dato,
                    transformacion=fila.transformacion or {},
                    requerido=fila.requerido,
                )
                for fila in filas
            ]

    async def registrar_pendientes(
        self, fuente_id: UUID, claves: Sequence[str], ejemplos: dict[str, str]
    ) -> None:
        """Anota las claves sin mapeo, acumulando cuántas veces se han visto.

        No se crea una fila por registro: se acumula por clave, porque lo que interesa es saber que
        la fuente publicó algo nuevo, no cuántas veces.
        """
        if not claves:
            return
        async with self._motor.begin() as conexion:
            for clave in claves:
                await conexion.execute(
                    text(
                        """
                        INSERT INTO campo_pendiente (fuente_id, clave_cruda, valor_ejemplo)
                        VALUES (:fuente, :clave, :ejemplo)
                        ON CONFLICT (fuente_id, clave_cruda) DO UPDATE
                            SET veces_visto = campo_pendiente.veces_visto + 1,
                                ultimo_detectado_en = now(),
                                valor_ejemplo = COALESCE(
                                    campo_pendiente.valor_ejemplo, EXCLUDED.valor_ejemplo
                                )
                        """
                    ),
                    {
                        "fuente": str(fuente_id),
                        "clave": clave,
                        "ejemplo": ejemplos.get(clave, "")[:500],
                    },
                )

    async def asegurar_mapeos(self, fuente_id: UUID, mapeos: Sequence[Mapping[str, Any]]) -> int:
        """Siembra las reglas de mapeo por defecto la primera vez.

        No sobrescribe nada: `DO NOTHING` deja intacto lo que un administrador haya ajustado. El
        catálogo por defecto es un punto de partida, no la verdad: a partir de ahí manda la tabla.
        """
        if not mapeos:
            return 0
        insertados = 0
        async with self._motor.begin() as conexion:
            for mapeo in mapeos:
                resultado = await conexion.execute(
                    text(
                        """
                        INSERT INTO campo_mapeo (
                            fuente_id, clave_cruda, campo_canonico, etiqueta,
                            tipo_dato, transformacion, requerido, orden, ancho_excel
                        )
                        VALUES (
                            :fuente, :clave, :canonico, :etiqueta,
                            :tipo, CAST(:transformacion AS jsonb), :requerido, :orden, :ancho
                        )
                        ON CONFLICT (fuente_id, clave_cruda) DO NOTHING
                        """
                    ),
                    {
                        "fuente": str(fuente_id),
                        "clave": mapeo["clave_cruda"],
                        "canonico": mapeo["campo_canonico"],
                        "etiqueta": mapeo["etiqueta"],
                        "tipo": mapeo["tipo_dato"],
                        "transformacion": json.dumps(
                            mapeo.get("transformacion", {}), ensure_ascii=False
                        ),
                        "requerido": bool(mapeo.get("requerido", False)),
                        "orden": int(mapeo.get("orden", 0)),
                        "ancho": mapeo.get("ancho_excel"),
                    },
                )
                insertados += resultado.rowcount or 0

            # Un campo que ya tiene mapeo deja de estar pendiente, aunque su fila se creara antes de
            # que el mapeo existiera. Sin esto, `campo_pendiente` acumula avisos que ya no
            # significan nada: quedaron seis claves marcadas como «sin mapear» que llevaban ciclos
            # enteros guardándose bien, porque nadie cerraba la fila al añadir su regla. Y el aviso
            # de la tabla es justo el mecanismo que dice «la fuente ha cambiado»: si grita cuando no
            # ha pasado nada, el día que pase de verdad nadie lo mirará.
            await conexion.execute(
                text(
                    """
                    UPDATE campo_pendiente p
                       SET resuelto_en = now(),
                           mapeo_id = m.id
                      FROM campo_mapeo m
                     WHERE m.fuente_id = p.fuente_id
                       AND m.clave_cruda = p.clave_cruda
                       AND p.resuelto_en IS NULL
                    """
                )
            )
        return insertados

    async def obtener_pendientes_de_ingesta(self, limite: int) -> list[dict[str, Any]]:
        """Términos que toca buscar en este ciclo, en orden de urgencia.

        El orden es la pieza que evita que un término se quede sin ingestar para siempre:

        1. primero los que **nunca** se han buscado (`ultima_ingesta_en` nulo);
        2. después los que llevan más tiempo sin buscarse;
        3. la prioridad que fije un administrador solo desempata.

        Poner la prioridad por delante del tiempo sería un error: un término urgente y otro
        tranquilo acabarían compitiendo, y el segundo no se ingestaría nunca. El orden anterior
        tenía ese defecto y además otro peor: `ultima_ingesta_en` no se actualizaba en ninguna
        parte, así que todos los términos lo tenían nulo y el `LIMIT` elegía siempre los mismos por
        fecha de creación. **Todo término añadido después del vigésimo no se ingestaba jamás.**

        El primer desempate es el número de negocios suscritos, para que un término que pide mucha
        gente no quede detrás de uno que solo interesa a un cliente.
        """
        async with self._motor.connect() as conexion:
            filas = await conexion.execute(
                text(
                    """
                    SELECT id, texto, texto_normalizado, prioridad, ultima_ingesta_en,
                           conteo_suscriptores(id) AS suscriptores
                    FROM termino
                    WHERE activo
                    ORDER BY ultima_ingesta_en NULLS FIRST,
                             prioridad DESC,
                             conteo_suscriptores(id) DESC,
                             creado_en
                    LIMIT :limite
                    """
                ),
                {"limite": limite},
            )
            return [
                {
                    "termino_id": fila.id,
                    "texto": fila.texto,
                    "texto_normalizado": fila.texto_normalizado,
                    "prioridad": fila.prioridad,
                    "ultima_ingesta_en": fila.ultima_ingesta_en,
                    "suscriptores": fila.suscriptores,
                }
                for fila in filas
            ]

    async def marcar_terminos_ingestados(self, terminos: Sequence[UUID], momento: datetime) -> int:
        """Deja constancia de que estos términos se acaban de buscar.

        Sin esta marca, `ultima_ingesta_en` se queda nulo para siempre, la cola degenera en «los
        primeros por fecha de creación» y la ventana de búsqueda se mantiene ancha indefinidamente.
        Es la pieza que hace que el orden de la cola rote de verdad.
        """
        if not terminos:
            return 0
        async with self._motor.begin() as conexion:
            resultado = await conexion.execute(
                text("UPDATE termino SET ultima_ingesta_en = :momento WHERE id = ANY(:terminos)"),
                {"momento": momento, "terminos": list(terminos)},
            )
        return int(resultado.rowcount or 0)

    # ------------------------------------------------------------------ #
    # Sincronizaciones
    # ------------------------------------------------------------------ #
    async def ultima_sincronizacion_ok(self, fuente_id: UUID) -> datetime | None:
        """Marca de agua: hasta dónde llegó el último ciclo completo.

        Solo cuentan los ciclos `ok` o `parcial`: si un ciclo falló, la ventana no avanza, para que
        la siguiente ejecución vuelva a cubrir el hueco.
        """
        async with self._motor.connect() as conexion:
            fila = await conexion.execute(
                text(
                    """
                    SELECT watermark_fecha
                    FROM sincronizacion
                    WHERE fuente_id = :fuente AND estado IN ('ok', 'parcial')
                    ORDER BY iniciada_en DESC
                    LIMIT 1
                    """
                ),
                {"fuente": str(fuente_id)},
            )
            return fila.scalar_one_or_none()

    async def iniciar_sincronizacion(self, fuente_id: UUID) -> UUID:
        async with self._motor.begin() as conexion:
            fila = await conexion.execute(
                text("INSERT INTO sincronizacion (fuente_id) VALUES (:fuente) RETURNING id"),
                {"fuente": str(fuente_id)},
            )
            return fila.scalar_one()

    async def cerrar_sincronizacion(
        self,
        sincronizacion_id: UUID,
        *,
        estado: str,
        peticiones: int,
        nuevos: int,
        actualizados: int,
        errores: int,
        avisos: Sequence[str],
        watermark: datetime | None,
    ) -> None:
        async with self._motor.begin() as conexion:
            await conexion.execute(
                text(
                    """
                    UPDATE sincronizacion
                       SET terminada_en = now(),
                           estado = :estado,
                           peticiones = :peticiones,
                           nuevos = :nuevos,
                           actualizados = :actualizados,
                           errores = :errores,
                           avisos = CAST(:avisos AS jsonb),
                           watermark_fecha = :watermark
                     WHERE id = :id
                    """
                ),
                {
                    "id": str(sincronizacion_id),
                    "estado": estado,
                    "peticiones": peticiones,
                    "nuevos": nuevos,
                    "actualizados": actualizados,
                    "errores": errores,
                    "avisos": json.dumps(list(avisos), ensure_ascii=False),
                    "watermark": watermark,
                },
            )

    # ------------------------------------------------------------------ #
    # Registros
    # ------------------------------------------------------------------ #
    async def huellas_existentes(self, fuente_id: UUID, claves: Sequence[str]) -> dict[str, str]:
        """Huella de contenido de los registros ya conocidos, por clave natural."""
        if not claves:
            return {}
        consulta = text(
            "SELECT clave_natural, hash_contenido FROM registro "
            "WHERE fuente_id = :fuente AND clave_natural IN :claves"
        ).bindparams(bindparam("claves", expanding=True))

        async with self._motor.connect() as conexion:
            filas = await conexion.execute(
                consulta, {"fuente": str(fuente_id), "claves": list(claves)}
            )
            return {fila.clave_natural: fila.hash_contenido for fila in filas}

    async def guardar_registro(
        self,
        fuente_id: UUID,
        *,
        clave: str,
        datos: dict[str, Any],
        crudo: dict[str, Any],
        texto_busqueda: str,
        hash_contenido: str,
        fecha_publicacion: datetime | None,
    ) -> UUID:
        """Inserta o actualiza el registro y devuelve su identificador.

        El conflicto se resuelve por clave natural: es lo que hace la ingesta idempotente. Se guarda
        el payload íntegro en `crudo` para no perder ningún campo que no sepamos mapear todavía.

        `ultima_vez_visto` solo se actualiza cuando el contenido cambia. Es deliberado: marcar las
        ~1.700 filas de NCO en cada ciclo, 96 veces al día, sería un desperdicio de escrituras sin
        aportar nada.
        """
        async with self._motor.begin() as conexion:
            fila = await conexion.execute(
                text(
                    """
                    INSERT INTO registro (
                        fuente_id, clave_natural, datos, crudo, texto_busqueda,
                        hash_contenido, fecha_publicacion
                    )
                    VALUES (
                        :fuente, :clave, CAST(:datos AS jsonb), CAST(:crudo AS jsonb),
                        :texto, :hash, CAST(:fecha AS timestamptz)
                    )
                    ON CONFLICT (fuente_id, clave_natural) DO UPDATE
                        SET datos = EXCLUDED.datos,
                            crudo = EXCLUDED.crudo,
                            texto_busqueda = EXCLUDED.texto_busqueda,
                            hash_contenido = EXCLUDED.hash_contenido,
                            fecha_publicacion = EXCLUDED.fecha_publicacion,
                            ultima_vez_visto = now()
                    RETURNING id
                    """
                ),
                {
                    "fuente": str(fuente_id),
                    "clave": clave,
                    "datos": json.dumps(datos, ensure_ascii=False, default=str),
                    "crudo": json.dumps(crudo, ensure_ascii=False, default=str),
                    "texto": texto_busqueda,
                    "hash": hash_contenido,
                    "fecha": fecha_publicacion,
                },
            )
            return fila.scalar_one()

    async def agregar_historial(
        self, registro_id: UUID, *, datos: dict[str, Any], hash_contenido: str
    ) -> None:
        """Añade una versión al histórico. Solo se llama cuando el contenido cambió.

        Esta tabla es el activo comercial del producto: la fuente no publica histórico de
        necesidades, así que lo que no se guarde aquí, se pierde.
        """
        async with self._motor.begin() as conexion:
            await conexion.execute(
                text(
                    """
                    INSERT INTO registro_historial (registro_id, datos, hash_contenido)
                    VALUES (:registro, CAST(:datos AS jsonb), :hash)
                    """
                ),
                {
                    "registro": str(registro_id),
                    "datos": json.dumps(datos, ensure_ascii=False, default=str),
                    "hash": hash_contenido,
                },
            )
