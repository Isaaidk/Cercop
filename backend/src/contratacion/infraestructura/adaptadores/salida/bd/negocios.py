"""Adaptador de salida: empresas.

El método que importa es `crear`, y su gracia está en **cuándo** se fija el contexto de negocio.

Las políticas de RLS de `negocio`, `usuario` y `acceso_vista` comparan `negocio_id` con
`current_setting('app.negocio_id', true)::uuid`. Una inserción sin contexto se rechaza, y al
registrar una empresa el contexto no puede existir todavía: la empresa es justo lo que se está
creando.

Las salidas malas son dos y conviene descartarlas por escrito:

- **Quitar RLS durante el alta.** Sería la única operación que escribe sin aislamiento, y
  el día que alguien reutilizara ese camino para otra cosa el aislamiento ya no estaría.
- **Una función `SECURITY DEFINER`.** Es lo que usa `resolver_cuenta`, y allí está justificado
  porque hay que leer una tabla existente sin contexto. Aquí no hace falta: el identificador de la
  empresa **lo genera esta misma operación**, así que se puede fijar el contexto a ese identificador
  antes de insertar nada. La comprobación de la política pasa por sí sola —`id = contexto`— y no hay
  nada que debilitar.

Es decir: no se esquiva el aislamiento, se entra por la puerta, con el contexto del negocio que se
acaba de crear.
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

from contratacion.aplicacion.puertos.negocios import (
    AltaEmpresa,
    EmpresaDePlataforma,
    NegocioGuardado,
)
from contratacion.dominio.errores import DatoInvalido
from contratacion.dominio.negocios import DatosEmpresa
from contratacion.infraestructura.adaptadores.salida.bd.conflictos import (
    MENSAJE_CORREO_EN_USO,
    es_correo_repetido,
)
from contratacion.infraestructura.adaptadores.salida.bd.contexto import (
    contexto_negocio,
    sin_contexto,
)

registro = logging.getLogger(__name__)

CAMPOS_NEGOCIO = """
    id, nombre, ruc, estado, plan, limite_usuarios,
    email_contacto, telefono, direccion, ciudad, creado_en
"""


def _a_negocio(fila: Mapping[Any, Any]) -> NegocioGuardado:
    return NegocioGuardado(
        negocio_id=fila["id"],
        nombre=str(fila["nombre"]),
        ruc=fila["ruc"],
        estado=str(fila["estado"]),
        plan=str(fila["plan"]),
        limite_usuarios=int(fila["limite_usuarios"]),
        email_contacto=fila["email_contacto"],
        telefono=fila["telefono"],
        direccion=fila["direccion"],
        ciudad=fila["ciudad"],
        creado_en=fila["creado_en"],
    )


def _a_empresa_de_plataforma(fila: Mapping[Any, Any]) -> EmpresaDePlataforma:
    """Traduce una fila de `listar_negocios()`.

    Los nombres de las columnas van prefijados en la función SQL a propósito: los parámetros de
    salida de `RETURNS TABLE` son variables dentro del cuerpo, y llamarse igual que las columnas las
    haría ambiguas.
    """
    return EmpresaDePlataforma(
        negocio_id=fila["id_negocio"],
        nombre=str(fila["nombre_empresa"]),
        ruc=fila["ruc_empresa"],
        estado=str(fila["estado_empresa"]),
        plan=str(fila["plan_empresa"]),
        limite_usuarios=int(fila["limite_cuentas"]),
        email_contacto=fila["correo_contacto"],
        telefono=fila["telefono_contacto"],
        direccion=fila["direccion_empresa"],
        ciudad=fila["ciudad_empresa"],
        creado_en=fila["creada_en"],
        cuentas=int(fila["cuentas"]),
        cuentas_activas=int(fila["cuentas_activas"]),
    )


class RepositorioNegociosBd:
    """Implementación sobre PostgreSQL."""

    def __init__(self, motor: AsyncEngine) -> None:
        self._motor = motor

    async def listar(self) -> Sequence[EmpresaDePlataforma]:
        """Todas las empresas, leídas de una función `SECURITY DEFINER`.

        Hace falta porque `negocio` tiene RLS forzado con la política `id = contexto`: sin un
        negocio en el contexto, una consulta normal no devuelve ninguna fila. La función devuelve
        una lista de columnas cerrada —identidad, estado y **cuántas** cuentas tiene cada empresa,
        nunca cuáles— así que lo único que se puede obtener de más es el censo de empresas.
        """
        async with sin_contexto(self._motor) as conexion:
            filas = (
                (await conexion.execute(text("SELECT * FROM listar_negocios()"))).mappings().all()
            )
        return tuple(_a_empresa_de_plataforma(fila) for fila in filas)

    async def cambiar_estado(self, *, negocio_id: UUID, estado: str, momento: datetime) -> None:
        """Suspende o reactiva una empresa.

        Esta sí atraviesa el aislamiento por la puerta: se fija el contexto al de la empresa que se
        modifica, y la política `id = contexto` deja pasar el `UPDATE`. No hace falta ninguna
        función con privilegios elevados, que es justo lo que evita tener dos caminos de escritura
        sin aislamiento.
        """
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            await conexion.execute(
                text("UPDATE negocio SET estado = :estado WHERE id = :negocio_id"),
                {"estado": estado, "negocio_id": negocio_id},
            )

    async def crear(self, alta: AltaEmpresa) -> UUID:
        """Registra empresa, administrador y vistas de prueba en una sola transacción.

        El orden importa y no es casual: primero la empresa, porque las otras dos tablas la
        referencian. Si cualquier inserción falla, la transacción entera se deshace y no queda una
        empresa sin administrador, que es el estado del que no se puede salir desde la interfaz.
        """
        datos = alta.datos
        vence = alta.plazo_prueba.calcular(alta.momento)

        # El contexto se fija al identificador de la empresa **que se va a crear**. Es lo que hace
        # que las tres inserciones pasen las políticas sin abrir ningún atajo.
        async with contexto_negocio(self._motor, alta.negocio_id) as conexion:
            await conexion.execute(
                text(
                    """
                    INSERT INTO negocio (id, nombre, ruc, email_contacto, telefono, direccion,
                                         ciudad)
                    VALUES (:id, :nombre, :ruc, :email_contacto, :telefono, :direccion, :ciudad)
                    """
                ),
                {
                    "id": alta.negocio_id,
                    "nombre": datos.nombre,
                    "ruc": datos.ruc,
                    "email_contacto": datos.email_contacto,
                    "telefono": datos.telefono,
                    "direccion": datos.direccion,
                    "ciudad": datos.ciudad,
                },
            )

            # El correo es único en toda la plataforma y lo garantiza un índice, no una
            # comprobación previa: entre la comprobación y la inserción cabe otro registro con el
            # mismo correo. Se intenta insertar y se traduce el fallo. Al traducirlo, la excepción
            # sale del bloque y la transacción se deshace entera, así que no queda una empresa sin
            # administrador.
            try:
                await conexion.execute(
                    text(
                        """
                        INSERT INTO usuario (id, negocio_id, email, hash_password,
                                             nombre, rol, estado)
                        VALUES (:id, :negocio_id, :email, :huella, :nombre, :rol, 'activo')
                        """
                    ),
                    {
                        "id": alta.admin_id,
                        "negocio_id": alta.negocio_id,
                        "email": alta.admin_email,
                        "huella": alta.huella,
                        "nombre": alta.admin_nombre,
                        "rol": str(alta.admin_rol),
                    },
                )
            except IntegrityError as error:
                if es_correo_repetido(error):
                    raise DatoInvalido(MENSAJE_CORREO_EN_USO) from error
                raise

            for vista in alta.vistas_prueba:
                await conexion.execute(
                    text(
                        """
                        INSERT INTO acceso_vista (negocio_id, usuario_id, vista, plazo_codigo,
                                                  otorgado_en, vence_en, otorgado_por)
                        VALUES (:negocio_id, :usuario_id, :vista, :plazo,
                                :momento, :vence, :usuario_id)
                        """
                    ),
                    {
                        "negocio_id": alta.negocio_id,
                        "usuario_id": alta.admin_id,
                        "vista": str(vista),
                        "plazo": str(alta.plazo_prueba),
                        "momento": alta.momento,
                        "vence": vence,
                    },
                )

        registro.info(
            "Empresa registrada: negocio=%s admin=%s vistas=%s",
            alta.negocio_id,
            alta.admin_id,
            len(alta.vistas_prueba),
        )
        return alta.negocio_id

    async def obtener(self, *, negocio_id: UUID) -> NegocioGuardado | None:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            fila = (
                (
                    await conexion.execute(
                        text(f"SELECT {CAMPOS_NEGOCIO} FROM negocio WHERE id = :negocio_id"),
                        {"negocio_id": negocio_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return _a_negocio(fila) if fila else None

    async def actualizar_datos(
        self, *, negocio_id: UUID, datos: DatosEmpresa, momento: datetime
    ) -> None:
        """Cambia los datos de contacto.

        El nombre y el RUC se actualizan también: son datos que la propia empresa corrige —una razón
        social mal escrita al registrarse es lo más habitual— y obligarla a escribir a soporte para
        eso no tiene sentido. Lo que **no** se toca desde aquí es el estado ni el plan, que son
        decisiones de la plataforma y no del cliente.
        """
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            await conexion.execute(
                text(
                    """
                    UPDATE negocio
                    SET nombre = :nombre, ruc = :ruc, email_contacto = :email_contacto,
                        telefono = :telefono, direccion = :direccion, ciudad = :ciudad
                    WHERE id = :negocio_id
                    """
                ),
                {
                    "negocio_id": negocio_id,
                    "nombre": datos.nombre,
                    "ruc": datos.ruc,
                    "email_contacto": datos.email_contacto,
                    "telefono": datos.telefono,
                    "direccion": datos.direccion,
                    "ciudad": datos.ciudad,
                },
            )

    async def resumen_uso(self, *, negocio_id: UUID) -> dict[str, Any]:
        """Cuentas activas, administradores activos y límite del plan, en una sola consulta.

        Se cuentan las dos cosas de golpe porque el panel necesita las tres a la vez: cuántas plazas
        quedan y si todavía hay alguien que pueda gestionarlas. Dos consultas darían dos fotos de
        instantes distintos y un panel que se contradice consigo mismo.
        """
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            fila = (
                (
                    await conexion.execute(
                        text(
                            """
                            SELECT n.limite_usuarios,
                                   count(u.id) FILTER (
                                       WHERE u.estado IN ('activo', 'pendiente')
                                   ) AS usuarios_activos,
                                   count(u.id) FILTER (
                                       WHERE u.estado IN ('activo', 'pendiente')
                                         AND u.rol = 'admin_negocio'
                                   ) AS administradores_activos
                            FROM negocio n
                            LEFT JOIN usuario u ON u.negocio_id = n.id
                            WHERE n.id = :negocio_id
                            GROUP BY n.limite_usuarios
                            """
                        ),
                        {"negocio_id": negocio_id},
                    )
                )
                .mappings()
                .one_or_none()
            )

        if fila is None:
            return {
                "limite_usuarios": 0,
                "usuarios_activos": 0,
                "administradores_activos": 0,
                "plazas_libres": 0,
            }

        limite = int(fila["limite_usuarios"])
        activos = int(fila["usuarios_activos"])
        return {
            "limite_usuarios": limite,
            "usuarios_activos": activos,
            "administradores_activos": int(fila["administradores_activos"]),
            # Nunca negativo: si el plan se reduce por debajo de lo ya contratado, el panel tiene
            # que decir «no caben más» y no mostrar un número negativo, que no significa nada.
            "plazas_libres": max(0, limite - activos),
        }
