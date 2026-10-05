"""Adaptador de salida: cuentas, sesiones y auditoría.

Casi todas las operaciones se ejecutan dentro del contexto del negocio, porque tanto `usuario` como
`sesion` y `auditoria` están protegidas por RLS. La única excepción es `resolver`, que llama a una
función `SECURITY DEFINER` que devuelve dos identificadores y nada más: es la pieza que permite
averiguar a qué negocio pertenece un correo **antes** de tener contexto, sin abrir la tabla.

Dos detalles menores que evitan problemas reales:

- La dirección IP y el agente de usuario llegan de cabeceras que el cliente controla. Se validan y
  se truncan antes de guardarlos: una cabecera arbitraria no puede convertirse en un error de la
  base —`inet` rechaza lo que no es una dirección— ni en un campo de megabytes.
- La auditoría **exige** negocio. Un intento fallido con un correo desconocido no se puede auditar
  en esta tabla porque la política lo impide, y se registra en el registro de la aplicación: no es
  un olvido, es la consecuencia de que la tabla sea del plano de negocio.
"""

from __future__ import annotations

import ipaddress
import logging
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from contratacion.aplicacion.puertos.cuentas import Cuenta, SesionGuardada
from contratacion.dominio.sesiones import EstadoSesion, MotivoRevocacion, Sesion
from contratacion.infraestructura.adaptadores.salida.bd.contexto import contexto_negocio

registro = logging.getLogger(__name__)

LONGITUD_MAXIMA_AGENTE = 300

CAMPOS_CUENTA = """
    id, negocio_id, email, nombre, rol, estado, hash_password,
    intentos_fallidos, bloqueado_hasta, debe_aceptar_politica_version
"""

CAMPOS_SESION = """
    id, usuario_id, negocio_id, creada_en, ultimo_uso_en, expira_en, estado, revocada_motivo
"""


def ip_valida(valor: str | None) -> str | None:
    """Devuelve la dirección si es una IP válida, o `None`.

    La cabecera de la que sale la IP la controla el cliente: sin validarla, un valor arbitrario
    haría fallar la inserción por el tipo `inet` y el fallo parecería un error del servidor.
    """
    if not valor:
        return None
    try:
        return str(ipaddress.ip_address(valor.strip()))
    except ValueError:
        # Puede venir con puerto («1.2.3.4:5678») o con varias direcciones separadas por comas.
        primero = valor.split(",", 1)[0].strip().split(":", 1)[0]
        try:
            return str(ipaddress.ip_address(primero))
        except ValueError:
            return None


def agente_valido(valor: str | None) -> str | None:
    """Recorta el agente de usuario al tamaño previsto."""
    if not valor:
        return None
    limpio = valor.strip()
    return limpio[:LONGITUD_MAXIMA_AGENTE] if limpio else None


def _a_cuenta(fila: Mapping[Any, Any]) -> Cuenta:
    return Cuenta(
        usuario_id=fila["id"],
        negocio_id=fila["negocio_id"],
        email=str(fila["email"]),
        nombre=str(fila["nombre"]),
        rol=str(fila["rol"]),
        estado=str(fila["estado"]),
        hash_password=str(fila["hash_password"]),
        intentos_fallidos=int(fila["intentos_fallidos"]),
        bloqueado_hasta=fila["bloqueado_hasta"],
        debe_aceptar_politica_version=fila["debe_aceptar_politica_version"],
    )


def _a_sesion(fila: Mapping[Any, Any]) -> Sesion:
    return Sesion(
        id=fila["id"],
        usuario_id=fila["usuario_id"],
        negocio_id=fila["negocio_id"],
        creada_en=fila["creada_en"],
        ultimo_uso_en=fila["ultimo_uso_en"],
        expira_en=fila["expira_en"],
        estado=EstadoSesion(str(fila["estado"])),
        motivo_revocacion=_a_motivo(fila.get("revocada_motivo")),
    )


def _a_motivo(valor: object) -> MotivoRevocacion | None:
    """Convierte el motivo guardado, tolerando un valor fuera del catálogo.

    La columna tiene una restricción `CHECK`, así que en teoría no puede haber otro valor. Se
    contempla igualmente porque una restricción se puede ampliar en una migración y este código
    podría desplegarse antes que ella: un motivo desconocido deja la sesión sin explicación, que es
    mucho mejor que tumbar el listado de presencia entero por una fila.
    """
    if valor is None:
        return None
    try:
        return MotivoRevocacion(str(valor))
    except ValueError:
        registro.warning("Motivo de revocación desconocido en la base: %r", valor)
        return None


class RepositorioCuentasBd:
    """Implementación sobre PostgreSQL."""

    def __init__(self, motor: AsyncEngine) -> None:
        self._motor = motor

    async def resolver(self, email: str) -> tuple[UUID, UUID] | None:
        """Identificadores del correo, sin contexto de negocio y sin exponer nada más."""
        async with self._motor.connect() as conexion:
            fila = (
                await conexion.execute(
                    text("SELECT id_usuario, id_negocio FROM resolver_cuenta(:email)"),
                    {"email": email},
                )
            ).one_or_none()

        if fila is None:
            return None
        return fila[0], fila[1]

    async def obtener(self, *, negocio_id: UUID, usuario_id: UUID) -> Cuenta | None:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            fila = (
                (
                    await conexion.execute(
                        text(f"SELECT {CAMPOS_CUENTA} FROM usuario WHERE id = :usuario_id"),
                        {"usuario_id": usuario_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return _a_cuenta(fila) if fila else None

    async def registrar_acceso_correcto(
        self, *, negocio_id: UUID, usuario_id: UUID, momento: datetime
    ) -> None:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            await conexion.execute(
                text(
                    """
                    UPDATE usuario
                    SET intentos_fallidos = 0, bloqueado_hasta = NULL, ultimo_acceso = :momento
                    WHERE id = :usuario_id
                    """
                ),
                {"usuario_id": usuario_id, "momento": momento},
            )

    async def registrar_fallo(
        self,
        *,
        negocio_id: UUID,
        usuario_id: UUID,
        intentos: int,
        bloqueado_hasta: datetime | None,
    ) -> None:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            await conexion.execute(
                text(
                    """
                    UPDATE usuario
                    SET intentos_fallidos = :intentos, bloqueado_hasta = :bloqueado_hasta
                    WHERE id = :usuario_id
                    """
                ),
                {
                    "usuario_id": usuario_id,
                    "intentos": intentos,
                    "bloqueado_hasta": bloqueado_hasta,
                },
            )

    async def actualizar_huella(self, *, negocio_id: UUID, usuario_id: UUID, huella: str) -> None:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            await conexion.execute(
                text("UPDATE usuario SET hash_password = :huella WHERE id = :usuario_id"),
                {"usuario_id": usuario_id, "huella": huella},
            )

    async def cambiar_estado(
        self, *, negocio_id: UUID, usuario_id: UUID, estado: str, momento: datetime
    ) -> None:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            await conexion.execute(
                text("UPDATE usuario SET estado = :estado WHERE id = :usuario_id"),
                {"usuario_id": usuario_id, "estado": estado},
            )
        await self.auditar(
            accion="cambio_estado_usuario",
            negocio_id=negocio_id,
            entidad="usuario",
            entidad_id=str(usuario_id),
            resultado=estado,
            detalle={"momento": momento.isoformat()},
        )

    async def listar(
        self, *, negocio_id: UUID, estado: str | None = None
    ) -> Sequence[dict[str, Any]]:
        filtro = "WHERE estado = :estado" if estado else ""
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            filas = (
                (
                    await conexion.execute(
                        text(
                            f"""
                            SELECT id AS usuario_id, email, nombre, rol, estado, ultimo_acceso,
                                   bloqueado_hasta, debe_aceptar_politica_version
                            FROM usuario {filtro}
                            ORDER BY nombre, email
                            """
                        ),
                        {"estado": estado} if estado else {},
                    )
                )
                .mappings()
                .all()
            )
        return tuple(dict(fila) for fila in filas)

    async def auditar(
        self,
        *,
        accion: str,
        negocio_id: UUID,
        usuario_id: UUID | None = None,
        entidad: str | None = None,
        entidad_id: str | None = None,
        resultado: str | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
        detalle: dict[str, Any] | None = None,
    ) -> None:
        import json

        async with contexto_negocio(self._motor, negocio_id) as conexion:
            await conexion.execute(
                text(
                    """
                    INSERT INTO auditoria (negocio_id, usuario_id, accion, entidad, entidad_id,
                                           resultado, ip, user_agent, detalle)
                    VALUES (:negocio_id, :usuario_id, :accion, :entidad, :entidad_id,
                            :resultado, :ip, :user_agent, CAST(:detalle AS jsonb))
                    """
                ),
                {
                    "negocio_id": negocio_id,
                    "usuario_id": usuario_id,
                    "accion": accion,
                    "entidad": entidad,
                    "entidad_id": entidad_id,
                    "resultado": resultado,
                    "ip": ip_valida(ip),
                    "user_agent": agente_valido(user_agent),
                    "detalle": json.dumps(detalle or {}, ensure_ascii=False),
                },
            )


class RepositorioSesionesBd:
    """Implementación sobre PostgreSQL."""

    def __init__(self, motor: AsyncEngine) -> None:
        self._motor = motor

    async def vigentes(
        self, *, negocio_id: UUID, usuario_id: UUID, momento: datetime
    ) -> Sequence[Sesion]:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            filas = (
                (
                    await conexion.execute(
                        text(
                            f"""
                            SELECT {CAMPOS_SESION}
                            FROM sesion
                            WHERE usuario_id = :usuario_id
                              AND estado = 'activa'
                              AND expira_en > :momento
                            ORDER BY ultimo_uso_en
                            """
                        ),
                        {"usuario_id": usuario_id, "momento": momento},
                    )
                )
                .mappings()
                .all()
            )
        return tuple(_a_sesion(fila) for fila in filas)

    async def crear(
        self,
        *,
        sesion_id: UUID,
        negocio_id: UUID,
        usuario_id: UUID,
        refresh_hash: str,
        expira_en: datetime,
        momento: datetime,
        dispositivo: str | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> UUID:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            await conexion.execute(
                text(
                    """
                    INSERT INTO sesion (id, negocio_id, usuario_id, refresh_hash, dispositivo,
                                        ip, user_agent, creada_en, ultimo_uso_en, expira_en, estado)
                    VALUES (:id, :negocio_id, :usuario_id, :refresh_hash, :dispositivo,
                            :ip, :user_agent, :momento, :momento, :expira_en, 'activa')
                    """
                ),
                {
                    "id": sesion_id,
                    "negocio_id": negocio_id,
                    "usuario_id": usuario_id,
                    "refresh_hash": refresh_hash,
                    "dispositivo": agente_valido(dispositivo),
                    "ip": ip_valida(ip),
                    "user_agent": agente_valido(user_agent),
                    "momento": momento,
                    "expira_en": expira_en,
                },
            )
        return sesion_id

    async def por_id(self, *, negocio_id: UUID, sesion_id: UUID) -> SesionGuardada | None:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            fila = (
                (
                    await conexion.execute(
                        text(
                            f"""
                            SELECT {CAMPOS_SESION}, refresh_hash,
                                   refresh_hash_anterior, refresh_anterior_desde
                            FROM sesion WHERE id = :sesion_id
                            """
                        ),
                        {"sesion_id": sesion_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if fila is None:
            return None
        return SesionGuardada(
            sesion=_a_sesion(fila),
            refresh_hash=str(fila["refresh_hash"]),
            refresh_hash_anterior=(
                str(fila["refresh_hash_anterior"])
                if fila["refresh_hash_anterior"] is not None
                else None
            ),
            refresh_anterior_desde=fila["refresh_anterior_desde"],
        )

    async def rotar(
        self,
        *,
        negocio_id: UUID,
        sesion_id: UUID,
        refresh_hash: str,
        ultimo_uso_en: datetime,
    ) -> None:
        """Rota la huella, **desplazando la anterior a su propio hueco**.

        El `SET` se lee contra la fila vieja, así que `refresh_hash_anterior = refresh_hash` guarda
        la huella que había antes de esta rotación. Es exactamente lo que hay que conservar para
        poder reconocer un reintento.

        `ultimo_uso_en` sirve además de marca de la rotación. No son dos cosas distintas: solo se
        rota al renovar, y renovar es usar la sesión. Guardar dos columnas con el mismo instante
        sería guardar dos verdades que podrían separarse.
        """
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            await conexion.execute(
                text(
                    """
                    UPDATE sesion
                    SET refresh_hash_anterior = refresh_hash,
                        refresh_anterior_desde = :ultimo_uso_en,
                        refresh_hash = :refresh_hash,
                        ultimo_uso_en = :ultimo_uso_en
                    WHERE id = :sesion_id
                    """
                ),
                {
                    "sesion_id": sesion_id,
                    "refresh_hash": refresh_hash,
                    "ultimo_uso_en": ultimo_uso_en,
                },
            )

    async def revocar(
        self,
        *,
        negocio_id: UUID,
        sesion_id: UUID,
        motivo: MotivoRevocacion,
        momento: datetime,
    ) -> None:
        await self.revocar_varias(
            negocio_id=negocio_id, sesion_ids=[sesion_id], motivo=motivo, momento=momento
        )

    async def revocar_varias(
        self,
        *,
        negocio_id: UUID,
        sesion_ids: Sequence[UUID],
        motivo: MotivoRevocacion,
        momento: datetime,
    ) -> int:
        if not sesion_ids:
            return 0
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            resultado = await conexion.execute(
                text(
                    """
                    UPDATE sesion
                    SET estado = 'revocada', revocada_motivo = :motivo, ultimo_uso_en = :momento
                    WHERE id = ANY(:sesion_ids) AND estado = 'activa'
                    """
                ),
                {
                    "sesion_ids": list(sesion_ids),
                    "motivo": str(motivo),
                    "momento": momento,
                },
            )
        return int(resultado.rowcount or 0)

    async def revocar_todas(
        self, *, negocio_id: UUID, usuario_id: UUID, motivo: MotivoRevocacion, momento: datetime
    ) -> int:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            resultado = await conexion.execute(
                text(
                    """
                    UPDATE sesion
                    SET estado = 'revocada', revocada_motivo = :motivo, ultimo_uso_en = :momento
                    WHERE usuario_id = :usuario_id AND estado = 'activa'
                    """
                ),
                {"usuario_id": usuario_id, "motivo": str(motivo), "momento": momento},
            )
        return int(resultado.rowcount or 0)

    async def revocar_todas_salvo(
        self,
        *,
        negocio_id: UUID,
        usuario_id: UUID,
        excepto: UUID | None,
        motivo: MotivoRevocacion,
        momento: datetime,
    ) -> int:
        """Revoca todas las sesiones activas menos una.

        Es lo que necesita quien cambia **su propia** contraseña: cerrar las demás sesiones y
        conservar la que está usando. Cerrarlas todas expulsaría a quien acaba de hacer lo
        correcto, y no cerrar ninguna dejaría vivo justo lo que el cambio viene a cortar.

        La sesión que se conserva solo puede ser una del propio usuario: la consulta filtra por
        `usuario_id`, así que no hay forma de mantener viva la sesión de otro. Si `excepto` llega
        `None`, el comportamiento es el de revocar todas.
        """
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            resultado = await conexion.execute(
                text(
                    """
                    UPDATE sesion
                    SET estado = 'revocada', revocada_motivo = :motivo, ultimo_uso_en = :momento
                    WHERE usuario_id = :usuario_id
                      AND estado = 'activa'
                      AND (CAST(:excepto AS uuid) IS NULL OR id <> CAST(:excepto AS uuid))
                    """
                ),
                {
                    "usuario_id": usuario_id,
                    "excepto": excepto,
                    "motivo": str(motivo),
                    "momento": momento,
                },
            )
        return int(resultado.rowcount or 0)

    async def activas_del_negocio(self, *, negocio_id: UUID, momento: datetime) -> Sequence[Sesion]:
        """Sesiones vigentes de todo el negocio.

        El filtro `expira_en > :momento` se repite aquí aunque el dominio también compruebe la
        vigencia: así la consulta no arrastra sesiones que ya no sirven, y lo que llega arriba ya es
        candidato de verdad. La comprobación del dominio sigue siendo la que decide, porque es la
        única que se ejecuta también sobre sesiones revocadas, que sí hay que leer para explicarlas.
        """
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            filas = (
                (
                    await conexion.execute(
                        text(
                            f"""
                            SELECT {CAMPOS_SESION}
                            FROM sesion
                            WHERE estado = 'activa' AND expira_en > :momento
                            ORDER BY ultimo_uso_en DESC
                            """
                        ),
                        {"momento": momento},
                    )
                )
                .mappings()
                .all()
            )
        return tuple(_a_sesion(fila) for fila in filas)

    async def revocadas_del_negocio(
        self, *, negocio_id: UUID, limite: int = 500
    ) -> Sequence[Sesion]:
        """Sesiones que ya no están activas, las de uso más reciente primero.

        `ultimo_uso_en` se reescribe al revocar, así que ordenar por él equivale a «la más recién
        cerrada primero». Eso es lo que hace que el motivo que se muestra sea el del último cierre y
        no el de una expulsión de hace tres semanas. El límite acota una tabla que crece sin fin.
        """
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            filas = (
                (
                    await conexion.execute(
                        text(
                            f"""
                            SELECT {CAMPOS_SESION}
                            FROM sesion
                            WHERE estado <> 'activa'
                            ORDER BY ultimo_uso_en DESC
                            LIMIT :limite
                            """
                        ),
                        {"limite": limite},
                    )
                )
                .mappings()
                .all()
            )
        return tuple(_a_sesion(fila) for fila in filas)
