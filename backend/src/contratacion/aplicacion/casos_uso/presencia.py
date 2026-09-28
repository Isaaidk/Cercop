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

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.puertos.accesos import RepositorioAccesos
from contratacion.aplicacion.puertos.cuentas import RepositorioSesiones
from contratacion.aplicacion.puertos.presencia import BusEventos, RegistroPresencia
from contratacion.dominio.acceso import puede_gestionar
from contratacion.dominio.errores import SinPermiso
from contratacion.dominio.presencia import (
    EstadoPresencia,
    EventoPresencia,
    Latido,
    Motivo,
    Presencia,
    evaluar_presencia,
    evento_conectado,
    evento_desconectado,
)
from contratacion.dominio.sesiones import EstadoSesion, MotivoRevocacion, Sesion

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
    bus: BusEventos,
    momento: datetime | None = None,
    ttl_seg: int,
) -> EventoPresencia:
    """Anota que la sesión sigue viva y lo anuncia al negocio.

    **La sesión se valida antes de dar nada por vivo.** Sin esta comprobación, una sesión revocada
    seguiría latiendo y el panel la mostraría en verde hasta que el usuario cerrara la pestaña:
    exactamente el caso que la revocación existe para cortar. Cuesta una lectura por latido —una
    cada 30 s por persona conectada— y ese precio se paga a gusto, porque la alternativa es un color
    que afirma lo contrario de lo que acaba de decidir un administrador.
    """
    instante = momento or datetime.now(UTC)
    guardada = await sesiones.por_id(negocio_id=actor.negocio_id, sesion_id=sesion_id)
    if guardada is None or guardada.sesion.usuario_id != actor.usuario_id:
        raise SinPermiso(NO_ENCONTRADA)

    await registro.marcar(
        usuario_id=actor.usuario_id,
        sesion_id=sesion_id,
        negocio_id=actor.negocio_id,
        momento=instante,
        ttl_seg=ttl_seg,
    )

    presencia = evaluar_presencia(
        usuario_id=actor.usuario_id,
        estado_cuenta="activo",
        sesiones=[guardada.sesion],
        latidos=[Latido(usuario_id=actor.usuario_id, sesion_id=sesion_id, momento=instante)],
        momento=instante,
        ttl_seg=ttl_seg,
    )
    evento = evento_conectado(actor.negocio_id, presencia, instante)
    # Se anuncia en cada latido, aunque el estado no haya cambiado. Es redundante a propósito: el
    # aviso de conexión es lo que pone al día a un panel recién abierto, y repetirlo hace que un
    # aviso perdido se recupere en el latido siguiente en lugar de esperar a la relectura periódica.
    # Un aviso de más cuesta un mensaje; uno de menos deja el panel mintiendo.
    await bus.publicar(negocio_id=actor.negocio_id, evento=evento)
    return evento


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
    if negocio_solicitado is not None:
        actor.exigir_administrativo()
        negocio = negocio_solicitado
    else:
        negocio = actor.negocio_id

    cuentas = list(await accesos.usuarios(negocio_id=negocio, limite=MAXIMO_USUARIOS))
    if not puede_gestionar(actor.rol):
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
