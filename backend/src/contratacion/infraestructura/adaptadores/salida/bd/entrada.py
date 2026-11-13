"""La puerta de entrada de cada petición en **una** consulta.

Toda petición autenticada pasaba por tres lecturas, cada una con su conexión del pool y su
transacción (`BEGIN`, `set_config`, consulta, `COMMIT`: cuatro viajes a la base):

1. la empresa, para saber si está suspendida (`obtener_actor`);
2. la cuenta, para saber si su contraseña es temporal (`consentimiento_del_actor`);
3. otra vez la cuenta, para el marcador de políticas pendientes (`exigir_aceptado`).

Medido en local: 3 conexiones y 12 viajes por petición antes de empezar a trabajar, también en el
latido de presencia y en la comprobación de novedades que cada panel hace solo. Aquí se leen las
tres cosas juntas, en el mismo contexto RLS de la empresa del token, y el resultado se guarda en la
petición para que la segunda puerta no vuelva a preguntar.

No cambia **qué** se comprueba ni **cuándo**: las tres comprobaciones siguen haciéndose en cada
petición contra la base, sin caché entre peticiones. Una suspensión, una contraseña temporal o una
política nueva se notan en la petición siguiente, igual que antes.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from contratacion.aplicacion.puertos.negocios import NegocioGuardado
from contratacion.infraestructura.adaptadores.salida.bd.contexto import contexto_negocio
from contratacion.infraestructura.adaptadores.salida.bd.negocios import _a_negocio

# El `LEFT JOIN` deja la empresa aunque la cuenta no esté a la vista: así se distingue «empresa
# suspendida» (que manda) de «cuenta que no existe en esta empresa». Las columnas de la empresa van
# con prefijo porque `id` y `estado` existen en las dos tablas.
_CONSULTA = text(
    """
    SELECT n.id, n.nombre, n.ruc, n.estado, n.plan, n.limite_usuarios,
           n.email_contacto, n.telefono, n.direccion, n.ciudad, n.creado_en,
           u.id AS usuario_id,
           u.debe_cambiar_contrasena,
           u.debe_aceptar_politica_version
    FROM negocio n
    LEFT JOIN usuario u ON u.negocio_id = n.id AND u.id = :usuario_id
    WHERE n.id = :negocio_id
    """
)


@dataclass(frozen=True, slots=True)
class EstadoDeEntrada:
    """Lo que las dos puertas necesitan saber de la empresa y de la cuenta."""

    negocio_id: UUID
    usuario_id: UUID
    negocio: NegocioGuardado | None
    cuenta_visible: bool
    debe_cambiar_contrasena: bool
    politica_pendiente: int | None


class PuertaDeEntradaBd:
    """Lectura única de la puerta de entrada."""

    def __init__(self, motor: AsyncEngine) -> None:
        self._motor = motor

    async def leer(self, *, negocio_id: UUID, usuario_id: UUID) -> EstadoDeEntrada:
        async with contexto_negocio(self._motor, negocio_id) as conexion:
            fila = (
                (
                    await conexion.execute(
                        _CONSULTA, {"negocio_id": negocio_id, "usuario_id": usuario_id}
                    )
                )
                .mappings()
                .one_or_none()
            )
        if fila is None:
            return EstadoDeEntrada(
                negocio_id=negocio_id,
                usuario_id=usuario_id,
                negocio=None,
                cuenta_visible=False,
                debe_cambiar_contrasena=False,
                politica_pendiente=None,
            )
        pendiente = fila["debe_aceptar_politica_version"]
        return EstadoDeEntrada(
            negocio_id=negocio_id,
            usuario_id=usuario_id,
            negocio=_a_negocio(fila),
            cuenta_visible=fila["usuario_id"] is not None,
            debe_cambiar_contrasena=bool(fila["debe_cambiar_contrasena"]),
            politica_pendiente=None if pendiente is None else int(pendiente),
        )
