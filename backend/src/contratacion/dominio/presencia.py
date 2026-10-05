"""Reglas de presencia: quién está conectado, quién no y **por qué**.

Aquí no hay Redis ni HTTP. Lo único que se decide es, dadas las sesiones registradas de una persona
y las señales de vida que ha dejado, de qué color es su punto y qué texto lo explica.

Las dos reglas que sostienen todo
---------------------------------
**Verde = señal viva *y* sesión vigente.** Hacen falta las dos cosas, y ninguna es suficiente:

- Solo con la señal, una sesión revocada por un administrador seguiría en verde mientras el
  navegador siguiera latiendo. La revocación no se notaría hasta que el usuario cerrara la pestaña.
- Solo con la sesión, todo el mundo aparecería conectado para siempre: la fila sigue en la base
  después de que alguien apague el portátil.

**La ausencia de señal no es un cierre.** Cuando alguien cierra el navegador de golpe —o se le va el
wifi, o se queda sin batería— no llega ningún aviso. La única señal de que se fue es que deja de
llegar el latido, y eso se nota al vencer su vigencia. Por eso el rojo tiene un piso de detección y
no es instantáneo: es una limitación del problema, no del código, y se prefiere un rojo que llega un
minuto tarde a un verde que miente para siempre.

Por qué el motivo se calcula aquí y no se lee de la base
-------------------------------------------------------
La base guarda *por qué se revocó* una sesión (`logout`, `eviccion`, `admin`, `reuso_detectado`,
`cierre_ventana`) y esa lista es cerrada. «Se le fue el wifi» no está en ella, y no debería estar:
no es una revocación, es la falta de una señal. Así que el motivo del rojo se deriva de lo que se
sabe —el estado de la cuenta, el estado de cada sesión, si hay latido— y no de una columna que
tendría que inventarse un valor para algo que nadie decidió.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from contratacion.dominio.sesiones import MotivoRevocacion, Sesion

# Las señales de vida se guardan bajo esta clave. El negocio va delante del identificador de sesión
# para poder listar las de un solo negocio con un recorrido por prefijo, sin tocar las de los demás.
PREFIJO_LATIDO = "presencia:"
PREFIJO_CANAL = "presencia:canal:"

# El cuadro completo —quién está conectado y quién no— también se guarda un momento. La razón está
# en la aritmética: mientras alguien tiene el panel abierto, el cuadro se recalcula cada
# `SEGUNDOS_ENTRE_INSTANTANEAS` y cuesta cuatro consultas, así que con muchos paneles abiertos es,
# con diferencia, el mayor consumidor de base de datos de todo el sistema.
PREFIJO_CUADRO = "presencia:cuadro:"

# Alcance de quien pregunta, dentro de la clave. **Va en la clave y no en el valor**, y es la parte
# que no se puede saltar: un administrador ve la presencia de toda su empresa y un lector se ve solo
# a sí mismo. Si la clave fuera solo el negocio, el listado calculado para el administrador —con
# todos sus compañeros dentro— se le serviría al lector, que pasaría a ver justo lo que esta regla
# existe para no enseñarle. Con el alcance dentro, cada uno tiene su entrada y ninguna se cruza.
AMBITO_TODOS = "todos"

# Lo que dura la instantánea guardada. Corto a propósito: el panel relee cada quince segundos, así
# que unas pocas unidades no se notan en pantalla y sí convierten una ráfaga de paneles que releen a
# la vez —lo normal, porque todos abren y latieron aproximadamente al mismo tiempo— en un solo
# cálculo. Los avisos de entrada y salida no esperan a que venza: llegan por el canal y se pintan al
# instante, así que este plazo no retrasa nada de lo que se ve cambiar.
TTL_CUADRO_SEG = 3

# Patrón que abarca **todos** los canales de negocio. Es lo que permite a un proceso escucharlos
# con una sola suscripción por patrón, en lugar de una por canal: suscribirse y desuscribirse según
# quién esté mirando el panel exigiría enviar comandos por la conexión que ya se está leyendo, que
# es justo la parte delicada de Pub/Sub. A cambio se reciben también los avisos de empresas que este
# proceso no atiende, y con la frecuencia real de estos avisos —un latido cada treinta segundos por
# persona— eso es despreciable.
PATRON_CANALES = f"{PREFIJO_CANAL}*"

# Estados de cuenta que pueden estar conectados. Un usuario «pendiente» todavía no aceptó los
# términos, pero puede entrar —así es como los acepta—, así que cuenta como persona conectable.
ESTADOS_CONECTABLES = frozenset({"activo", "pendiente"})

# Margen con el que se refresca la instantánea durante una transmisión en vivo. Es la red de
# seguridad frente a un evento perdido: los avisos hacen que el color cambie al instante, y esta
# relectura periódica garantiza que, aunque uno se pierda, el panel se corrija solo.
SEGUNDOS_ENTRE_INSTANTANEAS = 15


class EstadoPresencia(StrEnum):
    """El color del punto."""

    VERDE = "verde"
    ROJO = "rojo"


class Motivo(StrEnum):
    """Por qué el punto tiene ese color. Es lo que se muestra al lado."""

    CONECTADO = "conectado"
    SIN_SENAL = "sin_senal"
    SESION_CERRADA = "sesion_cerrada"
    CIERRE_ADMIN = "cierre_admin"
    EVICCION = "eviccion"
    SESION_EXPIRADA = "sesion_expirada"
    CUENTA_INACTIVA = "cuenta_inactiva"
    SIN_ACCESO = "sin_acceso"


# Textos escritos para que los lea una persona. El panel los pinta tal cual al lado del color: un
# punto rojo sin explicación obliga a preguntar por teléfono qué pasó.
DESCRIPCION_MOTIVO: dict[Motivo, str] = {
    Motivo.CONECTADO: "Conectado ahora",
    Motivo.SIN_SENAL: "Sin señal: el navegador dejó de responder o se cerró sin avisar",
    Motivo.SESION_CERRADA: "Cerró la sesión",
    Motivo.CIERRE_ADMIN: "Un administrador cerró su sesión",
    Motivo.EVICCION: "Entró desde otro dispositivo y se superó el máximo de sesiones",
    Motivo.SESION_EXPIRADA: "Su sesión caducó por inactividad",
    Motivo.CUENTA_INACTIVA: "Su cuenta no está habilitada",
    Motivo.SIN_ACCESO: "Todavía no ha entrado nunca",
}


@dataclass(frozen=True, slots=True)
class Latido:
    """Una señal de vida: «esta sesión sigue con el navegador abierto a tal hora»."""

    usuario_id: UUID
    sesion_id: UUID
    momento: datetime


@dataclass(frozen=True, slots=True)
class Presencia:
    """El color de una persona, con su explicación."""

    usuario_id: UUID
    estado: EstadoPresencia
    motivo: Motivo
    sesion_id: UUID | None = None
    ultimo_latido_en: datetime | None = None
    dispositivos: int = 0

    @property
    def descripcion(self) -> str:
        return DESCRIPCION_MOTIVO[self.motivo]

    @property
    def verde(self) -> bool:
        return self.estado is EstadoPresencia.VERDE

    def como_diccionario(self) -> dict[str, object]:
        return {
            "usuario_id": str(self.usuario_id),
            "estado": str(self.estado),
            "motivo": str(self.motivo),
            "descripcion": self.descripcion,
            "sesion_id": str(self.sesion_id) if self.sesion_id else None,
            "ultimo_latido_en": (
                self.ultimo_latido_en.isoformat() if self.ultimo_latido_en else None
            ),
            "dispositivos": self.dispositivos,
        }


def clave_latido(negocio_id: UUID, sesion_id: UUID) -> str:
    """Clave con la que se guarda la señal de una sesión.

    Se indexa por **sesión**, no por usuario, y esa diferencia importa: alguien con el panel abierto
    en el portátil y en el teléfono tiene dos señales. Si se indexara por usuario, cerrar el
    portátil apagaría también la señal del teléfono y la persona aparecería desconectada estando
    delante.
    """
    return f"{PREFIJO_LATIDO}{negocio_id}:{sesion_id}"


def prefijo_de_negocio(negocio_id: UUID) -> str:
    """Prefijo con el que se listan las señales de un negocio, sin ver las de los demás."""
    return f"{PREFIJO_LATIDO}{negocio_id}:"


def clave_cuadro(negocio_id: UUID, ambito: str) -> str:
    """Clave de la instantánea de presencia de un negocio, para un alcance concreto.

    El alcance es `AMBITO_TODOS` para quien puede ver a sus compañeros, y el identificador de la
    persona para quien solo se ve a sí misma. Omitirlo sería servir el listado del administrador a
    un lector.
    """
    return f"{PREFIJO_CUADRO}{negocio_id}:{ambito}"


def canal_de_negocio(negocio_id: UUID) -> str:
    """Canal por el que se avisa a los paneles de un negocio.

    Un canal por negocio, y no uno global, para que el aviso de que alguien entró en una empresa no
    se envíe siquiera a los paneles de otra. Filtrar al recibir sería más frágil: el aislamiento se
    garantiza mejor en el transporte que en una condición que alguien pueda olvidar.
    """
    return f"{PREFIJO_CANAL}{negocio_id}"


def negocio_de_canal(canal: str) -> UUID | None:
    """Negocio al que pertenece un canal, o `None` si el nombre no es de un canal de negocio.

    Es la vuelta de `canal_de_negocio` y vive pegada a ella a propósito: son la misma regla vista
    desde los dos lados, y separarlas es como se acaba publicando con un formato y leyendo con otro.

    Un nombre desconocido devuelve `None` en lugar de lanzar: por un canal puede llegar cualquier
    cosa, y un mensaje raro no puede cortar el reparto de todos los demás.
    """
    if not canal.startswith(PREFIJO_CANAL):
        return None
    try:
        return UUID(canal[len(PREFIJO_CANAL) :])
    except ValueError:
        return None


def latido_vivo(latido: Latido, momento: datetime, ttl_seg: int) -> bool:
    """¿La señal sigue vigente?

    Se compara contra la hora del momento de la consulta en vez de fiarse de que el almacén haya
    caducado la clave: la implementación sin Redis guarda en memoria y podría devolver una señal
    vieja, y dos réplicas podrían no compartir el mismo reloj. Comprobar aquí hace que la respuesta
    no dependa de que el almacén haga bien su parte.
    """
    return momento - latido.momento < timedelta(seconds=ttl_seg)


def latidos_vivos(latidos: Sequence[Latido], momento: datetime, ttl_seg: int) -> tuple[Latido, ...]:
    """Señales vigentes, la más reciente primero."""
    vivos = [latido for latido in latidos if latido_vivo(latido, momento, ttl_seg)]
    return tuple(sorted(vivos, key=lambda latido: latido.momento, reverse=True))


def evaluar_presencia(
    *,
    usuario_id: UUID,
    estado_cuenta: str,
    sesiones: Sequence[Sesion],
    latidos: Sequence[Latido],
    momento: datetime,
    ttl_seg: int,
) -> Presencia:
    """Decide el color y lo explica.

    El orden de las comprobaciones es la regla: se pregunta primero por la cuenta, luego por la
    coincidencia de señal y sesión, y solo después por los motivos del rojo. Invertirlo daría
    respuestas peores —por ejemplo, explicar «cerró la sesión» a alguien cuya cuenta está
    deshabilitada, cuando lo relevante es que no puede entrar—.
    """
    if estado_cuenta not in ESTADOS_CONECTABLES:
        return Presencia(
            usuario_id=usuario_id,
            estado=EstadoPresencia.ROJO,
            motivo=Motivo.CUENTA_INACTIVA,
        )

    vigentes = {sesion.id for sesion in sesiones if sesion.vigente(momento)}
    vivos = latidos_vivos(latidos, momento, ttl_seg)
    conectado = next((latido for latido in vivos if latido.sesion_id in vigentes), None)

    if conectado is not None:
        # Cuántos dispositivos tiene abiertos, para que el panel pueda decir «también en el móvil».
        abiertos = len(vigentes & {latido.sesion_id for latido in vivos})
        return Presencia(
            usuario_id=usuario_id,
            estado=EstadoPresencia.VERDE,
            motivo=Motivo.CONECTADO,
            sesion_id=conectado.sesion_id,
            ultimo_latido_en=conectado.momento,
            dispositivos=max(1, abiertos),
        )

    motivo = _motivo_del_rojo(sesiones=sesiones, momento=momento, hay_senal=bool(vivos))
    ultimo = vivos[0].momento if vivos else None
    return Presencia(
        usuario_id=usuario_id,
        estado=EstadoPresencia.ROJO,
        motivo=motivo,
        ultimo_latido_en=ultimo,
        dispositivos=0,
    )


def presencia_de_sesion_viva(*, usuario_id: UUID, sesion_id: UUID, momento: datetime) -> Presencia:
    """La presencia de una sesión que **se acaba de comprobar viva**.

    Existe para que el latido no tenga que construir una `Sesion` entera solo para que
    `evaluar_presencia` diga lo que ya se sabe. El latido comprueba primero que la sesión siga
    viva —contra el almacén, sin tocar la base— y con eso la respuesta está decidida: verde, y el
    motivo es que está conectado.

    Está aquí y no en el caso de uso por la misma razón que todo lo demás de este módulo: **la regla
    del semáforo es una sola**. Si el latido decidiera el color por su cuenta, el día que la regla
    cambiara —un estado nuevo, un motivo nuevo— el latido seguiría diciendo lo de antes y el panel
    mostraría dos verdades distintas según por dónde se preguntara.

    `dispositivos` vale 1 y no es un descuido: el latido habla de **una** sesión, la suya. Cuántos
    dispositivos tiene abiertos lo dice el cuadro de presencia, que sí mira todas.
    """
    return Presencia(
        usuario_id=usuario_id,
        estado=EstadoPresencia.VERDE,
        motivo=Motivo.CONECTADO,
        sesion_id=sesion_id,
        ultimo_latido_en=momento,
        dispositivos=1,
    )


def _motivo_del_rojo(*, sesiones: Sequence[Sesion], momento: datetime, hay_senal: bool) -> Motivo:
    """Explica un rojo. Se elige el motivo más informativo de los que se pueden afirmar.

    La primera comprobación es la que evita el error fácil: **si todavía hay una sesión abierta**,
    la explicación es que dejó de llegar la señal, sin importar lo que dijera una revocación del
    pasado. Sin esto, a alguien con la pestaña abierta y una sesión revocada por evicción hace tres
    días se le explicaría «entró desde otro dispositivo» cuando lo que ha pasado es que se le fue el
    wifi. El orden importa: se informa de lo que sigue siendo cierto, no de lo que pasó alguna vez.

    Solo cuando no queda ninguna sesión abierta se mira la historia, y ahí sí se prefiere lo que
    alguien decidió —una revocación tiene un responsable y una explicación que dar— sobre lo que
    simplemente ocurrió, como una caducidad.
    """
    if any(sesion.vigente(momento) for sesion in sesiones):
        return Motivo.SIN_SENAL

    ordenadas = sorted(sesiones, key=lambda sesion: sesion.ultimo_uso_en, reverse=True)

    for sesion in ordenadas:
        if sesion.motivo_revocacion is not None:
            # Claves del enumerado y no cadenas: un motivo escrito a mano que no exista no daría
            # error, simplemente no coincidiría nunca y el panel diría «sin señal» para siempre.
            preferido = MOTIVO_POR_REVOCACION.get(sesion.motivo_revocacion)
            if preferido is not None:
                return preferido

    if sesiones:
        return Motivo.SESION_EXPIRADA

    if hay_senal:
        # Una señal sin ninguna sesión que la respalde solo puede venir de una sesión ya borrada.
        # Se informa como cierre, porque afirmar «conectado» sin sesión vigente sería justo el
        # fallo que esta comprobación cruzada existe para evitar.
        return Motivo.SESION_CERRADA

    return Motivo.SIN_ACCESO


MOTIVO_POR_REVOCACION: dict[MotivoRevocacion, Motivo] = {
    MotivoRevocacion.LOGOUT: Motivo.SESION_CERRADA,
    MotivoRevocacion.CIERRE_VENTANA: Motivo.SESION_CERRADA,
    MotivoRevocacion.EVICCION: Motivo.EVICCION,
    MotivoRevocacion.ADMIN: Motivo.CIERRE_ADMIN,
    MotivoRevocacion.REUSO_DETECTADO: Motivo.SESION_CERRADA,
}


class TipoEvento(StrEnum):
    """Qué se está anunciando por el canal del negocio."""

    CONECTADO = "conectado"
    DESCONECTADO = "desconectado"
    # Relectura completa del negocio. Es la que corrige el panel cuando un aviso se pierde, y la que
    # refleja un rojo por falta de señal, que por definición no genera ningún aviso.
    INSTANTANEA = "instantanea"
    # Latido de la propia transmisión, para que un proxy no cierre la conexión por inactividad.
    LATIDO = "latido"


@dataclass(frozen=True, slots=True)
class EventoPresencia:
    """Un aviso que viaja por el canal del negocio."""

    tipo: TipoEvento
    negocio_id: UUID
    momento: datetime
    presencia: Presencia | None = None
    presencias: tuple[Presencia, ...] = ()

    def como_diccionario(self) -> dict[str, object]:
        cuerpo: dict[str, object] = {
            "tipo": str(self.tipo),
            "momento": self.momento.isoformat(),
        }
        if self.presencia is not None:
            cuerpo["usuario"] = self.presencia.como_diccionario()
        if self.presencias:
            cuerpo["usuarios"] = [presencia.como_diccionario() for presencia in self.presencias]
        return cuerpo


def evento_conectado(negocio_id: UUID, presencia: Presencia, momento: datetime) -> EventoPresencia:
    return EventoPresencia(
        tipo=TipoEvento.CONECTADO, negocio_id=negocio_id, momento=momento, presencia=presencia
    )


def evento_desconectado(
    negocio_id: UUID, presencia: Presencia, momento: datetime
) -> EventoPresencia:
    return EventoPresencia(
        tipo=TipoEvento.DESCONECTADO, negocio_id=negocio_id, momento=momento, presencia=presencia
    )
