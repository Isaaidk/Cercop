"""Adaptador de salida: políticas y consentimientos.

Se separan las dos lecturas porque viven en planos distintos y confundirlas sería un fallo de
aislamiento:

- Las **políticas** se leen y se escriben **sin contexto de negocio**. Su tabla no tiene
  `negocio_id`: el mismo texto rige para todos. Abrir una transacción con contexto para leerlas
  sería inofensivo hoy y engañoso mañana, porque sugeriría que son de alguien.
- Los **consentimientos** van siempre dentro del contexto del negocio. Su tabla está protegida por
  políticas, y una consulta sin contexto devolvería cero filas **sin dar ningún error**: el sistema
  creería que nadie ha aceptado nunca nada y pediría la aceptación en cada petición.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from contratacion.dominio.errores import NoEncontrado
from contratacion.dominio.politicas import (
    Consentimiento,
    Politica,
    TipoPolitica,
    huella_texto,
)
from contratacion.infraestructura.adaptadores.salida.bd.contexto import (
    contexto_negocio,
    sin_contexto,
)
from contratacion.infraestructura.adaptadores.salida.bd.cuentas import agente_valido, ip_valida

registro = logging.getLogger(__name__)

CAMPOS_POLITICA = "id, tipo, version, texto, hash, vigente_desde"
CAMPOS_CONSENTIMIENTO = "tipo, version_texto, texto_hash, aceptado_en, revocado_en"


def _a_politica(fila: Mapping[Any, Any]) -> Politica:
    return Politica(
        tipo=TipoPolitica(str(fila["tipo"])),
        version=int(fila["version"]),
        texto=str(fila["texto"]),
        hash=str(fila["hash"]),
        vigente_desde=fila["vigente_desde"],
    )


def _a_consentimiento(fila: Mapping[Any, Any]) -> Consentimiento:
    return Consentimiento(
        tipo=TipoPolitica(str(fila["tipo"])),
        version=int(fila["version_texto"]),
        hash_texto=str(fila["texto_hash"]),
        aceptado_en=fila["aceptado_en"],
        revocado_en=fila["revocado_en"],
    )


class RepositorioPoliticasBd:
    """Versiones publicadas de los textos legales. Plano compartido, sin RLS."""

    def __init__(self, motor: AsyncEngine) -> None:
        self._motor = motor

    async def vigentes(self) -> Sequence[Politica]:
        """La versión más alta de cada tipo, en una sola consulta.

        Se resuelve con `DISTINCT ON`, que es específico de PostgreSQL y hace exactamente esto: de
        cada tipo, la fila que quede primera según el `ORDER BY`. Hacerlo con dos consultas —una
        para saber las versiones y otra para traerlas— abriría la puerta a que una publicación
        ocurriera entre las dos y el resultado fuera incoherente.
        """
        async with sin_contexto(self._motor) as conexion:
            filas = (
                (
                    await conexion.execute(
                        text(
                            f"""
                            SELECT DISTINCT ON (tipo) {CAMPOS_POLITICA}
                            FROM politica_version
                            ORDER BY tipo, version DESC
                            """
                        )
                    )
                )
                .mappings()
                .all()
            )
        return tuple(_a_politica(fila) for fila in filas)

    async def vigente(self, tipo: TipoPolitica) -> Politica | None:
        async with sin_contexto(self._motor) as conexion:
            fila = (
                (
                    await conexion.execute(
                        text(
                            f"""
                            SELECT {CAMPOS_POLITICA}
                            FROM politica_version
                            WHERE tipo = :tipo
                            ORDER BY version DESC
                            LIMIT 1
                            """
                        ),
                        {"tipo": str(tipo)},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return _a_politica(fila) if fila else None

    async def publicar(self, *, tipo: TipoPolitica, texto: str, momento: datetime) -> Politica:
        """Publica el texto como la versión siguiente.

        El número de versión se calcula sumando uno al máximo de ese tipo, dentro de la misma
        transacción que inserta. La suma sola **no basta**: con dos publicaciones a la vez, las dos
        leerían el mismo máximo y una fallaría contra la restricción de unicidad. Por eso se toma
        antes un cerrojo de asesoría por tipo, que serializa las publicaciones y no bloquea a los
        lectores.

        Se prefiere un cerrojo —y no un reintento ante el error de unicidad— porque publicar es una
        operación humana y excepcional: unas veces al año, desde una migración o desde un script. Un
        cerrojo cuesta una espera imperceptible y deja el código sin el bucle de reintentos; un
        reintento habría que escribirlo bien, y escribirlo mal es fácil.

        La huella se calcula aquí, sobre el texto que se acaba de guardar. Calcularla en otro sitio
        dejaría abierta la posibilidad de guardar un texto y registrar la huella de otro.
        """
        huella = huella_texto(texto)
        async with sin_contexto(self._motor) as conexion:
            # El cerrojo vive lo que vive la transacción, así que se suelta solo aunque algo falle.
            await conexion.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:clave))"),
                {"clave": f"politica_version:{tipo}"},
            )
            fila = (
                (
                    await conexion.execute(
                        text(
                            f"""
                            INSERT INTO politica_version (tipo, version, texto, hash, vigente_desde)
                            VALUES (
                                :tipo,
                                COALESCE(
                                    (SELECT MAX(version) FROM politica_version WHERE tipo = :tipo),
                                    0
                                ) + 1,
                                :texto,
                                :hash,
                                :momento
                            )
                            RETURNING {CAMPOS_POLITICA}
                            """
                        ),
                        {
                            "tipo": str(tipo),
                            "texto": texto,
                            "hash": huella,
                            "momento": momento,
                        },
                    )
                )
                .mappings()
                .one()
            )
        publicada = _a_politica(fila)
        registro.info(
            "Política publicada: tipo=%s version=%s hash=%s",
            publicada.tipo,
            publicada.version,
            publicada.hash[:12],
        )
        return publicada

    async def marcar_pendientes(self, *, tipo: TipoPolitica, version: int) -> int:
        """Marca la versión como pendiente en todas las cuentas de todos los negocios.

        Recorre la tabla de usuarios entera, y eso es intencional: publicar una versión nueva obliga
        a **todos** los usuarios a aceptarla, incluidos los que llevan meses sin entrar. Limitar el
        marcado a las cuentas activas dejaría a los demás entrando con una aceptación de la versión
        anterior.

        Va sin contexto de negocio porque afecta a todos. Es una de las pocas escrituras del sistema
        que lo hace, y está aquí, en el adaptador, a la vista.
        """
        async with self._motor.begin() as conexion:
            resultado = await conexion.execute(
                text(
                    """
                    UPDATE usuario
                    SET debe_aceptar_politica_version = :version
                    WHERE debe_aceptar_politica_version IS NULL
                       OR debe_aceptar_politica_version < :version
                    """
                ),
                {"version": version},
            )
        marcadas = int(resultado.rowcount or 0)
        registro.info(
            "Política %s v%s marcada como pendiente en %d cuentas", tipo, version, marcadas
        )
        return marcadas


class RepositorioConsentimientosBd:
    """Aceptaciones y revocaciones. Plano de negocio, siempre con contexto."""

    def __init__(self, motor: AsyncEngine) -> None:
        self._motor = motor

    async def registrar(
        self,
        *,
        negocio_id: UUID,
        usuario_id: UUID,
        tipo: TipoPolitica,
        version: int,
        hash_texto: str,
        momento: datetime,
        ip: str | None = None,
        user_agent: str | None = None,
        metodo: str = "formulario",
    ) -> UUID:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            fila: Any = (
                await conexion.execute(
                    text(
                        """
                        INSERT INTO consentimiento (negocio_id, usuario_id, tipo, version_texto,
                                                    texto_hash, aceptado_en, ip, user_agent, metodo)
                        VALUES (:negocio_id, :usuario_id, :tipo, :version, :hash, :momento,
                                :ip, :user_agent, :metodo)
                        RETURNING id
                        """
                    ),
                    {
                        "negocio_id": negocio_id,
                        "usuario_id": usuario_id,
                        "tipo": str(tipo),
                        # `version_texto` es de tipo texto en el esquema aunque el número de versión
                        # sea entero. Se guarda tal cual para no depender de una conversión.
                        "version": str(version),
                        "hash": hash_texto,
                        "momento": momento,
                        "ip": ip_valida(ip),
                        "user_agent": agente_valido(user_agent),
                        "metodo": metodo,
                    },
                )
            ).scalar_one()
        return UUID(str(fila))

    async def del_usuario(self, *, negocio_id: UUID, usuario_id: UUID) -> Sequence[Consentimiento]:
        """Historial de esa cuenta, del más reciente al más antiguo.

        Incluye las revocadas: el historial es la prueba de lo que ocurrió, y esconder las
        revocaciones eliminaría justamente el registro del ejercicio de un derecho.
        """
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            filas = (
                (
                    await conexion.execute(
                        text(
                            f"""
                            SELECT {CAMPOS_CONSENTIMIENTO}
                            FROM consentimiento
                            WHERE usuario_id = :usuario_id
                            ORDER BY aceptado_en DESC, tipo
                            """
                        ),
                        {"usuario_id": usuario_id},
                    )
                )
                .mappings()
                .all()
            )
        return tuple(_a_consentimiento(fila) for fila in filas)

    async def revocar(
        self, *, negocio_id: UUID, usuario_id: UUID, tipo: TipoPolitica, momento: datetime
    ) -> int:
        """Marca como revocadas las aceptaciones vigentes de ese tipo.

        Solo toca las que están vigentes (`revocado_en IS NULL`): revocar dos veces no debe
        reescribir la fecha de la primera revocación, que es el dato que interesa.
        """
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            resultado = await conexion.execute(
                text(
                    """
                    UPDATE consentimiento
                    SET revocado_en = :momento
                    WHERE usuario_id = :usuario_id
                      AND tipo = :tipo
                      AND revocado_en IS NULL
                    """
                ),
                {"usuario_id": usuario_id, "tipo": str(tipo), "momento": momento},
            )
        return int(resultado.rowcount or 0)

    async def pendiente_de(self, *, negocio_id: UUID, usuario_id: UUID) -> int | None:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            fila = (
                await conexion.execute(
                    text(
                        """
                        SELECT debe_aceptar_politica_version
                        FROM usuario WHERE id = :usuario_id
                        """
                    ),
                    {"usuario_id": usuario_id},
                )
            ).one_or_none()
        if fila is None:
            # La cuenta no está a la vista dentro de este negocio. No se devuelve «nada pendiente»:
            # afirmar que esta persona no debe aceptar nada cuando no se ha podido leer su fila
            # sería abrir la puerta justo cuando no se puede comprobar si debía estar cerrada.
            raise NoEncontrado(
                "Tu cuenta no está disponible en este espacio de trabajo. Vuelve a iniciar sesión."
            )
        return None if fila[0] is None else int(fila[0])

    async def marcar_pendiente(self, *, negocio_id: UUID, usuario_id: UUID, version: int) -> None:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            await conexion.execute(
                text(
                    """
                    UPDATE usuario SET debe_aceptar_politica_version = :version
                    WHERE id = :usuario_id
                    """
                ),
                {"usuario_id": usuario_id, "version": version},
            )

    async def limpiar_pendiente(self, *, negocio_id: UUID, usuario_id: UUID) -> None:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            await conexion.execute(
                text(
                    """
                    UPDATE usuario SET debe_aceptar_politica_version = NULL
                    WHERE id = :usuario_id
                    """
                ),
                {"usuario_id": usuario_id},
            )
