"""Qué frase del TDR es un requisito que se pueda verificar, y cómo se resumen las condiciones.

El cliente lo pidió así: la lista de requisitos (paso 2, R1…Rn) debe traer solo factores
operativos directos y medibles —protocolos de bioseguridad, cantidades mínimas («mínimo 193
procedimientos»), condiciones de entrega, personal y su título, equipo, plazos—, en el orden del
TDR y con su numeral. Las frases de justificación («Desde el enfoque de bienestar animal, el
proyecto promueve una alternativa ética…») no se pueden marcar como cumplidas y llenaban la barra
de avance con criterios que nadie valida.

Y las condiciones de la oferta (plazo, lugar, forma de pago) van en una frase. El TDR suele traer
el plazo pegado al cronograma («El presente cronograma refleja 3 jornadas … 180 días
correspondiente a los meses…»): el campo lleva «180 días contados a partir del día siguiente de la
suscripción de la orden de compra.» y el texto largo pasa al documento de respaldo.

Todo es puro: recibe texto y devuelve texto.
"""

from __future__ import annotations

import re
from typing import Any

from contratacion.dominio.palabras import normalizar

# Un campo del formulario de la entidad («PLAZO DE ENTREGA: 15 días»): siempre es un requisito.
_CAMPO = re.compile(r"^[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ ]{2,60}:")

# Verbos y giros de obligación, sobre el texto sin tildes y en minúsculas.
_OBLIGACION = re.compile(
    r"\b(?:debe|deben|debera|deberan|requiere|requieren|requerira|se requiere|exige|exigira|"
    r"obligatori\w*|minim[oa]s?|maxim[oa]s?|al menos|no menor|no mayor|como minimo|"
    r"contar con|contara|contaran|garantiz\w*|cumplir\w*|entregar\w*|se entregara|"
    r"realizar\w*|se realizara|presentar\w*|proveer\w*|dotar\w*|dispondra|disponer de|"
    r"aplicar\w*|aplicara|incluir\w*|sera responsable|seran responsables|se encargara|"
    r"ejecutar\w*|suministrar\w*|instalar\w*|emitir\w*|elaborar\w*|asegurar\w*|"
    r"utilizar\w*|acreditar\w*|sera identificad\w*|seran identificad\w*|sera entregad\w*|"
    r"seran entregad\w*|sera realizad\w*|seran realizad\w*)\b"
)
# Lo que hace verificable un requisito aunque no traiga verbo de obligación.
_OPERATIVO = (
    "protocolo",
    "bioseguridad",
    "titulo",
    "profesional",
    "medico",
    "veterinari",
    "tecnico",
    "personal",
    "equipo",
    "insumo",
    "material",
    "medicament",
    "anestesi",
    "quirurg",
    "cirug",
    "plazo",
    "cronograma",
    "jornada",
    "entrega",
    "informe",
    "acta",
    "registro",
    "certificad",
    "licencia",
    "permiso",
    "garantia",
    "poliza",
    "uniforme",
    "vehiculo",
    "transporte",
    "horario",
    "senescyt",
    "experiencia",
)
# Giros de justificación o de contexto. Cada uno resta: una frase que solo explica por qué se
# contrata no se puede marcar como cumplida.
_NARRATIVO = (
    "enfoque",
    "promueve",
    "promover",
    "contribuy",
    "contribuir",
    "alternativa etica",
    "es importante",
    "se busca",
    "tiene como finalidad",
    "tiene por finalidad",
    "bienestar",
    "problematica",
    "en este contexto",
    "por lo expuesto",
    "es por ello",
    "considerando",
    "justific",
    "sensibiliz",
    "concienc",
    "el presente proyecto",
    "el proyecto",
    "la ciudadania",
    "salud publica",
)
_CIFRA = re.compile(r"\d")
_PRECIO = re.compile(r"\$|\busd\b|\bprecio|valor unitario|valor total|\bdolares\b")


def es_requisito_operativo(texto: str) -> bool:
    """Un factor que la entidad puede verificar: obligación, cantidad o dato operativo concreto.

    - Un campo del formulario («FORMA DE PAGO: …») siempre lo es.
    - Un precio no: la proforma lo escribe aparte, no es algo que se marque como cumplido.
    - Una línea corta de lista («RUC activo», «Toner original del fabricante») sí: es lo que se
      marca en un checklist.
    - Lo demás suma puntos por obligación (2), cifra (2) y datos operativos (personal, equipo,
      protocolo, plazo…, hasta 2) y resta por cada giro de justificación (2). Pasa con 1 o más.
    """
    limpio = " ".join(str(texto or "").split())
    if _CAMPO.match(limpio):
        return True
    plano = normalizar(limpio)
    if len(plano) < 6 or _PRECIO.search(plano):
        return False
    narrativo = sum(1 for marca in _NARRATIVO if marca in plano)
    if not narrativo and len(plano.split()) <= 6:
        return True
    puntos = (
        2 * bool(_OBLIGACION.search(plano))
        + 2 * bool(_CIFRA.search(plano))
        + min(2, sum(1 for palabra in _OPERATIVO if palabra in plano))
        - 2 * narrativo
    )
    return puntos >= 1


# --- Condiciones en una frase ---------------------------------------------------------------------

_DURACION = re.compile(
    r"(?<![\d.,])(\d{1,4})\s*(?:\([^)]{1,40}\)\s*)?"
    r"(d[ií]as?|mes(?:es)?|semanas?|horas?|a[nñ]os?)"
    r"(?:\s+(calendario|h[aá]biles|laborables))?",
    re.IGNORECASE,
)
_A_DIAS = {"dia": 1, "semana": 7, "mes": 30, "ano": 365, "hora": 1 / 24}
_UNIDADES = {
    "dia": ("día", "días"),
    "semana": ("semana", "semanas"),
    "mes": ("mes", "meses"),
    "ano": ("año", "años"),
    "hora": ("hora", "horas"),
}
_TOPE_CONDICION = 160
_TOPE_DETALLE = 1500
_MARCA_ACTA = re.compile(r"^(Según (?:el )?acta[^:]{0,40}):\s*", re.IGNORECASE)


def _unidad(texto: str) -> str:
    plano = normalizar(texto).rstrip("s")
    if plano.startswith("dia"):
        return "dia"
    if plano.startswith("mes") or plano == "me":
        return "mes"
    if plano.startswith("semana"):
        return "semana"
    if plano.startswith("hora"):
        return "hora"
    return "ano"


def duracion(texto: str) -> tuple[int, str, str] | None:
    """El plazo del texto: (número, unidad, calificativo). Manda el que va junto a «plazo».

    Sin «plazo» cerca, el más largo: en un cronograma, «3 jornadas de 2 días en 180 días» es 180.
    """
    original = str(texto or "")
    plano = normalizar(original)
    candidatos = []
    for hallado in _DURACION.finditer(original):
        numero = int(hallado.group(1))
        if numero <= 0:
            continue
        unidad = _unidad(hallado.group(2))
        calificativo = normalizar(hallado.group(3) or "")
        cerca = plano[max(0, hallado.start() - 120) : hallado.start()]
        junto_a_plazo = "plazo" in cerca or "termino de" in cerca
        candidatos.append(
            (junto_a_plazo, numero * _A_DIAS[unidad], hallado.start(), numero, unidad, calificativo)
        )
    if not candidatos:
        return None
    junto = [c for c in candidatos if c[0]]
    elegido = min(junto, key=lambda c: c[2]) if junto else max(candidatos, key=lambda c: c[1])
    return elegido[3], elegido[4], elegido[5]


def _con_unidad(numero: int, unidad: str, calificativo: str = "") -> str:
    singular, plural = _UNIDADES[unidad]
    texto = f"{numero} {singular if numero == 1 else plural}"
    if calificativo and unidad == "dia":
        texto += " calendario" if calificativo == "calendario" else f" {calificativo}"
    return texto


def _primera_frase(texto: str) -> str:
    partes = re.split(r"(?<=[.;])\s+", texto.strip(), maxsplit=1)
    return partes[0].strip() if partes else ""


def _corto(texto: str, tope: int = _TOPE_CONDICION) -> str:
    texto = " ".join(str(texto or "").split())
    if len(texto) <= tope:
        return texto
    corte = texto.rfind(". ", 0, tope)
    corte = corte if corte > tope // 2 else texto.rfind(" ", 0, tope)
    return texto[: corte if corte > 0 else tope].rstrip(" ,:;.") + "…"


def plazo_breve(texto: str, tope: int = 90) -> str:
    """El plazo en una frase estándar; un plazo que ya es corto («15 días calendario») queda igual.

    «El presente cronograma refleja 3 jornadas … 180 días correspondiente a los meses…» →
    «180 días contados a partir del día siguiente de la suscripción de la orden de compra.»
    """
    limpio = " ".join(str(texto or "").split())
    if not limpio:
        return ""
    sin_marca = _MARCA_ACTA.sub("", limpio)
    if len(sin_marca) <= tope and "cronograma" not in normalizar(sin_marca):
        return limpio
    hallado = duracion(sin_marca)
    if hallado is None:
        return _corto(limpio)
    plano = normalizar(sin_marca)
    documento = (
        "del contrato" if "contrato" in plano and "orden de compra" not in plano else None
    ) or "de la orden de compra"
    return (
        f"{_con_unidad(*hallado)} contados a partir del día siguiente de la suscripción "
        f"{documento}."
    )


def plazo_ejecucion(texto: str) -> str:
    """Solo la duración («180 días»): es lo que pide la casilla del formulario del SOCE."""
    hallado = duracion(_MARCA_ACTA.sub("", " ".join(str(texto or "").split())))
    return _con_unidad(*hallado) if hallado else ""


def condicion_breve(texto: str, pistas: tuple[str, ...] = (), tope: int = _TOPE_CONDICION) -> str:
    """Una condición (lugar, forma de pago) en una frase: la primera que trae una pista."""
    limpio = " ".join(str(texto or "").split())
    if len(limpio) <= tope:
        return limpio
    frases = [f.strip() for f in re.split(r"(?<=[.;])\s+", limpio) if f.strip()]
    for frase in frases:
        if not pistas or any(pista in normalizar(frase) for pista in pistas):
            return _corto(frase, tope)
    return _corto(frases[0] if frases else limpio, tope)


def alcance_breve(texto: str, tope: int = 300) -> str:
    """La frase medible del alcance («Un mínimo de 193 procedimientos…»), o la primera."""
    limpio = " ".join(str(texto or "").split())
    if not limpio:
        return ""
    frases = [f.strip() for f in re.split(r"(?<=[.;])\s+", limpio) if len(f.strip()) > 12]
    for frase in frases:
        plano = normalizar(frase)
        if _CIFRA.search(frase) or "minimo" in plano or "al menos" in plano:
            return _corto(frase, tope)
    return _corto(frases[0] if frases else limpio, tope)


_ETIQUETAS_DETALLE = {
    "plazo_entrega": "Plazo de entrega",
    "lugar_entrega": "Lugar de entrega",
    "forma_pago": "Forma de pago",
    "garantia": "Garantía",
}


def condiciones_de_tdr(secciones: dict[str, Any]) -> dict[str, str]:
    """Las condiciones de la oferta que el TDR trae, cada una en una frase, más su detalle.

    `detalle` junta el texto completo de las que se resumieron: no se pierde, va al documento de
    respaldo. `alcance` es la frase medible del apartado «Alcance». Lo que el TDR no trae no sale.
    """
    s = {clave: " ".join(str(valor or "").split()) for clave, valor in (secciones or {}).items()}
    plazo_original = s.get("plazo_entrega") or s.get("plazos") or ""
    originales = {
        "plazo_entrega": plazo_original,
        "lugar_entrega": s.get("lugar_entrega") or "",
        "forma_pago": s.get("forma_pago") or "",
        "garantia": s.get("garantia") or "",
    }
    breves = {
        "plazo_entrega": plazo_breve(plazo_original),
        "lugar_entrega": condicion_breve(
            originales["lugar_entrega"], ("lugar", "entreg", "direccion", "instalaciones")
        ),
        "forma_pago": condicion_breve(
            originales["forma_pago"], ("pago", "factura", "anticipo", "%", "contra entrega")
        ),
        "garantia": condicion_breve(originales["garantia"], ("garantia", "mes", "ano")),
    }
    salida = {clave: valor for clave, valor in breves.items() if valor}
    ejecucion = plazo_ejecucion(plazo_original)
    if ejecucion:
        salida["plazo_ejecucion"] = ejecucion
    if s.get("vigencia_proforma"):
        salida["validez"] = _corto(s["vigencia_proforma"], 60)
    alcance = alcance_breve(s.get("alcance") or "")
    if alcance:
        salida["alcance"] = alcance
    detalle = [
        f"{_ETIQUETAS_DETALLE[clave]} (según el TDR): {_corto(original, _TOPE_DETALLE)}"
        for clave, original in originales.items()
        if original and len(original) > len(breves[clave]) + 10
    ]
    if detalle:
        salida["detalle"] = "\n".join(detalle)
    return salida
