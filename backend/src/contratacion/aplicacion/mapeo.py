"""Motor de mapeo: convierte el payload crudo de una fuente en campos canónicos.

El mapeo es **dirigido por datos**: las reglas viven en la tabla `campo_mapeo`, no en el código. Eso
permite añadir una columna nueva sin desplegar, que es lo que hace escalable el producto cuando la
fuente cambia.

Cuando aparece una clave que no tiene mapeo, el campo **no se descarta**: el payload íntegro se
guarda en `registro.crudo` y la clave se registra como pendiente para que alguien la mapee. Nada se
pierde por no entenderlo todavía.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

SALTO_HTML = re.compile(r"<\s*br\s*/?\s*>", re.IGNORECASE)
ETIQUETA_HTML = re.compile(r"<[^>]+>")
ESPACIOS = re.compile(r"\s+")
SIMBOLOS_NO_NUMERICOS = re.compile(r"[^\d.,+-]")
SOLO_NUMERO = re.compile(r"\d+(?:\.\d+)?")
MILES_CON_PUNTO = re.compile(r"^\d{1,3}(?:\.\d{3})+$")
MILES_CON_COMA = re.compile(r"^\d{1,3}(?:,\d{3})+$")

FORMATOS_FECHA = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y",
)


@dataclass(frozen=True)
class MapeoCampo:
    """Una regla de la tabla `campo_mapeo`."""

    clave_cruda: str
    campo_canonico: str
    tipo_dato: str
    transformacion: Mapping[str, Any]
    requerido: bool = False


def _texto(valor: Any) -> str:
    if valor is None:
        return ""
    return ESPACIOS.sub(" ", html.unescape(str(valor))).strip()


def html_a_texto(valor: Any) -> str:
    """Convierte HTML embebido en texto plano.

    La fuente entrega campos con `<br/>` y etiquetas dentro del valor; sin esto, el dato llega sucio
    al usuario y al Excel.
    """
    crudo = _texto(valor)
    if not crudo:
        return ""
    crudo = SALTO_HTML.sub(" | ", crudo)
    crudo = ETIQUETA_HTML.sub(" ", crudo)
    return ESPACIOS.sub(" ", crudo).strip(" |").strip()


def _fecha(valor: Any) -> str | None:
    """Devuelve la fecha en ISO 8601 o `None` si no se puede interpretar.

    Se admite el formato de la fuente y los habituales en español. Nada de inventar una fecha.

    El último intento es el ISO 8601 completo —con la `T` y el desfase horario—, y **no es un
    extra**: los datos abiertos publican así todas sus fechas («2026-04-24T13:47:17-05:00»). Sin
    esa rama, `convertir` devolvía `None`, y como un valor nulo se descarta en silencio, la fecha
    de publicación de **los 53 procesos de OCDS** no llegaba ni a la tabla ni al detalle. El
    síntoma era una columna de fecha vacía en la pantalla y el filtro «desde/hasta» sin efecto
    sobre esa fuente, sin un solo error en los registros que lo delatara.

    Va después de la lista y no antes a propósito: `fromisoformat` acepta también las formas que
    ya cubre la lista, así que ponerlo primero cambiaría cómo se interpretan las fechas que hoy
    funcionan. Las que pasan por la lista siguen pasando por la lista.
    """
    texto = _texto(valor)
    if not texto:
        return None
    for formato in FORMATOS_FECHA:
        try:
            return datetime.strptime(texto, formato).isoformat()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(texto).isoformat()
    except ValueError:
        return None


def _a_decimal(valor: Any) -> Decimal | None:
    """Interpreta un importe escrito por una persona.

    El formato local usa el punto para los miles y la coma para los decimales («1.234,56»), pero la
    fuente también publica a veces el formato inglés («1234.56»). Hay que distinguirlos: si se trata
    «1.234,56» como inglés, el monto sale mil veces más pequeño, y ese error llega al usuario y al
    Excel sin que nadie lo note.
    """
    limpio = SIMBOLOS_NO_NUMERICOS.sub("", _texto(valor))
    if not limpio:
        return None

    negativo = limpio.startswith("-")
    limpio = limpio.lstrip("+-")

    if "," in limpio and "." in limpio:
        # El último separador que aparece es el decimal; el otro agrupa los miles.
        if limpio.rfind(",") > limpio.rfind("."):
            limpio = limpio.replace(".", "").replace(",", ".")
        else:
            limpio = limpio.replace(",", "")
    elif "," in limpio:
        limpio = (
            limpio.replace(",", "") if MILES_CON_COMA.match(limpio) else limpio.replace(",", ".")
        )
    elif MILES_CON_PUNTO.match(limpio):
        limpio = limpio.replace(".", "")

    if not SOLO_NUMERO.fullmatch(limpio):
        return None
    try:
        numero = Decimal(limpio)
    except InvalidOperation:
        return None
    return -numero if negativo else numero


def _numero(valor: Any, *, entero: bool = False) -> float | int | None:
    numero = _a_decimal(valor)
    if numero is None:
        return None
    return int(numero) if entero else float(numero)


def _booleano(valor: Any) -> bool | None:
    texto = _texto(valor).lower()
    if texto in {"si", "sí", "true", "1", "yes"}:
        return True
    if texto in {"no", "false", "0"}:
        return False
    return None


def _lista(valor: Any, separador: str) -> list[str]:
    return [parte.strip() for parte in _texto(valor).split(separador) if parte.strip()]


def convertir(valor: Any, regla: MapeoCampo) -> Any:
    """Aplica la transformación declarada en la regla."""
    transformacion = dict(regla.transformacion or {})
    operacion = transformacion.get("operacion", regla.tipo_dato)

    if valor is None or _texto(valor) == "":
        return None

    if operacion == "html_a_texto":
        return html_a_texto(valor)
    if operacion in {"fecha", "fecha_hora"}:
        return _fecha(valor)
    if operacion == "entero":
        return _numero(valor, entero=True)
    if operacion in {"numero", "moneda"}:
        return _numero(valor)
    if operacion == "booleano":
        return _booleano(valor)
    if operacion == "separar_por":
        return _lista(valor, str(transformacion.get("separador", ",")))
    if operacion == "regex":
        # Extrae un fragmento, pero si el patrón no coincide devuelve el texto original: perder el
        # dato por un cambio de formato en la fuente sería peor que traerlo sin limpiar.
        patron = str(transformacion.get("patron", ""))
        if not patron:
            return _texto(valor)
        coincidencia = re.search(patron, _texto(valor))
        if coincidencia is None:
            return _texto(valor)
        return coincidencia.group(1) if coincidencia.groups() else coincidencia.group()
    return _texto(valor)


def aplicar(
    mapeos: Iterable[MapeoCampo], crudo: Mapping[str, Any]
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Devuelve `(datos canónicos, claves sin mapear)`.

    Las claves sin mapear se devuelven para registrarlas como pendientes: es el mecanismo que avisa
    de que la fuente ha cambiado sin que nos enteremos.

    Las claves que empiezan por `_` se ignoran: son marcas internas que añaden los adaptadores (por
    ejemplo, el término por el que entró un registro) y no forman parte del payload de la fuente.
    """
    por_clave = {mapeo.clave_cruda: mapeo for mapeo in mapeos}
    datos: dict[str, Any] = {}
    sin_mapear: list[str] = []

    for clave, valor in crudo.items():
        if clave.startswith("_"):
            continue
        mapeo = por_clave.get(clave)
        if mapeo is None:
            sin_mapear.append(clave)
            continue
        convertido = convertir(valor, mapeo)
        if convertido is not None or mapeo.requerido:
            datos[mapeo.campo_canonico] = convertido

    return datos, tuple(sorted(sin_mapear))


def campos_requeridos_ausentes(
    mapeos: Sequence[MapeoCampo], crudo: Mapping[str, Any]
) -> tuple[str, ...]:
    """Claves marcadas como requeridas que no vienen en el payload.

    Sirve para detectar que la fuente dejó de publicar algo que el producto necesita.
    """
    return tuple(
        mapeo.clave_cruda
        for mapeo in mapeos
        if mapeo.requerido and _texto(crudo.get(mapeo.clave_cruda)) == ""
    )
