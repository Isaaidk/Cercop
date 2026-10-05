"""Sesiones vivas: cierre por inactividad y la puerta que no pregunta a la base.

El problema que resuelve este módulo
------------------------------------
Comprobar que la sesión del token sigue viva obliga hoy a **una lectura por clave primaria en cada
petición**. Es correcto y es caro: con la base al otro lado de la red son dos viajes de ida y vuelta
por petición, y no por consulta lenta —los planes se miden en fracciones de milisegundo— sino por el
viaje. Con la base en el mismo servidor sigue siendo trabajo que se puede ahorrar.

Aquí la respuesta a «¿sigue viva esta sesión?» vive en el almacén, con un tiempo de vida. Y el
tiempo de vida **es** el cierre por inactividad: no hay ninguna tarea que recorra sesiones, porque
el almacén ya sabe hacerlo sola.

Tres respuestas, no dos
-----------------------
La operación devuelve tres estados y no dos, y la diferencia es la que sostiene todo lo demás:

- **`VIVA`**: consta y es de quien dice el token.
- **`CERRADA`**: no consta, con el almacén funcionando. Eso es una respuesta, y la sesión se acaba.
- **`SIN_RESPUESTA`**: el almacén no está configurado o no responde. **No es un cierre.** Se
  pregunta a la base de datos, como se hacía antes de que esto existiera.

Esa tercera respuesta es la que impide que el sistema se caiga solo. Sin ella, un almacén apagado
haría que ninguna sesión constara y echaría a todo el mundo; y al revés, dar por buena la ausencia
cuando no hay almacén convertiría un despliegue sin Redis en un sistema que no cierra sesiones.

Por qué el refresco no rearma el plazo
--------------------------------------
Es tentador que renovar el token cuente como actividad —al fin y al cabo alguien lo pidió— y sería
un error de consecuencias visibles: **una pestaña olvidada se renueva sola**. El panel late cada
treinta segundos, el token de acceso caduca a los quince minutos, el latido recibe un 401, el
cliente renueva en silencio y vuelve a latir. Ese bucle no depende de que haya nadie delante, así
que si renovar rearmara el plazo, la pestaña del sótano no se cerraría jamás.

Por eso solo las peticiones de verdad rearman el plazo, y `rotar` no toca esta clave.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from contratacion.aplicacion.puertos.cache import Cache
from contratacion.aplicacion.puertos.cuentas import RepositorioSesiones, SesionGuardada
from contratacion.dominio.sesiones import MotivoRevocacion, Sesion
from contratacion.dominio.sesiones_vivas import (
    clave_de_sesion,
    usuario_de_sesion,
    valor_de_sesion,
)

registro = logging.getLogger(__name__)


class VidaDeSesion(StrEnum):
    """Las tres respuestas posibles, descritas en el módulo."""

    VIVA = "viva"
    CERRADA = "cerrada"
    SIN_RESPUESTA = "sin_respuesta"


async def abrir(cache: Cache, *, sesion_id: UUID, usuario_id: UUID, inactividad_seg: int) -> None:
    """Anota una sesión recién abierta, con el plazo de inactividad por delante.

    **Un fallo aquí se propaga, y es deliberado.** La ausencia de esta clave significa «cerrada»,
    así que dejarla sin escribir por no poder hablar con el almacén no daría una sesión que no se
    cierra por inactividad: daría una sesión que responde 401 a la primera petición, justo después
    de que el usuario escribiera bien su contraseña. Es mejor que el inicio de sesión falle y se
    vea.
    """
    await cache.guardar(clave_de_sesion(sesion_id), valor_de_sesion(usuario_id), inactividad_seg)


async def seguir(
    cache: Cache,
    *,
    sesion_id: UUID,
    usuario_id: UUID,
    inactividad_seg: int,
    renovar: bool = True,
) -> VidaDeSesion:
    """¿Sigue viva la sesión, y de quién es?

    `renovar=False` comprueba sin rearmar el plazo. Lo usan las rutas que mantienen la conexión
    abierta —el latido y el flujo de eventos—, que no son actividad de nadie: si rearmaran, una
    pestaña olvidada viviría para siempre.
    """
    if not cache.habilitada:
        # Sin almacén no hay nada que preguntar, y la ausencia de la clave no significa nada.
        return VidaDeSesion.SIN_RESPUESTA

    clave = clave_de_sesion(sesion_id)
    try:
        if renovar:
            valor = await cache.obtener_renovando(clave, inactividad_seg)
        else:
            valor = await cache.obtener(clave)
    except Exception:  # noqa: BLE001 - un almacén roto degrada a la base, no tumba el servicio
        registro.warning(
            "El almacén de sesiones no responde; se comprueba la sesión en la base de datos",
            exc_info=False,
        )
        return VidaDeSesion.SIN_RESPUESTA

    if valor is None:
        return VidaDeSesion.CERRADA

    dueno = usuario_de_sesion(valor)
    if dueno is None or dueno != usuario_id:
        # La sesión existe pero no es de quien la presenta. Con un token firmado esto no debería
        # poder pasar, y precisamente por eso importa: significa que algo se ha torcido en otro
        # sitio, y lo que no se puede hacer es dejarlo pasar.
        registro.warning("La sesión %s no pertenece al usuario que la presenta", sesion_id)
        return VidaDeSesion.CERRADA

    return VidaDeSesion.VIVA


async def olvidar(cache: Cache, *, sesion_ids: Sequence[UUID]) -> None:
    """Borra las claves de las sesiones que dejan de estar vivas.

    **Un fallo aquí también se propaga.** Si la clave sobrevive a la revocación, la sesión sigue
    pasando la comprobación —el almacén la da por viva— y el usuario revocado continúa dentro hasta
    que venza el plazo. Es el peor final posible para un cierre de sesión: decir que se ha cerrado y
    no cerrarlo. La operación es idempotente, así que reintentarla es inofensivo, y por eso se
    prefiere el error visible a la apariencia de éxito.
    """
    if not cache.habilitada or not sesion_ids:
        return
    for sesion_id in sesion_ids:
        await cache.eliminar(clave_de_sesion(sesion_id))


class SesionesConVida:
    """Repositorio de sesiones que además mantiene al día el almacén de sesiones vivas.

    Es un envoltorio, y esa forma es la decisión importante de este archivo. La alternativa era
    llamar a `abrir` y a `olvidar` desde cada sitio que abre o cierra una sesión, y eran **cinco**:
    el inicio de sesión, el cierre de sesión, la expulsión por superar el máximo, la revocación
    administrativa y el cambio de contraseña. Bastaba con olvidar uno —o con añadir mañana una sexta
    forma de cerrar una sesión— para dejar viva una sesión revocada, sin error y sin rastro.

    Envolviendo el repositorio, la regla se cumple por construcción: todo lo que revoca pasa por
    aquí, porque no hay otra puerta.
    """

    def __init__(self, interno: RepositorioSesiones, cache: Cache, *, inactividad_seg: int) -> None:
        self._interno = interno
        self._cache = cache
        self._inactividad_seg = inactividad_seg

    # --- Lecturas: se delegan sin tocarlas --------------------------------- #
    #
    # Ninguna lectura modifica el almacén, y por eso no hace falta interceptarlas. En particular
    # `por_id` **no** rearma nada: lo usa el camino de respaldo —cuando el almacén no responde— y el
    # refresco de token, y ninguno de los dos es actividad de nadie.

    async def vigentes(
        self, *, negocio_id: UUID, usuario_id: UUID, momento: datetime
    ) -> Sequence[Sesion]:
        return await self._interno.vigentes(
            negocio_id=negocio_id, usuario_id=usuario_id, momento=momento
        )

    async def por_id(self, *, negocio_id: UUID, sesion_id: UUID) -> SesionGuardada | None:
        return await self._interno.por_id(negocio_id=negocio_id, sesion_id=sesion_id)

    async def activas_del_negocio(self, *, negocio_id: UUID, momento: datetime) -> Sequence[Sesion]:
        return await self._interno.activas_del_negocio(negocio_id=negocio_id, momento=momento)

    async def revocadas_del_negocio(
        self, *, negocio_id: UUID, limite: int = 500
    ) -> Sequence[Sesion]:
        return await self._interno.revocadas_del_negocio(negocio_id=negocio_id, limite=limite)

    # --- Escrituras: la clave se abre después y se cierra después ---------- #

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
        """Registra la sesión y, **después**, la anota como viva.

        El orden importa y no es el que parece natural. Si la clave se escribiera primero y fallara
        el registro, quedaría una sesión que el almacén da por viva y que **no existe en la base**:
        un token válido para una sesión que nadie puede revocar, porque no hay fila que marcar. Al
        revés, un registro sin clave es una sesión inofensiva que nunca llegará a usarse.
        """
        registrada = await self._interno.crear(
            sesion_id=sesion_id,
            negocio_id=negocio_id,
            usuario_id=usuario_id,
            refresh_hash=refresh_hash,
            expira_en=expira_en,
            momento=momento,
            dispositivo=dispositivo,
            ip=ip,
            user_agent=user_agent,
        )
        await abrir(
            self._cache,
            sesion_id=sesion_id,
            usuario_id=usuario_id,
            inactividad_seg=self._inactividad_seg,
        )
        return registrada

    async def rotar(
        self,
        *,
        negocio_id: UUID,
        sesion_id: UUID,
        refresh_hash: str,
        ultimo_uso_en: datetime,
    ) -> None:
        """Guarda la huella del token nuevo. **No rearma el plazo de inactividad.**

        Está explicado arriba y se repite aquí porque es el sitio donde a alguien le parecerá que
        falta: una pestaña olvidada se renueva sola cada cuarto de hora, así que rearmar aquí haría
        que nunca se cerrara.
        """
        await self._interno.rotar(
            negocio_id=negocio_id,
            sesion_id=sesion_id,
            refresh_hash=refresh_hash,
            ultimo_uso_en=ultimo_uso_en,
        )

    async def revocar(
        self,
        *,
        negocio_id: UUID,
        sesion_id: UUID,
        motivo: MotivoRevocacion,
        momento: datetime,
    ) -> None:
        await self._interno.revocar(
            negocio_id=negocio_id, sesion_id=sesion_id, motivo=motivo, momento=momento
        )
        await olvidar(self._cache, sesion_ids=[sesion_id])

    async def revocar_varias(
        self,
        *,
        negocio_id: UUID,
        sesion_ids: Sequence[UUID],
        motivo: MotivoRevocacion,
        momento: datetime,
    ) -> int:
        revocadas = await self._interno.revocar_varias(
            negocio_id=negocio_id, sesion_ids=sesion_ids, motivo=motivo, momento=momento
        )
        await olvidar(self._cache, sesion_ids=sesion_ids)
        return revocadas

    async def revocar_todas(
        self, *, negocio_id: UUID, usuario_id: UUID, motivo: MotivoRevocacion, momento: datetime
    ) -> int:
        """Cierra todas las sesiones de una cuenta."""
        return await self._revocar_las_del_usuario(
            negocio_id=negocio_id,
            usuario_id=usuario_id,
            excepto=None,
            motivo=motivo,
            momento=momento,
        )

    async def revocar_todas_salvo(
        self,
        *,
        negocio_id: UUID,
        usuario_id: UUID,
        excepto: UUID | None,
        motivo: MotivoRevocacion,
        momento: datetime,
    ) -> int:
        """Cierra todas las sesiones de una cuenta menos una."""
        return await self._revocar_las_del_usuario(
            negocio_id=negocio_id,
            usuario_id=usuario_id,
            excepto=excepto,
            motivo=motivo,
            momento=momento,
        )

    async def _revocar_las_del_usuario(
        self,
        *,
        negocio_id: UUID,
        usuario_id: UUID,
        excepto: UUID | None,
        motivo: MotivoRevocacion,
        momento: datetime,
    ) -> int:
        """El trabajo compartido por las dos formas de cerrarlo todo.

        Aquí hay que **leer antes de revocar**, y es la única operación que necesita un paso más:
        estas dos reciben a quién cerrar, no qué sesiones, así que las claves que hay que borrar
        solo se conocen mirando la base mientras el estado todavía dice «activa».

        Se revoca con `revocar_varias` en lugar de con el método específico del repositorio porque
        la lista de identificadores ya está calculada: pedirlo de otra forma sería una segunda
        consulta para hacer lo mismo, y las dos listas podrían no coincidir.
        """
        vigentes = await self._interno.vigentes(
            negocio_id=negocio_id, usuario_id=usuario_id, momento=datetime.now(UTC)
        )
        ids = [sesion.id for sesion in vigentes if sesion.id != excepto]
        revocadas = await self._interno.revocar_varias(
            negocio_id=negocio_id, sesion_ids=ids, motivo=motivo, momento=momento
        )
        await olvidar(self._cache, sesion_ids=ids)
        return revocadas
