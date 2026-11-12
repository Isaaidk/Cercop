"""Qué anexos de un proceso sirven para armar la proforma, y cuáles se descartan.

El cliente lo dijo así: «TDR, pliegos y actas son los importantes para elaborar las proformas;
de las actas, solo la más reciente, no todas». Un proceso puede publicar diez actas (preguntas,
aclaraciones, apertura…) y cada una corrige a la anterior: la que vale es la última.

La regla vive aquí, en el dominio, para que la usen igual las ínfimas (ficha del portal, que da
nombre y enlace sin fecha) y los procesos de OCDS (que traen `datePublished`). Es pura: no baja
nada, solo clasifica y elige.

Cómo se decide qué acta es la más reciente, en este orden:
1. la fecha publicada del documento (`fecha`, ISO), si la trae;
2. una fecha escrita en el nombre («Acta 2026-03-14», «acta_14-03-2026»);
3. el número más alto en el nombre («Acta 3» frente a «Acta 2»);
4. la última en el orden en que la fuente las publicó (el portal las lista por fecha de subida).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any

TDR = "tdr"
PLIEGO = "pliego"
ACTA = "acta"
ESPECIFICACIONES = "especificaciones"
OTRO = "otro"

# Orden en que se muestran y se leen: primero lo que define qué se compra.
PRIORIDAD = {TDR: 0, PLIEGO: 1, ESPECIFICACIONES: 2, ACTA: 3, OTRO: 4}

ETIQUETAS = {
    TDR: "Términos de referencia (TDR)",
    PLIEGO: "Pliego",
    ESPECIFICACIONES: "Especificaciones técnicas",
    ACTA: "Acta más reciente",
    OTRO: "Otro anexo",
}

_REGLAS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (ACTA, re.compile(r"\bacta\b|\bactas\b|aclaraci|preguntas y respuestas|\bapertura\b")),
    (TDR, re.compile(r"\btdr\b|terminos? de referencia|t\.d\.r")),
    (PLIEGO, re.compile(r"\bpliegos?\b")),
    (ESPECIFICACIONES, re.compile(r"especificaciones|ficha tecnica|\beett?\b|\betp?\b")),
)

_FECHA_ISO = re.compile(r"(20\d{2})[-_./](\d{1,2})[-_./](\d{1,2})")
_FECHA_LATINA = re.compile(r"(\d{1,2})[-_./](\d{1,2})[-_./](20\d{2})")
_NUMERO = re.compile(r"(\d{1,4})")


def _plano(texto: str) -> str:
    base = unicodedata.normalize("NFKD", str(texto or ""))
    sin_tilde = "".join(c for c in base if not unicodedata.combining(c))
    return " ".join(re.sub(r"[_\-]+", " ", sin_tilde.lower()).split())


def clasificar(nombre: str, tipo_fuente: str = "") -> str:
    """El tipo de anexo por su nombre (y por el tipo que declare la fuente, si lo trae)."""
    texto = _plano(f"{nombre} {tipo_fuente}")
    for tipo, patron in _REGLAS:
        if patron.search(texto):
            return tipo
    # OCDS nombra así el pliego y los términos técnicos.
    if "biddingdocuments" in texto.replace(" ", "") or "tenderNotice".lower() in texto:
        return PLIEGO
    if "technicalspecifications" in texto.replace(" ", ""):
        return ESPECIFICACIONES
    # OCDS publica las actas de preguntas y aclaraciones como `clarifications`.
    if "clarifications" in texto.replace(" ", ""):
        return ACTA
    return OTRO


def _fecha_del_nombre(nombre: str) -> date | None:
    for patron, orden in ((_FECHA_ISO, (0, 1, 2)), (_FECHA_LATINA, (2, 1, 0))):
        hallada = patron.search(nombre)
        if hallada:
            partes = [int(hallada.group(i + 1)) for i in range(3)]
            anio, mes, dia = (partes[orden[0]], partes[orden[1]], partes[orden[2]])
            try:
                return date(anio, mes, dia)
            except ValueError:
                continue
    return None


def _clave_de_reciente(posicion: int, documento: Mapping[str, Any]) -> tuple[Any, ...]:
    """Más grande = más reciente. Ver el orden de criterios en el docstring del módulo."""
    nombre = str(documento.get("nombre") or "")
    publicada = str(documento.get("fecha") or "")[:10]
    del_nombre = _fecha_del_nombre(nombre)
    numeros = [int(n) for n in _NUMERO.findall(_FECHA_ISO.sub("", _FECHA_LATINA.sub("", nombre)))]
    return (
        publicada or "",
        del_nombre.isoformat() if del_nombre else "",
        max(numeros) if numeros else -1,
        posicion,
    )


def elegir_anexos(documentos: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Los anexos útiles para la proforma, ordenados, con **una sola** acta: la más reciente.

    Cada documento conserva sus campos y gana `tipo` y `etiqueta_tipo`. Los de tipo «otro» se
    conservan al final (pueden ser formularios o anexos que la entidad exige), pero las actas
    anteriores a la última se quitan.
    """
    lista = [dict(documento) for documento in documentos]
    for documento in lista:
        documento["tipo"] = clasificar(
            str(documento.get("nombre") or ""), str(documento.get("tipo_fuente") or "")
        )
        documento["etiqueta_tipo"] = ETIQUETAS[documento["tipo"]]

    actas = [(n, d) for n, d in enumerate(lista) if d["tipo"] == ACTA]
    ultima = max(actas, key=lambda par: _clave_de_reciente(*par))[1] if actas else None

    elegidos = [d for d in lista if d["tipo"] != ACTA or d is ultima]
    return sorted(elegidos, key=lambda d: (PRIORIDAD[d["tipo"]], lista.index(d)))


def fecha_de(documento: Mapping[str, Any]) -> date | None:
    """La fecha del anexo: la publicada si la trae, si no la escrita en el nombre."""
    publicada = str(documento.get("fecha") or "")[:10]
    try:
        return date.fromisoformat(publicada)
    except ValueError:
        return _fecha_del_nombre(str(documento.get("nombre") or ""))


def marca_de_acta(documento: Mapping[str, Any]) -> str:
    """«Según acta del 14/03/2026», o sin fecha si no se conoce. Precede a lo que el acta cambió."""
    fecha = fecha_de(documento)
    return f"Según acta del {fecha:%d/%m/%Y}" if fecha else "Según el acta más reciente"


# Lo que un acta de preguntas y aclaraciones suele corregir. Si el acta trae uno de estos apartados
# con otro texto, manda el acta: es posterior al TDR y la entidad la publica para cambiarlo.
CAMBIOS_DE_ACTA = (
    "presupuesto",
    "plazos",
    "plazo_entrega",
    "cantidad",
    "forma_pago",
    "lugar_entrega",
    "garantia",
    "vigencia_proforma",
    "especificaciones",
)


def _igual(uno: str, otro: str) -> bool:
    return _plano(uno).strip(" .") == _plano(otro).strip(" .")


def combinar_secciones(
    partes: Iterable[tuple[Mapping[str, Any], Mapping[str, str]]],
) -> tuple[dict[str, str], list[str]]:
    """Une los apartados leídos de varios anexos en uno solo, y dice qué cambió el acta.

    `partes` son pares (anexo con su `tipo`, apartados leídos), en el orden en que deben mandar:
    el primero que trae un apartado se queda con él. El acta es la excepción: lo que corrige
    (`CAMBIOS_DE_ACTA`) pisa al TDR y se marca «Según acta del …» para que se sepa de dónde sale.
    Lo demás del acta solo rellena huecos. Devuelve los apartados y las claves que tomó del acta.
    """
    combinadas: dict[str, str] = {}
    actas: list[tuple[Mapping[str, Any], Mapping[str, str]]] = []
    for anexo, secciones in partes:
        if anexo.get("tipo") == ACTA:
            actas.append((anexo, secciones))
            continue
        for clave, texto in secciones.items():
            if texto:
                combinadas.setdefault(clave, texto)
    cambios: list[str] = []
    for anexo, secciones in actas[-1:]:
        marca = marca_de_acta(anexo)
        for clave, texto in secciones.items():
            if not texto:
                continue
            previo = combinadas.get(clave)
            if clave in CAMBIOS_DE_ACTA and not (previo and _igual(previo, texto)):
                combinadas[clave] = f"{marca}: {texto}"
                cambios.append(clave)
            else:
                combinadas.setdefault(clave, texto)
    return combinadas, cambios


# Clave de la lectura donde va el texto de todos los anexos. No es un apartado del TDR: el panel lo
# enseña plegado y la IA lo recibe como contexto para redactar la proforma.
CONTEXTO = "contexto_anexos"
TOPE_CONTEXTO_ARCHIVO = 6000
TOPE_CONTEXTO = 24000


def recorte_de_contexto(texto: str, tope: int = TOPE_CONTEXTO_ARCHIVO) -> str:
    """El texto de un anexo sin líneas vacías ni espacios de más, cortado al final de una línea."""
    lineas = [" ".join(linea.split()) for linea in str(texto or "").splitlines()]
    limpio = "\n".join(linea for linea in lineas if linea)
    if len(limpio) <= tope:
        return limpio
    corte = limpio.rfind("\n", 0, tope)
    return limpio[: corte if corte > tope // 2 else tope].rstrip() + "\n[…]"


def contexto_de_anexos(partes: Iterable[tuple[Mapping[str, Any], str]]) -> str:
    """El texto de **todos** los anexos leídos, cada uno con su tipo y nombre, en orden de lectura.

    Los apartados titulados (objeto, plazos, requisitos…) solo cubren lo que el TDR trae con
    título; el resto —formularios, tablas de ítems, anexos sin títulos, el membrete— se perdía.
    Aquí va todo, con tope por archivo y en total para que la lectura y el mensaje a la IA no
    crezcan sin fin.
    """
    bloques: list[str] = []
    usado = 0
    for anexo, texto in partes:
        cuerpo = recorte_de_contexto(texto)
        if not cuerpo:
            continue
        etiqueta = str(anexo.get("etiqueta_tipo") or ETIQUETAS.get(str(anexo.get("tipo")), "Anexo"))
        nombre = str(anexo.get("nombre_visible") or anexo.get("nombre") or "").strip()
        bloque = f"### {etiqueta}{f': {nombre}' if nombre else ''}\n{cuerpo}"
        if usado + len(bloque) > TOPE_CONTEXTO:
            libre = TOPE_CONTEXTO - usado
            if libre < 400:
                break
            bloque = bloque[:libre].rstrip() + "\n[…]"
        bloques.append(bloque)
        usado += len(bloque) + 2
    return "\n\n".join(bloques)


def principal(documentos: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    """El anexo que se lee primero para la proforma: TDR, si no pliego, si no especificaciones."""
    for documento in elegir_anexos(documentos):
        if documento["tipo"] in (TDR, PLIEGO, ESPECIFICACIONES):
            return documento
    return None
