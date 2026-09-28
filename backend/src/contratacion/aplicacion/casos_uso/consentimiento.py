"""Casos de uso del consentimiento.

Cuatro operaciones: **consultar el estado**, **leer el texto**, **aceptar** y **revocar**.

La regla que sostiene todo el apartado legal
-------------------------------------------
**Quién decide si falta aceptar es el servidor, y solo el servidor.** Si lo decidiera el cliente
—«si el navegador dice que ya aceptó, le dejo pasar»—, bastaría con abrir las herramientas del
desarrollador o editar el JavaScript para entrar sin aceptar nada. La puerta se comprueba aquí, en
el caso de uso, para que valga igual desde la API que desde cualquier otra entrada.

La segunda regla, que es la que convierte la aceptación en evidencia
-------------------------------------------------------------------
Al aceptar, el cliente declara **qué versión y qué huella** dice haber leído, y se exige que
coincidan con lo publicado en ese instante. Si el texto cambió mientras la persona lo leía, la
aceptación se rechaza y se le pide recargar.

Parece excesivo y es lo contrario: aceptar sin comprobarlo guardaría una prueba que afirma que esa
persona leyó un documento que nunca tuvo delante. Una evidencia falsa es peor que ninguna, porque
alguien podría llegar a apoyarse en ella.
Sobre el botón que se habilita al llegar al final
------------------------------------------------
Está implementado en la interfaz y **el servidor no lo puede verificar**. Conviene decirlo claro en
lugar de dar a entender que hay una garantía: ninguna arquitectura puede demostrar que alguien leyó.
Lo que sí se demuestra, y es lo que importa, es **qué texto exacto** estaba delante cuando pulsó
aceptar, y eso lo garantizan la versión y la huella."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.puertos.cuentas import RepositorioCuentas
from contratacion.aplicacion.puertos.politicas import (
    RepositorioConsentimientos,
    RepositorioPoliticas,
)
from contratacion.dominio.errores import ConsentimientoPendiente, EstadoInvalido, NoEncontrado
from contratacion.dominio.politicas import (
    POLITICAS_OBLIGATORIAS,
    TITULO_POLITICA,
    Pendientes,
    Politica,
    TipoPolitica,
)
from contratacion.dominio.politicas import (
    pendientes as calcular_pendientes,
)

registro = logging.getLogger(__name__)

MENSAJE_PENDIENTE = (
    "Tienes que aceptar los términos y condiciones para usar el aplicativo. "
    "Abre la pantalla de aceptación y vuelve a intentarlo."
)
MENSAJE_TEXTO_CAMBIADO = (
    "Los términos cambiaron mientras los leías, así que no se registró tu aceptación. "
    "Vuelve a cargarlos y acéptalos otra vez: la aceptación debe corresponder al texto que lees."
)
MENSAJE_REVOCADO = (
    "Has retirado tu consentimiento. El aplicativo queda bloqueado hasta que vuelvas a aceptar los "
    "términos."
)


@dataclass(frozen=True, slots=True)
class EstadoConsentimiento:
    """Lo que hay que aceptar y lo que ya está aceptado."""

    pendientes: Pendientes
    catalogo: tuple[dict[str, object], ...]

    def como_diccionario(self) -> dict[str, object]:
        return {
            **self.pendientes.como_diccionario(),
            "catalogo": list(self.catalogo),
        }


def _metadatos(politica: Politica, *, pendiente: bool) -> dict[str, object]:
    """Datos de una política sin su texto.

    El texto no viaja aquí a propósito: pesa, y el enlace «términos y condiciones» lo pide solo
    cuando alguien lo pulsa. Mandarlo siempre en cada consulta de estado sería enviar varios miles
    de caracteres para pintar una casilla.
    """
    return {
        "tipo": str(politica.tipo),
        "titulo": politica.titulo,
        "version": politica.version,
        "hash": politica.hash,
        "vigente_desde": politica.vigente_desde.isoformat(),
        "obligatoria": politica.tipo in POLITICAS_OBLIGATORIAS,
        "pendiente": pendiente,
    }


async def estado(
    actor: Actor,
    *,
    politicas: RepositorioPoliticas,
    consentimientos: RepositorioConsentimientos,
) -> EstadoConsentimiento:
    """Qué le falta aceptar, y el catálogo completo con su versión y su huella.

    El estado se calcula **comparando el texto publicado con lo aceptado**, no leyendo una bandera.
    Una bandera hay que acordarse de actualizarla en cada camino que la afecte, y el día que se
    olvide el sistema dirá que todo está aceptado sin que nadie haya aceptado nada.
    """
    publicadas = tuple(await politicas.vigentes())
    aceptadas = tuple(
        await consentimientos.del_usuario(negocio_id=actor.negocio_id, usuario_id=actor.usuario_id)
    )
    faltantes = calcular_pendientes(publicadas=publicadas, aceptadas=aceptadas)
    tipos_pendientes = set(faltantes.tipos)

    return EstadoConsentimiento(
        pendientes=faltantes,
        catalogo=tuple(
            _metadatos(politica, pendiente=politica.tipo in tipos_pendientes)
            for politica in publicadas
        ),
    )


async def texto(
    tipo: TipoPolitica,
    *,
    politicas: RepositorioPoliticas,
) -> Politica:
    """El texto completo de una política, con su versión y su huella.

    El cliente recibe la huella junto al texto para poder declararla al aceptar. Así no hay que
    recalcularla en el navegador: se devuelve la que el servidor guardó, y la aceptación solo es
    válida si coincide con la que sigue publicada."""
    publicada = await politicas.vigente(tipo)
    if publicada is None:
        raise NoEncontrado(
            f"Todavía no se ha publicado «{TITULO_POLITICA[tipo]}». "
            "Avisa al administrador: es un problema de despliegue, no algo que puedas resolver."
        )
    return publicada


async def aceptar(
    actor: Actor,
    *,
    tipo: TipoPolitica,
    version: int,
    hash_texto: str,
    politicas: RepositorioPoliticas,
    consentimientos: RepositorioConsentimientos,
    cuentas: RepositorioCuentas,
    momento: datetime | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> Politica:
    """Registra la aceptación y levanta el bloqueo de esa cuenta.

    Se comprueba que lo aceptado sea **lo publicado ahora**, y solo entonces se guarda. Si no
    coincide, se rechaza: es mejor pedir que recarguen un texto que guardar la prueba de haber
    leído otro.

    La aceptación no se guarda «por encima» de las anteriores: se añade una fila nueva. El historial
    de aceptaciones es parte de la evidencia, y reescribirlo borraría lo que hay que demostrar.
    """
    instante = momento or datetime.now(UTC)
    publicada = await politicas.vigente(tipo)
    if publicada is None:
        raise NoEncontrado(f"Todavía no se ha publicado «{TITULO_POLITICA[tipo]}».")

    if not publicada.coincide_con(version=version, hash_texto=hash_texto):
        raise EstadoInvalido(MENSAJE_TEXTO_CAMBIADO)

    consentimiento_id = await consentimientos.registrar(
        negocio_id=actor.negocio_id,
        usuario_id=actor.usuario_id,
        tipo=tipo,
        version=publicada.version,
        hash_texto=publicada.hash,
        momento=instante,
        ip=ip,
        user_agent=user_agent,
        metodo="formulario",
    )
    await consentimientos.limpiar_pendiente(
        negocio_id=actor.negocio_id, usuario_id=actor.usuario_id
    )
    await cuentas.auditar(
        accion="consentimiento_aceptado",
        negocio_id=actor.negocio_id,
        usuario_id=actor.usuario_id,
        entidad="consentimiento",
        entidad_id=str(consentimiento_id),
        resultado="aceptado",
        ip=ip,
        user_agent=user_agent,
        # La versión y la huella van al registro de auditoría además de a la tabla: si alguien
        # alterara una fila de consentimientos, la auditoría —que es particionada y de solo
        # escritura— conservaría lo que se registró en su momento.
        detalle={
            "tipo": str(tipo),
            "version": publicada.version,
            "hash": publicada.hash,
        },
    )
    registro.info(
        "Aceptación registrada: tipo=%s version=%s usuario=%s",
        tipo,
        publicada.version,
        actor.usuario_id,
    )
    return publicada


async def revocar(
    actor: Actor,
    *,
    tipo: TipoPolitica,
    politicas: RepositorioPoliticas,
    consentimientos: RepositorioConsentimientos,
    cuentas: RepositorioCuentas,
    momento: datetime | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> int:
    """Retira el consentimiento y **bloquea el aplicativo** hasta que se vuelva a aceptar.

    Bloquear es la consecuencia honesta y no un castigo. Retirar el consentimiento significa que la
    plataforma ya no puede tratar los datos de esa persona, y el aplicativo existe para tratarlos:
    si se le dejara seguir usándolo, se estaría ignorando lo que acaba de pedir.

    La fila no se borra, se marca como revocada con su fecha. Borrarla destruiría la prueba de que
    existió una aceptación previa, que es justo lo que hay que poder demostrar.

    Se puede revocar aunque no haya nada que revocar. Devolver un error obligaría a la interfaz a
    consultar antes de cada pulsación para no mostrar un fallo, y no hay nada roto en pedir dos
    veces lo mismo.
    """
    instante = momento or datetime.now(UTC)
    afectadas = await consentimientos.revocar(
        negocio_id=actor.negocio_id,
        usuario_id=actor.usuario_id,
        tipo=tipo,
        momento=instante,
    )

    publicada = await politicas.vigente(tipo)
    if publicada is not None:
        await consentimientos.marcar_pendiente(
            negocio_id=actor.negocio_id, usuario_id=actor.usuario_id, version=publicada.version
        )

    await cuentas.auditar(
        accion="consentimiento_revocado",
        negocio_id=actor.negocio_id,
        usuario_id=actor.usuario_id,
        entidad="consentimiento",
        entidad_id=str(tipo),
        resultado="revocado",
        ip=ip,
        user_agent=user_agent,
        detalle={
            "tipo": str(tipo),
            "aceptaciones_revocadas": afectadas,
            "version_vigente": publicada.version if publicada else None,
        },
    )
    registro.info(
        "Consentimiento revocado: tipo=%s usuario=%s aceptaciones=%d",
        tipo,
        actor.usuario_id,
        afectadas,
    )
    return afectadas


async def exigir_aceptado(actor: Actor, *, consentimientos: RepositorioConsentimientos) -> None:
    """Puerta de bloqueo: se niega a seguir si la cuenta debe alguna aceptación.

    Lee el marcador de la cuenta, que es una sola consulta sobre la clave primaria. Lo escriben
    únicamente las operaciones que pueden cambiarlo —publicar una versión, aceptarla y **crear una
    cuenta nueva**—, y hay una prueba que comprueba que coincide con el estado real; ver
    `aplicacion/puertos/politicas.py`.
    **Falla cerrada**: ante un error al consultar el marcador no se deja pasar. Un bloqueo legal
    que se abre cuando la base tiene un problema no es un bloqueo.
    """
    pendiente = await consentimientos.pendiente_de(
        negocio_id=actor.negocio_id, usuario_id=actor.usuario_id
    )
    if pendiente is not None:
        raise ConsentimientoPendiente(MENSAJE_PENDIENTE)


async def marcar_lo_obligatorio_pendiente(
    *,
    negocio_id: UUID,
    usuario_id: UUID,
    politicas: RepositorioPoliticas,
    consentimientos: RepositorioConsentimientos,
) -> None:
    """Marca una cuenta recién creada como deudora de las políticas obligatorias.

    Existe por un defecto que es el peor posible en esta parte del sistema: **la puerta dejaba
    pasar a los usuarios nuevos**. El marcador que lee `exigir_aceptado` se escribía solo al
    publicar una versión de los términos —y ahí alcanza a las cuentas que ya existían— y al
    revocar. Una cuenta creada después de la última publicación nacía con el marcador vacío, así
    que el bloqueo no la veía y podía usarse el aplicativo sin aceptar nada. El registro de
    empresas, que crea cuentas todo el tiempo, era el camino más ancho hacia ese agujero.

    No se detecta mirando la respuesta del registro: la cuenta entra, funciona, y el
    incumplimiento solo aparece si alguien compara el listado de políticas pendientes con la
    respuesta de la puerta.

    Se marca la versión más alta de las obligatorias porque el marcador guarda **una** versión y
    lo que importa es que la cuenta deba algo: cualquier duda se resuelve del lado de exigir la
    aceptación, que es el lado seguro. Si no hay ninguna obligatoria publicada no se marca nada,
    y entonces la puerta no bloquea, que es lo correcto.
    """
    publicadas = await politicas.vigentes()
    obligatorias = [politica for politica in publicadas if politica.tipo in POLITICAS_OBLIGATORIAS]
    if not obligatorias:
        return

    await consentimientos.marcar_pendiente(
        negocio_id=negocio_id,
        usuario_id=usuario_id,
        version=max(politica.version for politica in obligatorias),
    )
