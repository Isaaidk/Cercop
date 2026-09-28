"""Adaptador de salida: alta, baja y modificación de las cuentas de un negocio.

Dos detalles que resuelven problemas reales.

**El correo repetido se detecta por el nombre del índice, no por el texto del error.** La
unicidad del correo la garantiza un índice único global (`ux_usuario_email_global`, migración
0007), y lo hace inmejorable: ninguna comprobación previa puede cubrir dos altas simultáneas con
el mismo correo, porque entre la consulta y la inserción cabe la otra. Así que no se comprueba
antes: se intenta insertar y se traduce el fallo. Para traducirlo hay que reconocerlo, y
reconocerlo por el nombre del índice es estable; reconocerlo por el texto del mensaje de
PostgreSQL, que cambia con la versión y con el idioma, no lo es.

**Dar de baja una cuenta y cerrar sus sesiones son la misma transacción.** Si se hicieran por
separado, un fallo entre las dos dejaría a alguien bloqueado pero con la sesión abierta, o al
revés.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from contratacion.aplicacion.puertos.usuarios import FichaUsuario, NuevaCuenta
from contratacion.dominio.errores import DatoInvalido
from contratacion.dominio.roles import Rol
from contratacion.infraestructura.adaptadores.salida.bd.conflictos import (
    MENSAJE_CORREO_EN_USO,
    es_correo_repetido,
)
from contratacion.infraestructura.adaptadores.salida.bd.contexto import contexto_negocio

registro = logging.getLogger(__name__)

CAMPOS_FICHA = """
    id, negocio_id, email, nombre, rol, estado, ultimo_acceso, creado_en
"""


def _a_ficha(fila: Mapping[Any, Any]) -> FichaUsuario:
    return FichaUsuario(
        usuario_id=fila["id"],
        negocio_id=fila["negocio_id"],
        email=str(fila["email"]),
        nombre=str(fila["nombre"]),
        rol=Rol(str(fila["rol"])),
        estado=str(fila["estado"]),
        ultimo_acceso=fila["ultimo_acceso"],
        creado_en=fila["creado_en"],
    )


class RepositorioUsuariosBd:
    """Implementación sobre PostgreSQL."""

    def __init__(self, motor: AsyncEngine) -> None:
        self._motor = motor

    async def crear(self, cuenta: NuevaCuenta) -> UUID:
        try:
            async with contexto_negocio(self._motor, cuenta.negocio_id) as conexion:
                await conexion.execute(
                    text(
                        """
                        INSERT INTO usuario (id, negocio_id, email, hash_password, nombre, rol,
                                             estado, creado_en)
                        VALUES (:id, :negocio_id, :email, :huella, :nombre, :rol,
                                'activo', :momento)
                        """
                    ),
                    {
                        "id": cuenta.usuario_id,
                        "negocio_id": cuenta.negocio_id,
                        "email": cuenta.email,
                        "huella": cuenta.huella,
                        "nombre": cuenta.nombre or cuenta.email,
                        "rol": str(cuenta.rol),
                        "momento": cuenta.momento,
                    },
                )
        except IntegrityError as error:
            if es_correo_repetido(error):
                raise DatoInvalido(MENSAJE_CORREO_EN_USO) from error
            raise
        return cuenta.usuario_id

    async def obtener(self, *, negocio_id: UUID, usuario_id: UUID) -> FichaUsuario | None:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            fila = (
                (
                    await conexion.execute(
                        text(f"SELECT {CAMPOS_FICHA} FROM usuario WHERE id = :usuario_id"),
                        {"usuario_id": usuario_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return _a_ficha(fila) if fila else None

    async def listar(
        self, *, negocio_id: UUID, incluir_inactivos: bool = False
    ) -> Sequence[FichaUsuario]:
        # Las bajas se excluyen por defecto y el orden es por nombre: el listado se lee para
        # encontrar a una persona, y «por fecha de alta» obliga a recorrerlo entero cada vez.
        filtro = "" if incluir_inactivos else "AND estado <> 'inactivo'"
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            filas = (
                (
                    await conexion.execute(
                        text(
                            f"""
                            SELECT {CAMPOS_FICHA}
                            FROM usuario
                            WHERE negocio_id = :negocio_id {filtro}
                            ORDER BY lower(nombre), lower(email)
                            """
                        ),
                        {"negocio_id": negocio_id},
                    )
                )
                .mappings()
                .all()
            )
        return tuple(_a_ficha(fila) for fila in filas)

    async def contar_activos(self, *, negocio_id: UUID) -> int:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            return int(
                (
                    await conexion.execute(
                        text(
                            """
                            SELECT count(*)
                            FROM usuario
                            WHERE negocio_id = :negocio_id AND estado IN ('activo', 'pendiente')
                            """
                        ),
                        {"negocio_id": negocio_id},
                    )
                ).scalar_one()
            )

    async def contar_administradores(self, *, negocio_id: UUID) -> int:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            return int(
                (
                    await conexion.execute(
                        text(
                            """
                            SELECT count(*)
                            FROM usuario
                            WHERE negocio_id = :negocio_id
                              AND estado IN ('activo', 'pendiente')
                              AND rol IN ('admin_negocio', 'super_admin')
                            """
                        ),
                        {"negocio_id": negocio_id},
                    )
                ).scalar_one()
            )

    async def actualizar_huella(
        self, *, negocio_id: UUID, usuario_id: UUID, huella: str, momento: datetime
    ) -> None:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            await conexion.execute(
                text(
                    """
                    UPDATE usuario
                    SET hash_password = :huella, intentos_fallidos = 0, bloqueado_hasta = NULL
                    WHERE id = :usuario_id
                    """
                ),
                {"usuario_id": usuario_id, "huella": huella},
            )

    async def actualizar_identidad(
        self,
        *,
        negocio_id: UUID,
        usuario_id: UUID,
        nombre: str,
        rol: Rol,
        huella: str | None,
    ) -> None:
        # La huella es opcional para poder reactivar una cuenta cambiando el nombre y el rol sin
        # obligar a inventar una contraseña nueva que nadie pidió.
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            await conexion.execute(
                text(
                    """
                    UPDATE usuario
                    SET nombre = :nombre, rol = :rol,
                        hash_password = COALESCE(:huella, hash_password),
                        intentos_fallidos = 0, bloqueado_hasta = NULL
                    WHERE id = :usuario_id
                    """
                ),
                {
                    "usuario_id": usuario_id,
                    "nombre": nombre,
                    "rol": str(rol),
                    "huella": huella,
                },
            )

    async def cambiar_estado(
        self, *, negocio_id: UUID, usuario_id: UUID, estado: str, momento: datetime
    ) -> None:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            await conexion.execute(
                text("UPDATE usuario SET estado = :estado WHERE id = :usuario_id"),
                {"usuario_id": usuario_id, "estado": estado},
            )

    async def eliminar(self, *, negocio_id: UUID, usuario_id: UUID) -> None:
        """Borra la fila. Sus consentimientos y sus sesiones se van con ella, por la
        cascada al borrar.

        La auditoría **no**: esa tabla no tiene clave ajena hacia `usuario`, así que el rastro
        de lo que hizo sobrevive al borrado. Es la diferencia que hace que el borrado real sea
        aceptable como acción administrativa y no como una pérdida de información.
        """
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            await conexion.execute(
                text("DELETE FROM usuario WHERE id = :usuario_id AND negocio_id = :negocio_id"),
                {"usuario_id": usuario_id, "negocio_id": negocio_id},
            )
