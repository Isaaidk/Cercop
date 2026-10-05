"""Caso de uso: agregar una palabra clave y encolar su ingesta.

Es CU-04, el caso que hace que el producto se sienta vivo sin poner en riesgo la fuente oficial.

La regla que lo gobierna todo: **este caso de uso no llama nunca a la fuente**. Responde de
inmediato con lo que ya hay y encola el término para que el `worker` lo atienda respetando el
presupuesto y el límite de tasa (R-01, R-02). Si aquí se consultara el SERCOP, un usuario con prisa
podría provocar el bloqueo de la IP del servicio y dejar sin datos a todos los negocios.

La deduplicación es global y no por negocio: el término es único en el catálogo, así que diez
negocios pidiendo «obras viales» producen una sola consulta a la fuente.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.puertos.terminos import RepositorioTerminos
from contratacion.dominio.errores import DatoInvalido, NoEncontrado
from contratacion.dominio.palabras import LONGITUD_MINIMA_TERMINO, normalizar_termino

registro = logging.getLogger(__name__)

AVISO_EN_COLA = (
    "El término se agregó a la cola de ingesta. Los resultados actuales pueden estar incompletos "
    "hasta que el próximo ciclo consulte la fuente oficial."
)
AVISO_RECIENTE = "El término ya se consultó hace poco; los resultados al día."


@dataclass(frozen=True, slots=True)
class ResultadoAltaTermino:
    """Respuesta inmediata al usuario que acaba de agregar una palabra clave."""

    termino: str
    termino_id: UUID
    suscripcion_nueva: bool
    en_cola: bool
    ultima_ingesta: datetime | None
    suscriptores: int
    avisos: tuple[str, ...]

    def como_diccionario(self) -> dict[str, Any]:
        return {
            "termino": self.termino,
            "termino_id": str(self.termino_id),
            "suscripcion_nueva": self.suscripcion_nueva,
            "estado_ingesta": "en_cola" if self.en_cola else "al_dia",
            "en_cola": self.en_cola,
            "ultima_ingesta": self.ultima_ingesta.isoformat() if self.ultima_ingesta else None,
            "suscriptores": self.suscriptores,
            "avisos": list(self.avisos),
        }


@dataclass(frozen=True, slots=True)
class ResultadoAltaTerminos:
    """Respuesta al alta de varias palabras clave de una vez."""

    terminos: tuple[str, ...]
    nuevas: int

    def como_diccionario(self) -> dict[str, Any]:
        return {
            "terminos": list(self.terminos),
            "nuevas": self.nuevas,
            "total": len(self.terminos),
        }


@dataclass(frozen=True, slots=True)
class EstadoTermino:
    """Estado de ingesta de un término, para que el panel pueda refrescar por su cuenta."""

    termino_id: UUID
    texto: str
    ultima_ingesta: datetime | None
    en_cola: bool
    suscriptores: int
    activo: bool

    def como_diccionario(self) -> dict[str, Any]:
        return {
            "termino_id": str(self.termino_id),
            "texto": self.texto,
            "ultima_ingesta": self.ultima_ingesta.isoformat() if self.ultima_ingesta else None,
            "estado_ingesta": "en_cola" if self.en_cola else "al_dia",
            "en_cola": self.en_cola,
            "suscriptores": self.suscriptores,
            "activo": self.activo,
        }


def limpiar_termino(texto: str | None) -> str:
    """Forma presentable del término, con la validación de longitud aplicada.

    Se rechazan los términos cortos porque la fuente oficial los rechaza y porque cada intento
    consume cuota del presupuesto: aceptarlos sería gastar en algo que no puede devolver nada.
    """
    colapsado = " ".join((texto or "").split())
    if len(normalizar_termino(colapsado)) < LONGITUD_MINIMA_TERMINO:
        raise DatoInvalido(
            f"El término debe tener al menos {LONGITUD_MINIMA_TERMINO} caracteres útiles."
        )
    return colapsado


async def agregar_termino(
    texto: str | None,
    *,
    actor: Actor,
    repositorio: RepositorioTerminos,
    intervalo_min: int,
    maximo_terminos: int,
    momento: datetime | None = None,
) -> ResultadoAltaTermino:
    """Suscribe el negocio a un término y lo deja listo para el próximo ciclo.

    Devuelve **de inmediato**: el usuario ve sus resultados parciales y el panel consulta el estado
    después. Esperar aquí significaría que una consulta a la fuente oficial ocurre dentro de una
    petición de usuario, que es justo lo que la restricción R-01 prohíbe.
    """
    instante = momento or datetime.now(UTC)
    limpio = limpiar_termino(texto)

    # Una sola llamada y una sola transacción: el repositorio crea el término, comprueba el tope,
    # suscribe y devuelve el estado. La alternativa —enumerar aquí, crear allí, suscribir después—
    # obligaba a cinco viajes a la base y dejaba el tope de palabras a merced de que dos peticiones
    # del mismo negocio no coincidieran en el tiempo.
    alta = await repositorio.alta_de_termino(
        actor.negocio_id,
        texto=limpio,
        maximo_terminos=maximo_terminos,
    )
    ultima = _fecha(alta, "ultima_ingesta_en")

    en_cola = ultima is None or (instante - ultima) > timedelta(minutes=intervalo_min)
    aviso = AVISO_EN_COLA if en_cola else AVISO_RECIENTE
    identificador = _identificador(alta)
    if identificador is None:
        raise NoEncontrado("El término se guardó pero la base no devolvió su identificador.")

    return ResultadoAltaTermino(
        termino=limpio,
        termino_id=identificador,
        suscripcion_nueva=bool(alta.get("suscripcion_nueva", True)),
        en_cola=en_cola,
        ultima_ingesta=ultima,
        suscriptores=int(alta.get("suscriptores") or 0),
        avisos=(aviso,),
    )


async def agregar_terminos(
    textos: Sequence[str],
    *,
    actor: Actor,
    repositorio: RepositorioTerminos,
    maximo_terminos: int,
) -> ResultadoAltaTerminos:
    """Suscribe el negocio a **varias** palabras clave de una vez (CU-04, en bloque).

    No consulta la fuente: igual que el alta de una sola, deja los términos en la cola y responde
    con lo que ya hay. La diferencia es la forma de la entrada —puede ser una columna entera
    copiada de una hoja de cálculo— y por eso la validación **descarta lo inservible sin abortar el
    resto**:
    perder treinta y cuatro palabras buenas porque una tiene dos letras sería un mal trueque.

    Lo que sí aborta el lote entero es pasarse del tope. Dejar la mitad aplicada y la otra mitad no
    sería peor que no hacer nada: el usuario no sabría qué quedó guardado.
    """
    limpios: list[str] = []
    for texto in textos:
        try:
            limpios.append(limpiar_termino(texto))
        except DatoInvalido:
            continue

    if not limpios:
        raise DatoInvalido(
            f"Ninguna de las palabras tiene al menos {LONGITUD_MINIMA_TERMINO} caracteres útiles."
        )

    filas = await repositorio.alta_de_terminos(
        actor.negocio_id,
        textos=limpios,
        maximo_terminos=maximo_terminos,
    )
    return ResultadoAltaTerminos(
        terminos=tuple(str(fila.get("texto", "")) for fila in filas if fila.get("texto")),
        nuevas=sum(1 for fila in filas if fila.get("suscripcion_nueva")),
    )


async def consultar_estado(
    termino_id: UUID,
    *,
    repositorio: RepositorioTerminos,
    intervalo_min: int,
    momento: datetime | None = None,
) -> EstadoTermino:
    """Estado de ingesta de un término, para que el panel refresque sin volver a agregarlo."""
    instante = momento or datetime.now(UTC)
    estado = await repositorio.estado_termino(termino_id)
    if estado is None:
        raise NoEncontrado("Ese término no existe en el catálogo.")

    ultima = _fecha(estado, "ultima_ingesta_en")
    return EstadoTermino(
        termino_id=termino_id,
        texto=str(estado.get("texto", "")),
        ultima_ingesta=ultima,
        en_cola=ultima is None or (instante - ultima) > timedelta(minutes=intervalo_min),
        suscriptores=await repositorio.suscriptores(termino_id),
        activo=bool(estado.get("activo", True)),
    )


async def listar_terminos(
    actor: Actor,
    *,
    repositorio: RepositorioTerminos,
    intervalo_min: int,
    momento: datetime | None = None,
) -> tuple[EstadoTermino, ...]:
    """Palabras clave a las que está suscrito el negocio, con su estado de ingesta.

    Faltaba: existía la forma de **agregar** una palabra clave y de consultar el estado de una
    concreta, pero no la de saber cuáles hay. Sin esto, el panel no puede pintar los filtros de un
    negocio que vuelve al día siguiente: tendría que adivinar sus propios términos o guardarlos en
    el navegador, y bastaría con cambiar de equipo para perder los filtros.

    El estado de ingesta se calcula con el mismo criterio que el de un término suelto —«en cola» si
    nunca se consultó o si ha pasado más de un ciclo— para que un listado y una consulta individual
    no puedan dar respuestas distintas sobre lo mismo.
    """
    instante = momento or datetime.now(UTC)
    suscritos = await repositorio.terminos_del_negocio(actor.negocio_id)

    # Los suscriptores se piden **una vez para todos**, no uno por término dentro del bucle. Con
    # cuarenta palabras clave y la base al otro lado de la red, la versión con una consulta por
    # término tardaba segundos en pintar la lista —lo medido: 16,7 s— y no fallaba nada, así que
    # parecía que el panel se había colgado.
    suscriptores = await repositorio.suscriptores_de(
        [identificador for fila in suscritos if (identificador := _identificador(fila)) is not None]
    )

    resultado: list[EstadoTermino] = []
    for fila in suscritos:
        termino_id = _identificador(fila)
        if termino_id is None:
            continue
        ultima = _fecha(fila, "ultima_ingesta_en")
        resultado.append(
            EstadoTermino(
                termino_id=termino_id,
                texto=str(fila.get("texto", "")),
                ultima_ingesta=ultima,
                en_cola=ultima is None or (instante - ultima) > timedelta(minutes=intervalo_min),
                # Un término sin entrada en el mapa no tiene suscriptores: la ausencia es un cero,
                # no un dato que falte.
                suscriptores=suscriptores.get(termino_id, 0),
                activo=bool(fila.get("activo", True)),
            )
        )
    return tuple(resultado)


def _identificador(fila: Any) -> UUID | None:
    """Extrae el identificador del término de una fila del catálogo.

    Se aceptan las dos formas habituales (`termino_id` en un listado con suscripción, `id` en el
    término suelto) para que el caso de uso no dependa de qué consulta concreta lo alimentó.
    """
    if not isinstance(fila, Mapping):
        return None
    valor = fila.get("termino_id") or fila.get("id")
    if valor is None:
        return None
    return valor if isinstance(valor, UUID) else UUID(str(valor))


def _fecha(fila: Any, campo: str) -> datetime | None:
    """Lee una fecha de una fila, aceptando texto ISO por si viene de un doble de prueba."""
    if not isinstance(fila, Mapping):
        return None
    valor = fila.get(campo)
    if valor is None or isinstance(valor, datetime):
        return valor
    try:
        return datetime.fromisoformat(str(valor))
    except ValueError:
        return None
