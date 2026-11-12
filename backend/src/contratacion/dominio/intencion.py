"""Qué pide un mensaje del asistente, sin modelo de lenguaje.

La mayoría de lo que se le pregunta al asistente es lo mismo: «recomiéndame ínfimas», «mis
alertas», «cómo va el NIC-…». Mandar eso al modelo cuesta un crédito, uno o dos segundos y tokens,
para terminar llamando a la misma herramienta. Este detector reconoce esas peticiones con reglas
fijas —palabras clave sin tildes ni mayúsculas, y la forma de un código de proceso o de un RUC— y
el asistente las contesta al instante y **sin cobrar**.

La regla de oro es la prudencia: ante la duda, `LIBRE` (el modelo con herramientas). Un falso
positivo responde algo que no se pidió, que es peor que pagar un crédito. Por eso las listas solo
se reconocen cuando el mensaje no trae nada más que la petición: «propuestas» sí, «propuestas de
limpieza en Guayas con más de 5 000 dólares» no, porque ahí hay filtros que solo el modelo sabe
convertir en argumentos.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class TipoIntencion(StrEnum):
    SALUDO = "saludo"
    AYUDA = "ayuda"
    PROPUESTAS = "propuestas_para_ti"
    ESTADO_PROCESO = "estado_proceso"
    LISTAR_ALERTAS = "listar_alertas"
    MIS_OFERTAS = "mis_ofertas"
    DATOS_EMPRESA = "datos_empresa"
    CONSULTAR_RUC = "consultar_ruc"
    HISTORIAL_RUC = "historial_ruc"
    PREPARAR_PROFORMA = "preparar_proforma"
    LIBRE = "libre"


@dataclass(frozen=True, slots=True)
class Intencion:
    tipo: TipoIntencion
    argumentos: dict[str, Any] = field(default_factory=dict)

    @property
    def rapida(self) -> bool:
        """Se contesta sin modelo."""
        return self.tipo is not TipoIntencion.LIBRE


PROVINCIAS = (
    "Azuay",
    "Bolívar",
    "Cañar",
    "Carchi",
    "Chimborazo",
    "Cotopaxi",
    "El Oro",
    "Esmeraldas",
    "Galápagos",
    "Guayas",
    "Imbabura",
    "Loja",
    "Los Ríos",
    "Manabí",
    "Morona Santiago",
    "Napo",
    "Orellana",
    "Pastaza",
    "Pichincha",
    "Santa Elena",
    "Santo Domingo de los Tsáchilas",
    "Sucumbíos",
    "Tungurahua",
    "Zamora Chinchipe",
)

# Un código de proceso del SERCOP: prefijo de 2 a 6 letras y al menos un grupo más con guion, con
# algún dígito y seis caracteres o más detrás del prefijo (`NIC-1768123450001-2026-00123`,
# `SIE-UTA-2026-0038`, `COTO-GADM-001-2026`). Se busca sobre el texto original, sin plegar.
_CODIGO = re.compile(r"(?<![\w-])([A-Za-z]{2,6}(?:-[A-Za-z0-9]+)+)(?![\w-])")
_RUC = re.compile(r"(?<!\d)(\d{13})(?!\d)")
_NO_PALABRA = re.compile(r"[^a-z0-9ñ\s-]+")


def plegar(texto: str | None) -> str:
    """Minúsculas, sin tildes, sin signos y con los espacios justos."""
    base = unicodedata.normalize("NFKD", str(texto or ""))
    sin_tilde = "".join(c for c in base if not unicodedata.combining(c)).lower()
    return " ".join(_NO_PALABRA.sub(" ", sin_tilde).split())


def codigo_de_proceso(texto: str) -> str | None:
    """El primer código de proceso del texto, en mayúsculas, o `None`."""
    for hallado in _CODIGO.finditer(texto or ""):
        codigo = hallado.group(1)
        _, _, resto = codigo.partition("-")
        if len(resto) >= 6 and any(c.isdigit() for c in resto):
            return codigo.upper()
    return None


def ruc_en(texto: str) -> str | None:
    hallado = _RUC.search(texto or "")
    return hallado.group(1) if hallado else None


_PROVINCIAS_PLEGADAS = {plegar(nombre): nombre for nombre in PROVINCIAS}


def provincia_oficial(texto: str | None) -> str | None:
    """«pichincha», «GALAPAGOS», «santo domingo» → el nombre oficial; `None` si no es provincia."""
    plano = plegar(texto)
    if not plano:
        return None
    if plano in _PROVINCIAS_PLEGADAS:
        return _PROVINCIAS_PLEGADAS[plano]
    for clave, nombre in _PROVINCIAS_PLEGADAS.items():
        if clave.startswith(plano) and len(plano) >= 5:
            return nombre
    return None


def provincia_mencionada(plano: str) -> str | None:
    """La provincia que aparece en un texto ya plegado, buscando las de nombre largo primero."""
    rodeado = f" {plano} "
    for clave in sorted(_PROVINCIAS_PLEGADAS, key=len, reverse=True):
        if f" {clave} " in rodeado:
            return _PROVINCIAS_PLEGADAS[clave]
    if " santo domingo " in rodeado:
        return "Santo Domingo de los Tsáchilas"
    return None


def _palabras(texto: str) -> frozenset[str]:
    return frozenset(texto.split())


def _tiene(plano: str, frases: tuple[str, ...]) -> bool:
    rodeado = f" {plano} "
    return any(f" {frase} " in rodeado for frase in frases)


_SALUDOS = (
    "hola",
    "holi",
    "buenas",
    "buenos dias",
    "buen dia",
    "buenas tardes",
    "buenas noches",
    "saludos",
    "hey",
    "que tal",
    "como estas",
    "como esta",
    "asistente",
    "gracias",
    "muchas gracias",
)
_AYUDA = (
    "ayuda",
    "ayudame",
    "que puedes hacer",
    "que sabes hacer",
    "que haces",
    "como funciona",
    "como te uso",
    "como funcionas",
    "en que me ayudas",
    "en que me puedes ayudar",
    "que puedo preguntarte",
    "que te puedo preguntar",
    "menu",
    "opciones",
)
# Verbos que piden algo nuevo o una búsqueda con filtros: siempre van al modelo.
_ACCIONES_LIBRES = (
    "crea",
    "crear",
    "creame",
    "creeme",
    "nueva alerta",
    "nueva",
    "agrega",
    "agregar",
    "avisame",
    "configura",
    "busca",
    "buscar",
    "buscame",
    "busco",
    "encuentra",
    "cuanto cuesta",
    "precio",
    "precios",
    "competidores",
    "competencia",
    "borra",
    "elimina",
    "quita",
    "cambia",
)
_PROPUESTAS = (
    "recomiendame",
    "recomienda",
    "recomiendeme",
    "recomendaciones",
    "recomendacion",
    "que me recomiendas",
    "que infimas",
    "propuestas",
    "propuestas para mi",
    "propuestas para ti",
    "a que puedo aplicar",
    "a que puedo postular",
    "a que puedo ofertar",
    "que puedo ofertar",
    "a que me puedo presentar",
    "oportunidades",
    "que hay para mi",
    "para mi empresa",
    "infimas para mi",
)
# Palabras que pueden acompañar a una petición de propuestas sin convertirla en una búsqueda.
_RELLENO_PROPUESTAS = _palabras(
    "a al algo alguna algunas alguno algunos aplicar ahora abiertas abiertos buenas cierre cierran "
    "cierra con cual cuales de del dame el en empresa es esta este hay hoy infima infimas la las "
    "lo los mas me mejor mejores mi mis muestrame muestra ofertar ordena ordenadas ordenar para "
    "por postular presentar presupuesto primero pronto propuesta propuestas puedo que quiero "
    "recomendacion recomendaciones recomienda recomiendame recomiendas recomiendeme se si sirven "
    "tengo ti todas una unas uno unos ver y oportunidad oportunidades mayor favor porfa porfavor "
    "dime cuantas nuevas nuevos vigentes"
)
_ALERTAS = (
    "mis alertas",
    "ver alertas",
    "ver mis alertas",
    "que alertas tengo",
    "cuales son mis alertas",
    "lista de alertas",
    "listar alertas",
    "muestrame mis alertas",
    "alertas activas",
    "tengo alertas",
)
_OFERTAS = (
    "mis ofertas",
    "mis proformas",
    "mis cotizaciones",
    "ofertas que hice",
    "proformas que hice",
    "ofertas enviadas",
    "proformas enviadas",
    "como van mis ofertas",
    "como van mis proformas",
    "estado de mis ofertas",
    "seguimiento de ofertas",
)
_ETAPAS = {
    "borrador": "borrador",
    "borradores": "borrador",
    "enviada": "enviada",
    "enviadas": "enviada",
    "adjudicada": "adjudicada",
    "adjudicadas": "adjudicada",
    "ganadas": "adjudicada",
    "ganada": "adjudicada",
    "perdida": "perdida",
    "perdidas": "perdida",
    "descartada": "descartada",
    "descartadas": "descartada",
}
_EMPRESA = (
    "mi empresa",
    "mis datos",
    "mis cpc",
    "mi cpc",
    "mi perfil",
    "datos de mi empresa",
    "datos de la empresa",
    "perfil de mi empresa",
    "que cpc tengo",
    "mis codigos cpc",
)
_PROFORMA = (
    "proforma",
    "proformas",
    "preparar",
    "prepara",
    "preparame",
    "cotizacion",
    "cotizar",
    "ofertar",
    "oferta",
    "postular",
    "armar",
    "arma",
)
_ESTADO = (
    "estado",
    "proceso",
    "como va",
    "como esta",
    "que paso",
    "informacion",
    "info",
    "detalle",
    "detalles",
    "datos",
    "ver",
    "muestrame",
    "consulta",
    "consultar",
    "cuando cierra",
    "cierre",
    "revisa",
)
_HISTORIAL_PISTAS = (
    "procesos",
    "proceso",
    "historial",
    "ganado",
    "gano",
    "ganados",
    "ganadas",
    "adjudicado",
    "adjudicados",
    "adjudicaciones",
    "contratos",
    "contratado",
    "participado",
    "experiencia",
    "cuantos",
    "cuantas",
)
_RUC_PISTAS = ("ruc", "sri", "consulta", "consultar", "quien es", "empresa", "contribuyente")
_PALABRAS_SALUDO = _palabras(
    "hola holi buenas buenos buen dia dias tardes noches saludos hey que tal como estas esta "
    "asistente gracias muchas por favor ok vale listo"
)


def _orden(plano: str) -> str | None:
    if _tiene(plano, ("cierre", "cierran", "cierra", "cierran pronto", "urgente", "urgentes")):
        return "cierre"
    if _tiene(plano, ("presupuesto", "mayor presupuesto", "mas dinero", "mas plata")):
        return "presupuesto"
    return None


def _solo_relleno(plano: str) -> bool:
    """El mensaje no trae nada más que la petición de propuestas (y, como mucho, una provincia)."""
    provincia = provincia_mencionada(plano)
    resto = f" {plano} "
    if provincia:
        resto = resto.replace(f" {plegar(provincia)} ", " ").replace(" santo domingo ", " ")
    return all(palabra in _RELLENO_PROPUESTAS for palabra in resto.split())


def detectar(texto: str) -> Intencion:
    """La intención de un mensaje. `LIBRE` cuando no hay una regla clara."""
    plano = plegar(texto)
    if not plano:
        return Intencion(TipoIntencion.AYUDA)
    palabras = plano.split()
    libre = _tiene(plano, _ACCIONES_LIBRES)

    codigo = codigo_de_proceso(texto)
    if codigo:
        if libre:
            return Intencion(TipoIntencion.LIBRE)
        if _tiene(plano, _PROFORMA):
            return Intencion(TipoIntencion.PREPARAR_PROFORMA, {"codigo": codigo})
        resto = [p for p in palabras if p != codigo.lower()]
        if _tiene(plano, _ESTADO) or len(resto) <= 2:
            return Intencion(TipoIntencion.ESTADO_PROCESO, {"codigo": codigo})
        return Intencion(TipoIntencion.LIBRE)

    ruc = ruc_en(texto)
    if ruc:
        if not libre and _tiene(plano, _HISTORIAL_PISTAS):
            return Intencion(TipoIntencion.HISTORIAL_RUC, {"ruc": ruc})
        if not libre and (_tiene(plano, _RUC_PISTAS) or len(palabras) <= 2):
            return Intencion(TipoIntencion.CONSULTAR_RUC, {"ruc": ruc})
        return Intencion(TipoIntencion.LIBRE)

    if libre:
        return Intencion(TipoIntencion.LIBRE)

    if all(palabra in _PALABRAS_SALUDO for palabra in palabras) and _tiene(plano, _SALUDOS):
        return Intencion(TipoIntencion.SALUDO)
    if _tiene(plano, _AYUDA) and len(palabras) <= 8:
        return Intencion(TipoIntencion.AYUDA)

    if _tiene(plano, _ALERTAS) and len(palabras) <= 8:
        return Intencion(TipoIntencion.LISTAR_ALERTAS)

    if _tiene(plano, _OFERTAS) and len(palabras) <= 10:
        argumentos: dict[str, Any] = {}
        etapa = next((_ETAPAS[p] for p in palabras if p in _ETAPAS), None)
        if etapa:
            argumentos["etapa"] = etapa
        return Intencion(TipoIntencion.MIS_OFERTAS, argumentos)

    # Antes que «mi empresa»: «oportunidades para mi empresa» pide propuestas, no el perfil.
    if _tiene(plano, _PROPUESTAS) and _solo_relleno(plano):
        argumentos = {}
        orden = _orden(plano)
        if orden:
            argumentos["orden"] = orden
        provincia = provincia_mencionada(plano)
        if provincia:
            argumentos["provincia"] = provincia
        return Intencion(TipoIntencion.PROPUESTAS, argumentos)

    if _tiene(plano, _EMPRESA) and len(palabras) <= 8:
        return Intencion(TipoIntencion.DATOS_EMPRESA)

    return Intencion(TipoIntencion.LIBRE)
