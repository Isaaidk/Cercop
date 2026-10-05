"""Pedir un ciclo de ingesta y ver el trabajo que han hecho los workers.

Es la mitad administrativa de la ingesta, y va aparte de todo lo demás por una razón de
arquitectura: **el único proceso que habla con el SERCOP es el worker**. Un endpoint que ingestara
dentro de la petición HTTP rompería las dos reglas que sostienen el diseño —el requisito R-01 y el
caso de uso CU-07: ninguna petición de usuario puede originar tráfico hacia la fuente— y además
dejaría al API bloqueado durante minutos, que es justo lo que el worker viene a evitar.

Así que la petición viaja por el único canal que los dos procesos comparten: la caché. El panel
escribe «quiero un ciclo ahora» y el worker, que mira cada pocos segundos, lo toma y lo ejecuta.
La petición **se borra al recogerla**: una petición es una vez, no una orden permanente que se
vuelva a ejecutar en cada vuelta.

El historial tampoco se inventa nada: se lee de `sincronizacion`, la tabla que los ciclos ya
escriben para poder auditarse. Dibujar el trabajo del worker no exige instrumentar nada nuevo.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.casos_uso.administrar_negocios import es_de_plataforma
from contratacion.aplicacion.puertos.cache import Cache
from contratacion.aplicacion.puertos.consultas import RepositorioConsultas
from contratacion.dominio.errores import EstadoInvalido, SinPermiso
from contratacion.dominio.serializacion import a_json, de_json

# Clave de la caché donde vive la petición. Una sola: la ingesta es un recurso único —hay un
# bloqueo, un presupuesto y una fuente— y dos peticiones a la vez no son dos ciclos, son el mismo.
CLAVE_SOLICITUD = "ingesta:solicitud"

# Lo que vive una petición sin que nadie la recoja. Quince minutos es más que el ciclo completo, así
# que si el worker está vivo la recoge de sobra; y si está caído, no queda una orden antigua
# esperando a que vuelva para disparar un ciclo a traición horas después.
TTL_SOLICITUD_SEG = 900

# Cada cuánto mira el worker si le han pedido un ciclo. Es también lo que tarda como mucho en
# atenderla, y por eso se puede pulsar el botón y ver el ciclo arrancar sin pensar que no funciona.
PASO_COMPROBACION_SEG = 5.0

# Ciclos que se dibujan por fuente. Veinticuatro son seis horas de la cadencia de quince minutos:
# suficiente para ver el latido y detectar una racha de fallos sin llenar la pantalla de barras.
CICLOS_POR_FUENTE = 24


@dataclass(frozen=True, slots=True)
class SolicitudCiclo:
    """Una petición de ciclo, con quién la hizo y cuándo."""

    solicitado_por: str
    solicitado_en: datetime

    def como_diccionario(self) -> dict[str, Any]:
        return {
            "solicitado_por": self.solicitado_por,
            "solicitado_en": self.solicitado_en.isoformat(),
        }


def _exigir_plataforma(actor: Actor) -> None:
    if not es_de_plataforma(actor):
        raise SinPermiso("Solo el superadministrador de la plataforma puede ordenar la ingesta.")


def _leer(texto: str | None) -> SolicitudCiclo | None:
    """Convierte lo guardado en una petición. Un valor ilegible no es una petición."""
    if not texto:
        return None
    try:
        datos = de_json(texto)
    except Exception:  # noqa: BLE001 - un valor corrupto equivale a no tener petición
        return None
    if not isinstance(datos, dict):
        return None
    momento = datos.get("solicitado_en")
    try:
        cuando = datetime.fromisoformat(str(momento))
    except (TypeError, ValueError):
        cuando = datetime.now(UTC)
    return SolicitudCiclo(
        solicitado_por=str(datos.get("solicitado_por") or "—"), solicitado_en=cuando
    )


async def solicitar_ciclo(
    actor: Actor, *, cache: Cache, ahora: datetime | None = None
) -> SolicitudCiclo:
    """Deja pedido un ciclo completo. Devuelve la petición, para poder decir quién y cuándo.

    Con la caché deshabilitada **no se finge**: se rechaza con un motivo. Aceptar la petición y
    perderla dejaría al administrador pulsando un botón que dice «hecho» mientras no pasa nada, que
    es la peor forma de fallar de las posibles.
    """
    _exigir_plataforma(actor)
    if not cache.habilitada:
        raise EstadoInvalido(
            "La caché está deshabilitada, así que el worker no puede recibir la petición. "
            "Actívala para poder ordenar un ciclo."
        )

    peticion = SolicitudCiclo(
        solicitado_por=str(actor.usuario_id), solicitado_en=ahora or datetime.now(UTC)
    )
    await cache.guardar(CLAVE_SOLICITUD, a_json(peticion.como_diccionario()), TTL_SOLICITUD_SEG)
    return peticion


async def solicitud_pendiente(cache: Cache) -> SolicitudCiclo | None:
    """La petición que está esperando, sin quitarla. Es lo que enseña la pantalla."""
    if not cache.habilitada:
        return None
    return _leer(await cache.obtener(CLAVE_SOLICITUD))


async def consumir_solicitud(cache: Cache) -> SolicitudCiclo | None:
    """La toma el worker: devuelve la petición y la borra, porque se atiende una vez.

    Se borra **siempre** que la clave exista, también cuando su contenido es ilegible: lo que hay en
    la caché lo escribió otro proceso, y un valor roto no se va a volver legible. Dejarlo sería
    preguntarlo en cada vuelta durante los quince minutos que dura.

    Se lee y se borra en dos pasos, y con dos réplicas del worker las dos podrían verla antes de que
    ninguna borre. No se paga nada por ello: el ciclo de la segunda encontraría el bloqueo de la
    fuente tomado y se saltaría la ingesta, así que lo único que pasa es que vuelve a mirar el
    listado y no escribe nada. Cambiar esto por un `GETDEL` obligaría a que el puerto de caché
    creciera para un caso que no rompe nada.
    """
    if not cache.habilitada:
        return None
    texto = await cache.obtener(CLAVE_SOLICITUD)
    if texto is None:
        return None
    await cache.eliminar(CLAVE_SOLICITUD)
    return _leer(texto)


async def tablero_ingesta(
    actor: Actor,
    *,
    repositorio: RepositorioConsultas,
    cache: Cache,
    ciclos: int = CICLOS_POR_FUENTE,
) -> dict[str, Any]:
    """Lo que dibuja la pantalla de plataforma: el último ciclo, la serie y la petición pendiente.

    El historial se agrupa por fuente aquí y no en el panel: quién alimenta a quién es una regla del
    sistema, y el panel no tiene por qué saber que un ciclo pertenece a `NCO` o a `OCDS` para poder
    pintarlo en dos series.
    """
    _exigir_plataforma(actor)
    fuentes = [dict(fila) for fila in await repositorio.estado_fuentes()]
    ciclos_crudos = [dict(fila) for fila in await repositorio.historial_sincronizaciones(ciclos)]
    pendiente = await solicitud_pendiente(cache)

    por_fuente: dict[str, list[dict[str, Any]]] = {}
    for ciclo in ciclos_crudos:
        por_fuente.setdefault(str(ciclo.pop("fuente")), []).append(ciclo)

    return {
        "fuentes": fuentes,
        "historial": por_fuente,
        "solicitud": pendiente.como_diccionario() if pendiente else None,
        "cadencia_seg": PASO_COMPROBACION_SEG,
    }
