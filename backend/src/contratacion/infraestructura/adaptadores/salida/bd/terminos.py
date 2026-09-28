"""Adaptador de salida: catálogo de términos, suscripciones y cola de ingesta.

Conviven aquí dos planos distintos, y confundirlos es la causa habitual de errores en este tipo de
sistema:

- **`termino` es del plano compartido**: el término es único para toda la plataforma y se ingesta
  una sola vez. No lleva `negocio_id` ni RLS.
- **`suscripcion_termino` es del plano de negocio**: dice qué negocios quieren ese término. Está
  protegida por RLS, así que **toda** consulta a esa tabla necesita contexto de negocio. Una
  consulta sin contexto no da error: devuelve cero filas, que es exactamente el fallo silencioso que
  hay que evitar.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from contratacion.dominio.errores import DatoInvalido
from contratacion.dominio.palabras import normalizar_termino
from contratacion.infraestructura.adaptadores.salida.bd.contexto import (
    contexto_negocio,
    sin_contexto,
)

registro = logging.getLogger(__name__)


class RepositorioTerminosBd:
    """Implementación sobre PostgreSQL."""

    def __init__(self, motor: AsyncEngine) -> None:
        self._motor = motor

    async def asegurar_termino(self, texto: str, *, origen: str = "usuario") -> UUID:
        normalizado = normalizar_termino(texto)
        async with sin_contexto(self._motor) as conexion:
            valor: Any = (
                await conexion.execute(
                    text(
                        """
                        INSERT INTO termino (texto, texto_normalizado, origen)
                        VALUES (:texto, :normalizado, :origen)
                        ON CONFLICT (texto_normalizado) DO UPDATE
                            SET texto = termino.texto,
                                origen = termino.origen
                        RETURNING id
                        """
                    ),
                    {"texto": texto, "normalizado": normalizado, "origen": origen},
                )
            ).scalar_one()
        return valor if isinstance(valor, UUID) else UUID(str(valor))

    async def suscribir(self, negocio_id: UUID, termino_id: UUID) -> bool:
        """Suscribe el negocio. Devuelve `True` solo si la suscripción es nueva.

        Se consulta antes de escribir en lugar de usar `ON CONFLICT` con `RETURNING`, porque
        PostgreSQL no devuelve fila cuando la inserción no ocurre y no hay forma limpia de
        distinguir «ya estaba» de «se acaba de crear» en una sola sentencia.
        """
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            previa = (
                await conexion.execute(
                    text(
                        """
                        SELECT activa FROM suscripcion_termino
                        WHERE negocio_id = :negocio_id AND termino_id = :termino_id
                        """
                    ),
                    {"negocio_id": negocio_id, "termino_id": termino_id},
                )
            ).scalar_one_or_none()

            await conexion.execute(
                text(
                    """
                    INSERT INTO suscripcion_termino (negocio_id, termino_id, activa)
                    VALUES (:negocio_id, :termino_id, TRUE)
                    ON CONFLICT (negocio_id, termino_id) DO UPDATE SET activa = TRUE
                    """
                ),
                {"negocio_id": negocio_id, "termino_id": termino_id},
            )

        return previa is None or previa is False

    async def alta_de_termino(
        self,
        negocio_id: UUID,
        *,
        texto: str,
        maximo_terminos: int,
        origen: str = "usuario",
    ) -> Mapping[str, Any]:
        """Crea el término, suscribe el negocio y devuelve su estado, en **una** transacción.

        Antes esto eran cinco bloques de base —enumerar los términos del negocio, crear el término,
        suscribir, leer su estado y contar suscriptores— y cada bloque abría y cerraba su conexión.
        Contra una base remota, esas cinco negociaciones de conexión costaban más que el trabajo
        real; medido, el alta se iba por encima del segundo y se percibía como que «agregar una
        palabra clave tarda demasiado».

        Unirlas no es solo una optimización: **el tope de palabras se comprueba en la misma
        transacción en la que se escribe**. Antes se contaban los términos activos y se suscribía
        después, en transacciones distintas, así que dos peticiones simultáneas del mismo negocio
        podían leer veinte cada una y dejar veintidós suscritas. Con la comprobación y la inserción
        juntas, el tope es exacto y no depende de que las peticiones no coincidan en el tiempo.

        `termino` es del plano compartido y no mira el contexto de negocio, así que fijarlo para
        leer `suscripcion_termino` no le afecta: las dos tablas conviven en la misma transacción.
        """
        normalizado = normalizar_termino(texto)

        async with contexto_negocio(self._motor, negocio_id) as conexion:
            previos: Sequence[Any] = (
                (
                    await conexion.execute(
                        text(
                            """
                            SELECT termino_id FROM suscripcion_termino
                            WHERE negocio_id = :negocio_id AND activa
                            """
                        ),
                        {"negocio_id": negocio_id},
                    )
                )
                .scalars()
                .all()
            )

            valor: Any = (
                await conexion.execute(
                    text(
                        """
                        INSERT INTO termino (texto, texto_normalizado, origen)
                        VALUES (:texto, :normalizado, :origen)
                        ON CONFLICT (texto_normalizado) DO UPDATE
                            SET texto = termino.texto,
                                origen = termino.origen
                        RETURNING id
                        """
                    ),
                    {"texto": texto, "normalizado": normalizado, "origen": origen},
                )
            ).scalar_one()
            termino_id = valor if isinstance(valor, UUID) else UUID(str(valor))

            # `previos` solo trae las activas, así que una suscripción desactivada cuenta como
            # nueva al reactivarse: es lo que el panel muestra y lo que ya hacía `suscribir`.
            ya_estaba = any(UUID(str(previa)) == termino_id for previa in previos)
            if not ya_estaba and len(previos) >= maximo_terminos:
                raise DatoInvalido(
                    f"El negocio alcanzó el máximo de {maximo_terminos} palabras clave activas. "
                    "Quita alguna antes de agregar otra."
                )

            await conexion.execute(
                text(
                    """
                    INSERT INTO suscripcion_termino (negocio_id, termino_id, activa)
                    VALUES (:negocio_id, :termino_id, TRUE)
                    ON CONFLICT (negocio_id, termino_id) DO UPDATE SET activa = TRUE
                    """
                ),
                {"negocio_id": negocio_id, "termino_id": termino_id},
            )

            estado = (
                (
                    await conexion.execute(
                        text(
                            """
                            SELECT id, texto, texto_normalizado, activo, prioridad,
                                   ultima_ingesta_en,
                                   conteo_suscriptores(id) AS suscriptores
                            FROM termino WHERE id = :termino_id
                            """
                        ),
                        {"termino_id": termino_id},
                    )
                )
                .mappings()
                .one()
            )

        return {**dict(estado), "suscripcion_nueva": not ya_estaba}

    async def alta_de_terminos(
        self,
        negocio_id: UUID,
        *,
        textos: Sequence[str],
        maximo_terminos: int,
        origen: str = "usuario",
    ) -> tuple[Mapping[str, Any], ...]:
        """Crea y suscribe **varios** términos de una vez, en una sola transacción.

        Es la versión en bloque de `alta_de_termino`, y existe por una razón de tiempo medible:
        hacerlo término a término serían dos consultas por palabra más una conexión por llamada.
        Con treinta y cinco palabras, a ~95 ms por ida y vuelta, la espera pasaría del minuto y el
        usuario creería que el panel se ha colgado.

        Aquí son **tres consultas en total**, sin importar cuántas palabras vengan:

        1. Los términos que el negocio ya tiene activos, para comprobar el tope.
        2. Un `INSERT ... unnest` que crea de golpe todos los que falten.
        3. Un `INSERT ... SELECT` que suscribe todos los términos de la lista.

        Las palabras se deduplican por su forma normalizada **antes** de ir a la base. No es solo
        ahorro: repetir una clave dentro del mismo `ON CONFLICT DO UPDATE` es un error de PostgreSQL
        («cannot affect row a second time»), así que la lista llega sin repetidos. Y la forma
        normalizada es la clave real del conflicto, no el texto tal cual.
        """
        # Deduplicación conservando el orden y el texto original de la primera aparición.
        unicos: dict[str, str] = {}
        for texto in textos:
            limpio = " ".join(str(texto).split())
            if not limpio:
                continue
            unicos.setdefault(normalizar_termino(limpio), limpio)

        if not unicos:
            return ()

        claves = list(unicos)
        valores = [unicos[clave] for clave in claves]

        async with contexto_negocio(self._motor, negocio_id) as conexion:
            previos: set[Any] = set(
                (
                    await conexion.execute(
                        text(
                            """
                            SELECT termino_id FROM suscripcion_termino
                            WHERE negocio_id = :negocio_id AND activa
                            """
                        ),
                        {"negocio_id": negocio_id},
                    )
                )
                .scalars()
                .all()
            )

            filas = (
                (
                    await conexion.execute(
                        text(
                            """
                            INSERT INTO termino (texto, texto_normalizado, origen)
                            SELECT * FROM unnest(
                                CAST(:textos AS text[]),
                                CAST(:normalizados AS text[]),
                                CAST(:origenes AS text[])
                            )
                            ON CONFLICT (texto_normalizado) DO UPDATE
                                SET texto = termino.texto,
                                    origen = termino.origen
                            RETURNING id, texto_normalizado
                            """
                        ),
                        {
                            "textos": valores,
                            "normalizados": claves,
                            "origenes": [origen] * len(claves),
                        },
                    )
                )
                .mappings()
                .all()
            )

            identificadores = {str(fila["texto_normalizado"]): fila["id"] for fila in filas}
            nuevas = [
                identificadores[clave] for clave in claves if identificadores[clave] not in previos
            ]

            if len(previos) + len(nuevas) > maximo_terminos:
                raise DatoInvalido(
                    f"Con estas palabras el negocio llegaría a {len(previos) + len(nuevas)} "
                    f"palabras clave activas y el máximo es {maximo_terminos}. "
                    "Quita algunas antes de agregar más."
                )

            await conexion.execute(
                text(
                    """
                    INSERT INTO suscripcion_termino (negocio_id, termino_id, activa)
                    SELECT :negocio_id, t.id, TRUE
                      FROM termino t
                     WHERE t.texto_normalizado = ANY(CAST(:normalizados AS text[]))
                    ON CONFLICT (negocio_id, termino_id) DO UPDATE SET activa = TRUE
                    """
                ),
                {"negocio_id": negocio_id, "normalizados": claves},
            )

        return tuple(
            {
                "termino_id": identificadores[clave],
                "texto": unicos[clave],
                "suscripcion_nueva": identificadores[clave] not in previos,
            }
            for clave in claves
        )

    async def desuscribir(self, negocio_id: UUID, termino_id: UUID) -> bool:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            resultado = await conexion.execute(
                text(
                    """
                    UPDATE suscripcion_termino SET activa = FALSE
                    WHERE negocio_id = :negocio_id AND termino_id = :termino_id AND activa
                    """
                ),
                {"negocio_id": negocio_id, "termino_id": termino_id},
            )
            return bool(resultado.rowcount)

    async def terminos_del_negocio(self, negocio_id: UUID) -> Sequence[Mapping[str, Any]]:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            filas = (
                (
                    await conexion.execute(
                        text(
                            """
                            SELECT st.termino_id, t.texto, t.texto_normalizado, t.prioridad,
                                   t.activo, t.ultima_ingesta_en
                            FROM suscripcion_termino st
                            JOIN termino t ON t.id = st.termino_id
                            WHERE st.negocio_id = :negocio_id AND st.activa
                            ORDER BY t.texto
                            """
                        ),
                        {"negocio_id": negocio_id},
                    )
                )
                .mappings()
                .all()
            )
        return tuple(dict(fila) for fila in filas)

    async def estado_termino(self, termino_id: UUID) -> Mapping[str, Any] | None:
        async with sin_contexto(self._motor) as conexion:
            fila = (
                (
                    await conexion.execute(
                        text(
                            """
                            SELECT id, texto, texto_normalizado, activo, prioridad,
                                   ultima_ingesta_en
                            FROM termino WHERE id = :termino_id
                            """
                        ),
                        {"termino_id": termino_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return dict(fila) if fila else None

    async def pendientes_de_ingesta(self, limite: int) -> Sequence[Mapping[str, Any]]:
        """Cola ordenada: primero lo que piden más negocios, después lo más olvidado.

        El conteo de suscriptores sale de una función que atraviesa RLS devolviendo solo un número.
        El planificador corre sin contexto de negocio, así que una consulta normal a
        `suscripcion_termino` contaría cero y todos los términos tendrían la misma prioridad.
        """
        async with sin_contexto(self._motor) as conexion:
            filas = (
                (
                    await conexion.execute(
                        text(
                            """
                            SELECT t.id, t.texto, t.texto_normalizado, t.prioridad,
                                   t.ultima_ingesta_en,
                                   conteo_suscriptores(t.id) AS suscriptores
                            FROM termino t
                            WHERE t.activo
                            ORDER BY conteo_suscriptores(t.id) DESC,
                                     t.ultima_ingesta_en ASC NULLS FIRST,
                                     t.prioridad DESC,
                                     t.texto ASC
                            LIMIT :limite
                            """
                        ),
                        {"limite": limite},
                    )
                )
                .mappings()
                .all()
            )
        return tuple(dict(fila) for fila in filas)

    async def suscriptores(self, termino_id: UUID) -> int:
        async with sin_contexto(self._motor) as conexion:
            valor: Any = (
                await conexion.execute(
                    text("SELECT conteo_suscriptores(:termino_id)"),
                    {"termino_id": termino_id},
                )
            ).scalar_one()
        return int(valor)

    async def marcar_ingestado(self, termino_id: UUID, momento: datetime) -> None:
        async with sin_contexto(self._motor) as conexion:
            await conexion.execute(
                text("UPDATE termino SET ultima_ingesta_en = :momento WHERE id = :termino_id"),
                {"momento": momento, "termino_id": termino_id},
            )
