"""Reglas de la ingesta incremental.

Todo lo que decide si un registro es nuevo, cambió o sigue igual vive aquí, sin depender de la base
de datos, de HTTP ni de Redis. Así se puede probar sin levantar nada.

El principio que gobierna el diseño: **el payload original nunca se pierde**. Si la fuente añade un
campo que no conocemos, se guarda igualmente en el crudo y se registra para que alguien lo mapee.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

# Las fuentes publican hora local de Ecuador sin indicar zona. El continente no tiene horario de
# verano, así que la zona es estable; Galápagos va una hora por detrás y queda anotado como
# limitación conocida.
ZONA_FUENTE = ZoneInfo("America/Guayaquil")

# Días que se recuperan hacia atrás la primera vez que se busca un término.
#
# Es la cifra que decide si un cliente que agrega una palabra clave nueva ve las contrataciones
# publicadas **antes** de suscribirse. Si se dejara en el solape de dos ciclos, todo lo anterior a
# la suscripción sería irrecuperable, y el producto perdería justo aquello por lo que se paga.
DIAS_VENTANA_INICIAL = 90


class Clasificacion(StrEnum):
    """Qué ha pasado con un registro respecto a lo que ya había."""

    NUEVO = "nuevo"
    ACTUALIZADO = "actualizado"
    IGUAL = "igual"


# Campos que **no cuentan como contenido** aunque viajen en `datos`, porque la fuente los
# regenera en cada respuesta.
#
# `enlace` es el caso medido (2026-10-01): la URL de la ficha lleva un token opaco que cambia
# en cada listado —la misma necesidad apareció con cuatro tokens distintos en cuatro versiones
# consecutivas, con todo lo demás idéntico—. Sin excluirlo, cada ciclo clasificaba las 1.700
# necesidades como «actualizadas»: las reescribía todas, subía la generación del caché y les
# añadía una versión al histórico. El resultado eran 9.536 versiones para 2.873 registros, con
# el historial —que es el activo comercial— convertido en ruido. Con una lectura cada tres
# minutos serían cientos de miles de filas al día.
#
# El valor **se sigue guardando**: el token que se almacena es el último, que es el que abre la
# ficha. Lo único que cambia es que su rotación no se interpreta como un cambio de datos.
CAMPOS_VOLATILES: frozenset[str] = frozenset({"enlace"})


def clave_natural(fuente: str, partes: list[str]) -> str:
    """Clave estable de un registro dentro de una fuente.

    Se compone de los identificadores propios de la fuente (el `ocid` en OCDS, el identificador de
    la necesidad en NCO). Es lo que permite actualizar en lugar de duplicar.
    """
    limpias = [parte.strip() for parte in partes if parte and parte.strip()]
    if not limpias:
        raise ValueError(f"La fuente {fuente!r} no aportó ningún identificador para el registro.")
    return "|".join(limpias)


def hash_contenido(datos: Mapping[str, Any]) -> str:
    """Huella del contenido canónico.

    Se calcula sobre las claves ordenadas, de modo que el mismo contenido produzca siempre la misma
    huella aunque la fuente cambie el orden de los campos. Es lo que permite detectar cambios reales
    y no ruido.

    Los campos de `CAMPOS_VOLATILES` se dejan fuera: son cosas que la fuente reescribe sola y que no
    significan que el registro haya cambiado.
    """
    canonico = {clave: valor for clave, valor in datos.items() if clave not in CAMPOS_VOLATILES}
    serializado = json.dumps(canonico, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(serializado.encode("utf-8")).hexdigest()


def clasificar(hash_previo: str | None, hash_nuevo: str) -> Clasificacion:
    """Compara la huella previa con la nueva."""
    if hash_previo is None:
        return Clasificacion.NUEVO
    if hash_previo != hash_nuevo:
        return Clasificacion.ACTUALIZADO
    return Clasificacion.IGUAL


def ventana_desde(
    ultima_correcta: datetime | None,
    intervalo_min: int,
    ciclos_de_solape: int,
    ahora: datetime,
    dias_iniciales: int = DIAS_VENTANA_INICIAL,
) -> datetime:
    """Desde cuándo hay que releer para no perder registros entre ciclos.

    Sin solape, un registro publicado justo entre dos ejecuciones se perdería para siempre. La
    ventana relee los últimos `ciclos_de_solape x intervalo` minutos; como el `upsert` por huella es
    idempotente, releer de más no cuesta datos duplicados.

    Si no hay una ejecución correcta previa (primer arranque o tras un fallo), se devuelve la
    ventana inicial, que es amplia a propósito: **es lo que evita perder las contrataciones
    publicadas antes de que alguien se suscribiera**. Si aquí se devolviera solo el solape, todo lo
    anterior a la suscripción sería irrecuperable.
    """
    solape = timedelta(minutes=intervalo_min * ciclos_de_solape)
    if ultima_correcta is None:
        return ahora - timedelta(days=dias_iniciales)
    return min(ultima_correcta, ahora) - solape


def ventana_de_cola(
    ultimas: Sequence[datetime | None],
    intervalo_min: int,
    ciclos_de_solape: int,
    ahora: datetime,
    dias_iniciales: int = DIAS_VENTANA_INICIAL,
) -> datetime:
    """Desde cuándo leer para un lote de términos.

    Se toma la ventana **más amplia** de todas las del lote: basta con que un solo término nunca se
    haya ingestado para que el lote entero se lea desde la ventana inicial. Es deliberadamente
    conservador y hay una razón: perder contrataciones es irreversible, mientras que releer datos ya
    vistos solo cuesta peticiones, y el presupuesto acota ese coste.

    Un lote vacío se trata como «todo nuevo»: es el primer arranque y no hay nada de lo que fiarse.
    """
    candidatas = list(ultimas) or [None]
    return min(
        ventana_desde(ultima, intervalo_min, ciclos_de_solape, ahora, dias_iniciales)
        for ultima in candidatas
    )


def fecha_a_utc(valor: str | None) -> datetime | None:
    """Interpreta una fecha publicada en la zona de la fuente y la convierte a UTC.

    Guardarla como si ya fuera UTC desplazaría cada registro cinco horas, y los filtros por rango de
    fechas devolverían resultados equivocados. Si la fecha no se puede interpretar, se devuelve
    `None`: es preferible un hueco visible a una fecha falsa.
    """
    if not valor:
        return None
    try:
        momento = datetime.fromisoformat(valor)
    except ValueError:
        return None
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=ZONA_FUENTE)
    return momento.astimezone(UTC)


@dataclass
class Presupuesto:
    """Tope de peticiones a la fuente oficial por ciclo.

    Existe porque la fuente limita la tasa y porque un ciclo que se pasa de tiempo impide que el
    siguiente empiece a su hora. Es preferible terminar el ciclo de forma parcial y avisar, que
    agotar la cuota y dejar el servicio bloqueado.
    """

    limite: int
    usadas: int = 0

    def agotado(self) -> bool:
        return self.usadas >= self.limite

    def consumir(self) -> bool:
        """Registra una petición. Devuelve `False` si ya no queda presupuesto."""
        if self.agotado():
            return False
        self.usadas += 1
        return True

    @property
    def restantes(self) -> int:
        return max(0, self.limite - self.usadas)


@dataclass
class ContadoresCiclo:
    """Resultado numérico de un ciclo, para registrarlo y poder auditar la ingesta."""

    nuevos: int = 0
    actualizados: int = 0
    iguales: int = 0
    sin_mapear: int = 0
    errores: int = 0
    avisos: list[str] = field(default_factory=list)

    def avisar(self, mensaje: str) -> None:
        if mensaje not in self.avisos:
            self.avisos.append(mensaje)

    @property
    def procesados(self) -> int:
        return self.nuevos + self.actualizados + self.iguales
