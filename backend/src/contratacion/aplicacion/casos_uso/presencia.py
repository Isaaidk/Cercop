"""Casos de uso de la presencia.

Tres operaciones: **latir**, **listar** y **cerrar por cierre de ventana**.

La decisión importante de este módulo: el latido **no** toca `ultimo_uso` de la sesión
------------------------------------------------------------------------------
Es tentador hacerlo —el usuario tiene la aplicación abierta, luego la está usando— y sería un error
con consecuencias reales.

La expulsión de la tercera sesión ordena por `ultimo_uso` para decidir a quién se echa. Si un latido
actualizara ese campo, una pestaña olvidada en un equipo que nadie mira latiría cada treinta
segundos para siempre y sería **la última en expulsarse**. La sesión que la persona tiene delante
—la que mira y usa de verdad— se cerraría, y el usuario vería apagarse la pestaña que estaba usando
mientras la del sótano sobrevive.

Por eso `ultimo_uso` significa «aquí pasó algo que la persona pidió» y el latido vive en su propio
sitio. Son dos cosas distintas, y mezclarlas rompe la regla que ya está escrita en
`dominio/sesiones.py`.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.puertos.accesos import RepositorioAccesos
from contratacion.aplicacion.puertos.cache import Cache
from contratacion.aplicacion.puertos.cuentas import RepositorioSesiones
from contratacion.aplicacion.puertos.presencia import BusEventos, RegistroPresencia
from contratacion.aplicacion.sesiones_vivas import VidaDeSesion, seguir
from contratacion.dominio.acceso import puede_gestionar
from contratacion.dominio.errores import SinPermiso
from contratacion.dominio.presencia import (
    AMBITO_TODOS,
    TTL_CUADRO_SEG,
    EstadoPresencia,
    EventoPresencia,
    Latido,
    Motivo,
    Presencia,
    clave_cuadro,
    evaluar_presencia,
    evento_conectado,
    evento_desconectado,
    presencia_de_sesion_viva,
)
from contratacion.dominio.sesiones import EstadoSesion, MotivoRevocacion, Sesion

# El nombre del ayudante de registro lleva «avisos» porque en este módulo `registro` ya es el
# registro de presencia, y son dos cosas distintas que no conviene confundir al leer.
registro_de_avisos = logging.getLogger(__name__)

# El mismo texto para «no existe», «ya se cerró» y «es de otra cuenta». Distinguirlos permitiría
# averiguar qué sesiones existen probando identificadores, que es información de otro usuario.
NO_ENCONTRADA = "Esa sesión no existe, ya se cerró o no pertenece a tu cuenta."

# Topes del listado. Es una lectura de apoyo para el panel; si un negocio los supera, lo que hay que
# revisar es la paginación del panel, no ampliar el número a escondidas.
MAXIMO_USUARIOS = 500
MAXIMO_SESIONES_REVOCADAS = 500


@dataclass(frozen=True, slots=True)
class CuadroPresencia:
    """El listado de presencia de un negocio, con su alcance declarado."""

    momento: datetime
    presencias: tuple[Presencia, ...]
    compartida: bool

    @property
    def conectados(self) -> int:
        return sum(1 for presencia in self.presencias if presencia.verde)

    @property
    def total(self) -> int:
        return len(self.presencias)

    def como_diccionario(self) -> dict[str, object]:
        return {
            "momento": self.momento.isoformat(),
            "conectados": self.conectados,
            "total": len(self.presencias),
            # Se publica tal cual para que la interfaz pueda advertir de la limitación en lugar de
            # mostrar un dato que con varias réplicas sería falso sin parecerlo.
            "alcance": "compartido" if self.compartida else "proceso",
            "usuarios": [presencia.como_diccionario() for presencia in self.presencias],
        }


async def latir(
    actor: Actor,
    *,
    sesion_id: UUID,
    registro: RegistroPresencia,
    sesiones: RepositorioSesiones,
    cache: Cache,
    bus: BusEventos,
    inactividad_seg: int,
    momento: datetime | None = None,
    ttl_seg: int,
) -> EventoPresencia:
    """Anota que la sesión sigue viva y lo anuncia al negocio.

    **La sesión se valida antes de dar nada por vivo.** Sin esta comprobación, una sesión revocada
    seguiría latiendo y el panel la mostraría en verde hasta que el usuario cerrara la pestaña:
    exactamente el caso que la revocación existe para cortar.

    Y esa comprobación **no es la misma que la de la puerta**, aunque lo parezca. La puerta valida
    la sesión **del token**; aquí llega un `sesion_id` en el cuerpo de la petición, que lo elige
    quien llama. Sin comprobarlo, cualquiera con un token válido podría mantener en verde la sesión
    de otra persona —o de otra empresa— mandando latidos ajenos.

    Se comprueba contra el almacén y no contra la base, que es lo que hace que el camino más
    transitado del sistema —un latido cada treinta segundos por persona conectada— no cueste ninguna
    consulta. Si el almacén no responde, se pregunta a la base como antes: el sistema entero sigue
    funcionando sin Redis, solo más lento.
    """
    instante = momento or datetime.now(UTC)

    if not await _sesion_viva(
        sesiones,
        cache=cache,
        negocio_id=actor.negocio_id,
        sesion_id=sesion_id,
        usuario_id=actor.usuario_id,
        inactividad_seg=inactividad_seg,
    ):
        raise SinPermiso(NO_ENCONTRADA)

    await registro.marcar(
        usuario_id=actor.usuario_id,
        sesion_id=sesion_id,
        negocio_id=actor.negocio_id,
        momento=instante,
        ttl_seg=ttl_seg,
    )

    presencia = presencia_de_sesion_viva(
        usuario_id=actor.usuario_id, sesion_id=sesion_id, momento=instante
    )
    evento = evento_conectado(actor.negocio_id, presencia, instante)
    # Se anuncia en cada latido, aunque el estado no haya cambiado. Es redundante a propósito: el
    # aviso de conexión es lo que pone al día a un panel recién abierto, y repetirlo hace que un
    # aviso perdido se recupere en el latido siguiente en lugar de esperar a la relectura periódica.
    # Un aviso de más cuesta un mensaje; uno de menos deja el panel mintiendo.
    await bus.publicar(negocio_id=actor.negocio_id, evento=evento)
    return evento


async def _sesion_viva(
    sesiones: RepositorioSesiones,
    *,
    cache: Cache,
    negocio_id: UUID,
    sesion_id: UUID,
    usuario_id: UUID,
    inactividad_seg: int,
) -> bool:
    """¿Esta sesión sigue viva y es de esta persona?

    Responde primero el almacén. Solo si **no responde** —no está configurado o está caído— se
    pregunta a la base, porque entonces la ausencia de la clave no significa nada.

    Ojo con la diferencia: que el almacén diga «no consta» **sí** es un cierre y la sesión no late.
    Confundir las dos cosas dejaría latiendo para siempre a una sesión que se cerró por inactividad.
    """
    vida = await seguir(
        cache,
        sesion_id=sesion_id,
        usuario_id=usuario_id,
        inactividad_seg=inactividad_seg,
        # Sin rearmar el plazo: un latido **no** es actividad de nadie. Si lo rearmara, la pestaña
        # de un equipo que nadie mira —que late sola cada treinta segundos— no se cerraría nunca.
        renovar=False,
    )
    if vida is VidaDeSesion.VIVA:
        return True
    if vida is VidaDeSesion.CERRADA:
        return False

    guardada = await sesiones.por_id(negocio_id=negocio_id, sesion_id=sesion_id)
    return guardada is not None and guardada.sesion.usuario_id == usuario_id


async def cuadro_del_negocio(
    actor: Actor,
    *,
    accesos: RepositorioAccesos,
    sesiones: RepositorioSesiones,
    registro: RegistroPresencia,
    momento: datetime | None = None,
    ttl_seg: int,
    negocio_solicitado: UUID | None = None,
) -> CuadroPresencia:
    """Quién está conectado en el negocio y quién no, con el motivo de cada rojo.

    Se combinan tres lecturas: las cuentas registradas, sus sesiones y las señales vivas. Se cruzan
    aquí y no en la base porque las señales no están en la base, y tres consultas simples se leen y
    se corrigen mejor que una que las junte con `LEFT JOIN` sobre datos que por separado ya no son
    fiables.

    **Solo un rol administrativo ve la presencia de los demás.** Que un compañero esté conectado es
    información sobre una persona, y el rol de lectura existe para consultar contrataciones, no para
    vigilar a los compañeros. Quien no administra se ve a sí mismo y a nadie más, en lugar de
    recibir un error: la pantalla sigue sirviendo para lo que esa persona la abre.
    """
    instante = momento or datetime.now(UTC)
    negocio = _negocio_efectivo(actor, negocio_solicitado)

    cuentas = list(await accesos.usuarios(negocio_id=negocio, limite=MAXIMO_USUARIOS))
    if not _ve_a_todos(actor):
        cuentas = [
            cuenta for cuenta in cuentas if _como_uuid(cuenta.get("usuario_id")) == actor.usuario_id
        ]

    activas = await sesiones.activas_del_negocio(negocio_id=negocio, momento=instante)
    revocadas = await sesiones.revocadas_del_negocio(
        negocio_id=negocio, limite=MAXIMO_SESIONES_REVOCADAS
    )
    vivos = await registro.vivas(negocio_id=negocio)

    latidos_por_usuario: dict[UUID, list[Latido]] = {}
    for latido in vivos:
        latidos_por_usuario.setdefault(latido.usuario_id, []).append(latido)

    # Las revocadas y caducadas solo sirven para explicar los rojos. Se guardan aparte de las
    # activas para que una sesión cerrada no pueda participar en la comprobación de «vigente», ni
    # por descuido: mezclarlas sería dar por abierta una sesión que ya no lo está.
    anteriores: dict[UUID, list[Sesion]] = {}
    for sesion in revocadas:
        if sesion.estado is not EstadoSesion.ACTIVA:
            anteriores.setdefault(sesion.usuario_id, []).append(sesion)

    presencias: list[Presencia] = []
    for cuenta in cuentas:
        usuario_id = _como_uuid(cuenta.get("usuario_id"))
        if usuario_id is None:
            continue
        mias = [sesion for sesion in activas if sesion.usuario_id == usuario_id]
        presencias.append(
            evaluar_presencia(
                usuario_id=usuario_id,
                estado_cuenta=str(cuenta.get("estado", "")),
                sesiones=[*mias, *anteriores.get(usuario_id, ())],
                latidos=latidos_por_usuario.get(usuario_id, []),
                momento=instante,
                ttl_seg=ttl_seg,
            )
        )

    # Conectados primero, y dentro de cada grupo en orden estable: un listado que se reordena solo
    # cada treinta segundos es imposible de leer mientras alguien lo está mirando.
    presencias.sort(key=lambda presencia: (not presencia.verde, str(presencia.usuario_id)))
    return CuadroPresencia(
        momento=instante, presencias=tuple(presencias), compartida=registro.compartida
    )


def _ve_a_todos(actor: Actor) -> bool:
    """¿Este rol puede ver la presencia de sus compañeros, o solo la suya?"""
    return puede_gestionar(actor.rol)


def _ambito(actor: Actor) -> str:
    """Con qué alcance se guarda y se sirve el cuadro para quien pregunta."""
    return AMBITO_TODOS if _ve_a_todos(actor) else str(actor.usuario_id)


def _negocio_efectivo(actor: Actor, negocio_solicitado: UUID | None) -> UUID:
    """Sobre qué negocio se pregunta, comprobando antes el permiso."""
    if negocio_solicitado is None:
        return actor.negocio_id
    actor.exigir_administrativo()
    return negocio_solicitado


async def cuadro_serializado(
    actor: Actor,
    *,
    accesos: RepositorioAccesos,
    sesiones: RepositorioSesiones,
    registro: RegistroPresencia,
    cache: Cache,
    momento: datetime | None = None,
    ttl_seg: int,
    ttl_cache_seg: int = TTL_CUADRO_SEG,
    negocio_solicitado: UUID | None = None,
) -> dict[str, object]:
    """El cuadro listo para enviar, servido del almacén cuando se puede.

    Es el camino que alimenta tanto la carga del panel como su relectura periódica, y con muchos
    paneles abiertos es el mayor consumidor de base de datos del sistema. Guardarlo unos segundos
    convierte una ráfaga de relecturas —que es lo normal, porque los paneles abren y laten casi a la
    vez— en un solo cálculo.

    **Solo se guarda cuando se pregunta por el negocio propio.** Con un negocio ajeno el resultado
    no depende solo del negocio: depende de quién pregunta, porque el aislamiento de la base decide
    qué se ve. Dos administradores de empresas distintas pidiendo el mismo negocio ajeno recibirían
    —con razón— cosas distintas, y compartiendo entrada el segundo leería lo que se calculó para el
    primero. Ese camino no se guarda y se calcula siempre.
    """
    if negocio_solicitado is not None and negocio_solicitado != actor.negocio_id:
        return (
            await cuadro_del_negocio(
                actor,
                accesos=accesos,
                sesiones=sesiones,
                registro=registro,
                momento=momento,
                ttl_seg=ttl_seg,
                negocio_solicitado=negocio_solicitado,
            )
        ).como_diccionario()

    negocio = _negocio_efectivo(actor, negocio_solicitado)
    clave = clave_cuadro(negocio, _ambito(actor))
    guardable = cache.habilitada and ttl_cache_seg > 0

    if guardable:
        try:
            guardado = await cache.obtener(clave)
        except Exception:  # noqa: BLE001 - sin almacén se calcula, no se falla
            registro_de_avisos.warning("El almacén no responde; el cuadro se calcula")
            guardado = None
            guardable = False
        if guardado is not None:
            try:
                recuperado = json.loads(guardado)
            except ValueError:
                recuperado = None
            if isinstance(recuperado, dict):
                return cast("dict[str, object]", recuperado)
            # Una entrada ilegible se descarta en lugar de servirse: devolver algo que no es el
            # cuadro dejaría el panel pintando una lista sin saber que no lo es.
            registro_de_avisos.warning("La instantánea guardada no era un cuadro; se descarta")

    cuadro = await cuadro_del_negocio(
        actor,
        accesos=accesos,
        sesiones=sesiones,
        registro=registro,
        momento=momento,
        ttl_seg=ttl_seg,
        negocio_solicitado=negocio_solicitado,
    )
    datos = cuadro.como_diccionario()

    if guardable:
        try:
            await cache.guardar(clave, json.dumps(datos, ensure_ascii=False), ttl_cache_seg)
        except Exception:  # noqa: BLE001 - no poder guardar no impide responder
            registro_de_avisos.warning("No se pudo guardar la instantánea de presencia")

    return datos


async def cerrar_por_ventana(
    actor: Actor,
    *,
    sesion_id: UUID,
    registro: RegistroPresencia,
    sesiones: RepositorioSesiones,
    bus: BusEventos,
    momento: datetime | None = None,
) -> EventoPresencia:
    """Cierra una sesión porque la persona cerró la pestaña.

    El motivo se guarda como `cierre_ventana` y no como `logout` porque la diferencia importa al
    auditar: cerrar sesión es una decisión —«ya terminé»— y cerrar la pestaña es irse. Si los dos se
    anotaran igual, el registro no permitiría distinguir a quien se despidió de quien simplemente se
    fue.

    Es idempotente en la práctica. El navegador puede mandar este aviso y no llegar a recibir
    respuesta —la persona está cerrando la pestaña, la conexión se corta—, y que falle no importa:
    el rojo llega igual al caducar la señal. Este aviso es una mejora de latencia, no un requisito
    para que el estado sea correcto.
    """
    instante = momento or datetime.now(UTC)
    guardada = await sesiones.por_id(negocio_id=actor.negocio_id, sesion_id=sesion_id)
    if guardada is None or guardada.sesion.usuario_id != actor.usuario_id:
        raise SinPermiso(NO_ENCONTRADA)

    await sesiones.revocar(
        negocio_id=actor.negocio_id,
        sesion_id=sesion_id,
        motivo=MotivoRevocacion.CIERRE_VENTANA,
        momento=instante,
    )
    await registro.olvidar(negocio_id=actor.negocio_id, sesion_id=sesion_id)

    presencia = Presencia(
        usuario_id=actor.usuario_id,
        estado=EstadoPresencia.ROJO,
        motivo=Motivo.SESION_CERRADA,
        sesion_id=sesion_id,
        ultimo_latido_en=None,
        dispositivos=0,
    )
    evento = evento_desconectado(actor.negocio_id, presencia, instante)
    await bus.publicar(negocio_id=actor.negocio_id, evento=evento)
    return evento


def _como_uuid(valor: object) -> UUID | None:
    """Convierte a identificador lo que devuelve la consulta de usuarios.

    Es una lectura de apoyo para el panel, no un dato del que dependa una decisión de autorización,
    así que un valor inesperado se descarta en lugar de tumbar el listado entero.
    """
    if isinstance(valor, UUID):
        return valor
    if isinstance(valor, str):
        try:
            return UUID(valor)
        except ValueError:
            return None
    return None
