"""Datos de la entidad contratante sacados del texto de sus anexos (TDR, pliego, acta).

La ficha del portal casi nunca publica la dirección ni el teléfono de la entidad, y si el TDR se
sube a mano tampoco hay código del proceso del que sacar el RUC. Pero el propio TDR los trae: en el
membrete, en el pie o en la cláusula del administrador del contrato. Con esto la proforma deja de
salir con «RUC», «Dirección» y «Teléfono» vacíos.

Reglas, pensadas para no confundir a la entidad con el proveedor:

- **RUC**: un número de 13 dígitos con forma de RUC. Se prefiere el de una entidad pública (tercer
  dígito 6) y el que va junto a la palabra RUC; se descarta el que aparece en una frase sobre el
  proveedor, el contratista o el oferente («con RUC …… certifica»).
- **Teléfono**: el que sigue a «teléfono», «telf.», «tel.» o «celular», con forma de número
  ecuatoriano (fijo 0X XXX XXXX o celular 09XXXXXXXX), fuera de frases sobre el proveedor.
- **Dirección**: lo que sigue a «dirección:» o «domicilio:», sin «dirección de correo», hasta el
  final de la línea; se descarta si es un hueco del formulario.
- **Correo**: se prefiere uno institucional (`.gob.ec`, `.edu.ec`, `.mil.ec`); no el del
  proveedor ni los del SERCOP.
- **Sitio web**: el que va tras «Web:», «Sitio web» o «Página web», o el del dominio de su correo
  con forma de dirección («www.…»). Uno suelto (el del SRI) no cuenta.

Todo es una propuesta: el panel lo marca «autollenado · revisa».
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from typing import Any

from contratacion.dominio.verificacion import ruc_valido

_RUC = re.compile(r"(?<!\d)(\d{13})(?!\d)")
_DEL_PROVEEDOR = re.compile(
    r"proveedor|contratista|oferente|adjudicatari|el\s+consultor|la\s+empresa\s+ofertante"
)
_HUECO = re.compile(r"[.…_]{3,}|\[por completar\]")
_TELEFONO_ETIQUETA = re.compile(
    r"(?:tel[eé]fonos?|telf\.?|tel\.|telefax|celular|pbx)\s*[:.]?\s*", re.IGNORECASE
)
_TELEFONO = re.compile(
    r"(?<!\d)(?:\(?\+?593\)?[\s-]?)?(?:\(?0?[2-7]\)?[\s-]?\d{3}[\s-]?\d{4}|0?9\d[\s-]?\d{3}[\s-]?\d{4})(?!\d)"
)
_DIRECCION = re.compile(
    r"(?:direcci[oó]n|domicilio)(?!\s+(?:de\s+)?(?:correo|electr|e-?mail|web))\s*[:.]\s*([^\n]{6,200})",
    re.IGNORECASE,
)
_CORREO = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_INSTITUCIONAL = (".gob.ec", ".edu.ec", ".mil.ec", ".gov.ec")
_CORTE_DIRECCION = re.compile(
    r"\s+(?:tel[eé]fono|telf|tel\.|correo|e-?mail|ruc|celular|ciudad|provincia|cant[oó]n|web|www|sitio)\b",
    re.IGNORECASE,
)


def _plano(texto: str) -> str:
    base = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in base if not unicodedata.combining(c)).lower()


def _contexto(texto: str, inicio: int, antes: int = 90) -> str:
    return _plano(texto[max(0, inicio - antes) : inicio])


def _ruc(texto: str) -> str:
    mejores: list[tuple[int, int, str]] = []
    for posicion, hallado in enumerate(_RUC.finditer(texto)):
        numero = hallado.group(1)
        if not ruc_valido(numero):
            continue
        cerca = _contexto(texto, hallado.start())
        if _DEL_PROVEEDOR.search(cerca):
            continue
        puntos = (2 if numero[2] == "6" else 0) + (1 if "ruc" in cerca[-25:] else 0)
        mejores.append((puntos, -posicion, numero))
    return max(mejores)[2] if mejores else ""


def _telefono(texto: str) -> str:
    for etiqueta in _TELEFONO_ETIQUETA.finditer(texto):
        if _DEL_PROVEEDOR.search(_contexto(texto, etiqueta.start(), 60)):
            continue
        tramo = texto[etiqueta.end() : etiqueta.end() + 40]
        if _HUECO.match(tramo.strip()):
            continue
        hallado = _TELEFONO.search(tramo)
        if hallado and hallado.start() <= 3:
            return " ".join(hallado.group(0).split())
    return ""


def _direccion(texto: str) -> str:
    for hallada in _DIRECCION.finditer(texto):
        if _DEL_PROVEEDOR.search(_contexto(texto, hallada.start(), 60)):
            continue
        valor = _CORTE_DIRECCION.split(hallada.group(1), maxsplit=1)[0]
        valor = " ".join(valor.split()).strip(" ,;:-.")
        if len(valor) >= 6 and not _HUECO.search(valor) and re.search(r"[A-Za-zÁÉÍÓÚÑ]{3}", valor):
            return valor[:200]
    return ""


def _correo(texto: str) -> str:
    correos: list[str] = []
    for hallado in _CORREO.finditer(texto):
        correo = hallado.group(0).strip(".")
        # El del proveedor («correo del oferente: …») y los del SERCOP no son de la entidad.
        if _DEL_PROVEEDOR.search(_contexto(texto, hallado.start(), 60)):
            continue
        if correo.lower().endswith(_AJENOS):
            continue
        correos.append(correo)
    institucionales = [c for c in correos if c.lower().endswith(_INSTITUCIONAL)]
    return (institucionales or correos or [""])[0]


# Sitios que aparecen en cualquier TDR (el portal de compras, el SRI) y no son de la entidad.
_AJENOS = ("compraspublicas.gob.ec", "sercop.gob.ec", "sri.gob.ec", "gob.ec/sercop")
_WEB = re.compile(
    r"(?<![@\w.])((?:https?://)?(?:www\.)?[a-z0-9][\w-]*(?:\.[\w-]+)*\.(?:gob\.ec|gov\.ec|"
    r"edu\.ec|mil\.ec|org\.ec|com\.ec|ec|com|org|net)(?:/[^\s,;)»\"']*)?)(?![\w@-])",
    re.IGNORECASE,
)
_ETIQUETA_WEB = re.compile(r"(?:web|sitio|p[aá]gina|portal|url|internet)\s*[:.]?\s*$", re.I)


def _dominio(direccion: str) -> str:
    sin_protocolo = re.sub(r"^https?://", "", direccion.lower())
    return sin_protocolo.split("/", 1)[0].removeprefix("www.")


def _web(texto: str, correo: str) -> str:
    """El sitio web de la entidad: el que va tras «Web:» o «Sitio web», o el del dominio de su
    correo («municipio@pimampiro.gob.ec» → «www.pimampiro.gob.ec»). Un dominio suelto mencionado
    en el texto (el del SRI, el del SERCOP) no basta: sería el de otro."""
    dominio_correo = correo.lower().rsplit("@", 1)[-1] if "@" in correo else ""
    candidatos: list[tuple[int, int, str]] = []
    for posicion, hallado in enumerate(_WEB.finditer(texto)):
        direccion = hallado.group(1).rstrip(".")
        dominio = _dominio(direccion)
        if "." not in dominio or any(ajeno in direccion.lower() for ajeno in _AJENOS):
            continue
        tiene_forma = direccion.lower().startswith(("http", "www."))
        etiquetado = bool(
            _ETIQUETA_WEB.search(texto[max(0, hallado.start() - 25) : hallado.start()])
        )
        mismo = bool(dominio_correo) and dominio == dominio_correo
        if not (etiquetado or (mismo and tiene_forma)):
            continue
        if _DEL_PROVEEDOR.search(_contexto(texto, hallado.start(), 60)):
            continue
        candidatos.append((2 * etiquetado + 2 * mismo + tiene_forma, -posicion, direccion))
    return max(candidatos)[2] if candidatos else ""


def datos_entidad_de_texto(texto: str) -> dict[str, str]:
    """RUC, dirección, teléfono, correo y sitio web de la entidad según el texto de un anexo."""
    texto = str(texto or "")
    correo = _correo(texto)
    datos = {
        "ruc": _ruc(texto),
        "direccion": _direccion(texto),
        "telefono": _telefono(texto),
        "correo": correo,
        "web": _web(texto, correo),
    }
    return {clave: valor for clave, valor in datos.items() if valor}


def completar_entidad(*fuentes: Mapping[str, Any] | None) -> dict[str, str]:
    """Junta los datos de varias fuentes: el primero que trae un campo, gana.

    Se pasan en orden de confianza: primero la ficha del portal (el RUC del código del proceso es
    seguro), después los anexos.
    """
    resultado: dict[str, str] = {}
    for fuente in fuentes:
        for clave, valor in (fuente or {}).items():
            texto = str(valor or "").strip()
            if texto and not resultado.get(clave):
                resultado[clave] = texto
    return resultado


def entidad_de_textos(textos: Iterable[str]) -> dict[str, str]:
    """Lo mismo, recorriendo varios anexos en orden (TDR primero)."""
    return completar_entidad(*(datos_entidad_de_texto(texto) for texto in textos))
