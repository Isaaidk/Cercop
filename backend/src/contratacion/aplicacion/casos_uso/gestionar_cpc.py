"""Casos de uso: la lista de términos de CPC que una empresa vigila.

Es la parte que faltaba para que el filtro por CPC sirviera de algo en el trabajo diario: sin
guardar la lista, cada persona la escribe al entrar y se pierde al recargar, así que el equipo no
puede mirar lo mismo.

Dos decisiones que conviene tener presentes al leerlo.

**Quien puede cambiarla es cualquier usuario del negocio**, igual que con las palabras clave y a
diferencia de la selección de columnas del Excel, que exige rol administrativo. La lista es una
ayuda para buscar, no la configuración de lo que la empresa entrega a un tercero: restringirla haría
que quien detecta una clasificación útil tuviera que pedir permiso para apuntarla.

**El servidor aplica la misma regla que la pantalla.** Se aceptan los mismos separadores —comas,
punto y coma y saltos de línea— porque la lista se pega desde una hoja de cálculo, y los términos
de menos de tres letras se descartan **contándose**: el panel enseña cuántos entran antes de
pulsar, y un contador que no cuadre con lo guardado es peor que no tenerlo.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.puertos.cpc import RepositorioCpc
from contratacion.dominio.palabras import (
    LONGITUD_MINIMA_TERMINO,
    SEPARADOR_TERMINOS,
    normalizar_termino,
)

registro = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ResultadoAltaCpc:
    """Lo que pasó al añadir términos: qué entró y qué se quedó fuera, por qué."""

    agregadas: tuple[str, ...]
    repetidas: int
    cortas: int

    def como_diccionario(self) -> dict[str, Any]:
        return {
            "claves": list(self.agregadas),
            "agregadas": len(self.agregadas),
            "repetidas": self.repetidas,
            "cortas": self.cortas,
        }


def _partir(textos: Sequence[str]) -> tuple[list[str], int]:
    """Separa la entrada en términos válidos y cuenta los que se descartan por cortos.

    Se parte por los mismos separadores que la pantalla y se aplica el mismo mínimo, que no es
    capricho: la fuente oficial rechaza las búsquedas de menos de tres caracteres, y un término que
    no se puede buscar es una ficha que no filtra nada.
    """
    partes: list[str] = []
    for entrada in textos:
        for trozo in SEPARADOR_TERMINOS.split(str(entrada or "")):
            limpio = trozo.strip()
            if limpio:
                partes.append(limpio)

    validas = [parte for parte in partes if len(parte) >= LONGITUD_MINIMA_TERMINO]
    return validas, len(partes) - len(validas)


async def listar(actor: Actor, *, repositorio: RepositorioCpc) -> tuple[str, ...]:
    """Los términos guardados por la empresa, en orden de alta."""
    claves = await repositorio.listar(negocio_id=actor.negocio_id)
    return tuple(clave.texto for clave in claves)


async def agregar(
    actor: Actor,
    *,
    textos: Sequence[str],
    repositorio: RepositorioCpc,
    momento: datetime | None = None,
) -> ResultadoAltaCpc:
    """Añade los términos que no estuvieran ya. Devuelve qué entró y qué no.

    La deduplicación es **por negocio**: dos empresas pueden vigilar el mismo código y cada una lo
    puede quitar sin tocar la lista de la otra.
    """
    momento = momento or datetime.now(UTC)
    candidatos, cortas = _partir(textos)

    agregadas: list[str] = []
    repetidas = 0
    vistas: set[str] = set()
    for candidato in candidatos:
        normalizado = normalizar_termino(candidato)
        # `vistas` cubre las repeticiones **dentro** de la propia petición, que es lo que pasa al
        # pegar una lista con el mismo término dos veces; la base cubre las que ya estaban.
        if normalizado in vistas:
            repetidas += 1
            continue
        vistas.add(normalizado)

        insertada = await repositorio.agregar(
            negocio_id=actor.negocio_id,
            texto=candidato,
            texto_normalizado=normalizado,
            creado_por=actor.usuario_id,
            momento=momento,
        )
        if insertada:
            agregadas.append(candidato)
        else:
            repetidas += 1

    if agregadas or repetidas or cortas:
        registro.info(
            "CPC de %s: %s agregadas, %s repetidas, %s cortas",
            actor.negocio_id,
            len(agregadas),
            repetidas,
            cortas,
        )
    return ResultadoAltaCpc(agregadas=tuple(agregadas), repetidas=repetidas, cortas=cortas)


async def quitar(actor: Actor, *, texto: str, repositorio: RepositorioCpc) -> bool:
    """Quita un término de la lista. `False` si no estaba."""
    return await repositorio.quitar(
        negocio_id=actor.negocio_id, texto_normalizado=normalizar_termino(texto)
    )


async def limpiar(actor: Actor, *, repositorio: RepositorioCpc) -> int:
    """Vacía la lista. Devuelve cuántos términos había."""
    return await repositorio.limpiar(negocio_id=actor.negocio_id)
