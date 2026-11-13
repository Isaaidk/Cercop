"""Compatibilidad de una oportunidad con el perfil comercial de una empresa.

La puntuación explica por qué una oportunidad se parece a lo que la empresa vende. No es una
probabilidad de adjudicación: no hay historial de quién ganó ni un modelo que prediga el fallo.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Any

from contratacion.dominio.texto import sin_marcas

_PESOS = {
    "cpc": 25,
    "objeto": 25,
    "geografia": 15,
    "presupuesto": 15,
    "requisitos": 10,
    "tiempo": 5,
    "historial": 5,
}


@dataclass(frozen=True, slots=True)
class CriteriosComerciales:
    """Lo que la empresa dijo que le interesa. Vacío significa «no lo uses para excluir»."""

    provincias: tuple[str, ...] = ()
    cantones: tuple[str, ...] = ()
    cpc: tuple[str, ...] = ()
    palabras: tuple[str, ...] = ()
    presupuesto_min: float | None = None
    presupuesto_max: float | None = None
    experiencias: tuple[str, ...] = ()

    @property
    def tiene_interes(self) -> bool:
        return bool(self.cpc or self.palabras)


# Textos cortos (palabras del perfil, provincias, cantones, códigos) se repiten en cada fila que se
# evalúa: se recuerdan. Los largos (el texto de cada ínfima) casi nunca se repiten y llenarían la
# memoria sin acertar, así que se calculan siempre. Es una función pura: el valor solo depende del
# texto, no de quién lo pide.
_LARGO_RECORDADO = 200


@lru_cache(maxsize=8192)
def _plegar_corto(texto: str) -> str:
    return _plegar(texto)


def _plegar(texto: str) -> str:
    sin_tilde = sin_marcas(unicodedata.normalize("NFKD", texto))
    return " ".join(sin_tilde.lower().split())


def plegar(texto: str | None) -> str:
    """Minúsculas y sin tildes, para comparar «Pichincha» con «PICHINCHA».

    Mismo resultado que filtrar `unicodedata.combining` carácter a carácter (ver `dominio/texto`),
    pero en C y recordando los textos cortos: era el 70 % de la CPU de «Propuestas para ti».
    """
    plano = str(texto or "")
    if len(plano) <= _LARGO_RECORDADO:
        return _plegar_corto(plano)
    return _plegar(plano)


def _numero(valor: Any) -> float | None:
    if valor is None or valor == "":
        return None
    try:
        return float(str(valor).replace(",", ""))
    except ValueError:
        return None


def _codigos(valores: tuple[str, ...] | list[str]) -> list[str]:
    return [plegar(valor) for valor in valores if plegar(valor)]


def coincide_cpc(criterios: CriteriosComerciales, codigos: list[str]) -> bool:
    """Un código del perfil cabe en uno de la oportunidad, o al revés, por el inicio."""
    propios = _codigos(criterios.cpc)
    ajenos = _codigos(codigos)
    if not propios or not ajenos:
        return False
    for propio in propios:
        for ajeno in ajenos:
            if propio in ajeno or ajeno in propio:
                return True
    return False


def coincide_texto(criterios: CriteriosComerciales, texto: str) -> list[str]:
    """Palabras del perfil que aparecen en el objeto o en el texto de la oportunidad."""
    plano = plegar(texto)
    if not plano:
        return []
    halladas = []
    for palabra in criterios.palabras:
        plana = plegar(palabra)
        if plana and plana in plano:
            halladas.append(palabra)
    return halladas


def _monto_en_rango(criterios: CriteriosComerciales, monto: float | None) -> bool | None:
    """True si cabe, False si no, None si la oportunidad no publica monto."""
    if criterios.presupuesto_min is None and criterios.presupuesto_max is None:
        return True
    if monto is None:
        return None
    if criterios.presupuesto_min is not None and monto < criterios.presupuesto_min:
        return False
    return criterios.presupuesto_max is None or monto <= criterios.presupuesto_max


def excluir(criterios: CriteriosComerciales, oportunidad: dict[str, Any]) -> str | None:
    """Motivo para no mostrar la oportunidad, o None si entra al radar.

    La ubicación y el presupuesto, cuando la empresa los fijó, son duros: lo que cae fuera no se
    muestra. El interés (CPC o palabras) basta con que coincida en uno de los dos.
    """
    if not criterios.tiene_interes:
        return (
            "El perfil no tiene CPC, productos ni palabras clave. "
            "Sin eso no hay con qué reconocer una oportunidad."
        )
    provincia = plegar(oportunidad.get("provincia"))
    if criterios.provincias and provincia not in {plegar(p) for p in criterios.provincias}:
        return "La provincia no está en la zona de operación."
    canton = plegar(oportunidad.get("canton"))
    propios = {plegar(c) for c in criterios.cantones if plegar(c)}
    if propios and canton and canton not in propios:
        return "El cantón no está en la zona de operación."
    rango = _monto_en_rango(criterios, _numero(oportunidad.get("presupuesto")))
    if rango is False:
        return "El presupuesto queda fuera del rango de interés."
    cpc_ok = coincide_cpc(criterios, list(oportunidad.get("cpc_codigos") or []))
    texto = " ".join(str(oportunidad.get(clave) or "") for clave in ("objeto", "texto", "entidad"))
    palabras_ok = bool(coincide_texto(criterios, texto))
    if not cpc_ok and not palabras_ok:
        return "No coincide con el CPC ni con lo que la empresa ofrece."
    return None


def _factor(codigo: str, puntos: int, motivo: str) -> dict[str, Any]:
    return {"codigo": codigo, "puntos": puntos, "de": _PESOS[codigo], "motivo": motivo}


def puntuar(criterios: CriteriosComerciales, oportunidad: dict[str, Any]) -> dict[str, Any]:
    """Puntos de 0 a 100 y el motivo de cada factor. No predice la adjudicación."""
    factores: list[dict[str, Any]] = []

    if not criterios.cpc:
        factores.append(_factor("cpc", _PESOS["cpc"], "Sin CPC de interés: no resta."))
    elif coincide_cpc(criterios, list(oportunidad.get("cpc_codigos") or [])):
        factores.append(_factor("cpc", _PESOS["cpc"], "El CPC encaja con el perfil."))
    else:
        factores.append(_factor("cpc", 0, "El CPC publicado no encaja con el del perfil."))

    texto = " ".join(str(oportunidad.get(clave) or "") for clave in ("objeto", "texto"))
    halladas = coincide_texto(criterios, texto)
    if not criterios.palabras:
        factores.append(_factor("objeto", _PESOS["objeto"], "Sin productos ni palabras: no resta."))
    elif halladas:
        muestra = ", ".join(halladas[:4])
        factores.append(_factor("objeto", _PESOS["objeto"], f"El objeto menciona: {muestra}."))
    else:
        factores.append(_factor("objeto", 0, "El objeto no menciona lo ofrecido."))

    if not criterios.provincias and not criterios.cantones:
        factores.append(
            _factor("geografia", _PESOS["geografia"], "Sin zona de operación: no resta.")
        )
    elif excluir(criterios, oportunidad) is None:
        lugar = oportunidad.get("provincia") or "sin provincia"
        factores.append(_factor("geografia", _PESOS["geografia"], f"Está en la zona ({lugar})."))
    else:
        factores.append(_factor("geografia", 0, "Queda fuera de la zona de operación."))

    rango = _monto_en_rango(criterios, _numero(oportunidad.get("presupuesto")))
    if criterios.presupuesto_min is None and criterios.presupuesto_max is None:
        factores.append(
            _factor("presupuesto", _PESOS["presupuesto"], "Sin rango de presupuesto: no resta.")
        )
    elif rango is None:
        factores.append(
            _factor("presupuesto", _PESOS["presupuesto"] // 2, "No publica presupuesto.")
        )
    elif rango:
        factores.append(_factor("presupuesto", _PESOS["presupuesto"], "El presupuesto cabe."))
    else:
        factores.append(_factor("presupuesto", 0, "El presupuesto queda fuera del rango."))

    documentos = list(oportunidad.get("documentos") or [])
    if documentos:
        factores.append(_factor("requisitos", _PESOS["requisitos"], "Hay documentos para revisar."))
    else:
        factores.append(_factor("requisitos", 0, "La ficha no trae documentos."))

    plazo = oportunidad.get("plazo")
    if isinstance(plazo, datetime) and plazo.timestamp() > datetime.now().astimezone().timestamp():
        factores.append(_factor("tiempo", _PESOS["tiempo"], "El plazo de proformas sigue abierto."))
    elif plazo is None:
        factores.append(_factor("tiempo", 0, "No hay fecha límite de proformas publicada."))
    else:
        factores.append(_factor("tiempo", 0, "El plazo de proformas ya venció."))

    if not criterios.experiencias:
        factores.append(
            _factor("historial", _PESOS["historial"], "Sin experiencia cargada: no resta.")
        )
    elif coincide_texto(
        CriteriosComerciales(palabras=criterios.experiencias),
        texto + " " + " ".join(str(c) for c in oportunidad.get("cpc_codigos") or []),
    ):
        factores.append(
            _factor("historial", _PESOS["historial"], "Se parece a una experiencia ya registrada.")
        )
    else:
        factores.append(
            _factor("historial", 0, "No se parece a la experiencia registrada de la empresa.")
        )

    puntos = sum(int(factor["puntos"]) for factor in factores)
    return {
        "puntos": puntos,
        "de": 100,
        "factores": factores,
        "aviso": "Esta nota mide parecido con el perfil. No es una probabilidad de adjudicación.",
    }


# «CPC 87150» o «CPC: 73210.00.1» dentro de un texto libre. Es la forma en que la carga del RUP deja
# cada código en la descripción de lo que la empresa ofrece (`gestionar_perfil.aplicar_rup`).
_CPC_EN_TEXTO = re.compile(r"\bCPC\W{0,3}(\d[\d.]{2,14}\d)", re.IGNORECASE)
# Un CPC suelto, como el que trae la experiencia («8715»): solo dígitos y puntos.
_CPC_SUELTO = re.compile(r"^\d[\d.]{2,14}\d$")


def cpc_del_perfil(perfil: dict[str, Any]) -> list[str]:
    """CPC que el perfil declara fuera de la lista vigilada, sin repetir.

    El RUP deja cada código en la descripción de lo ofrecido («CPC 73210») y la experiencia trae el
    suyo en su propia columna. Antes esos textos solo entraban como palabras, y una palabra
    «CPC 73210» no aparece en el objeto de ningún proceso: el radar no reconocía los CPC con los que
    la empresa ya vende o ya vendió si alguien los quitaba de la lista vigilada.
    """
    hallados: list[str] = []
    for fila in perfil.get("ofertas") or []:
        for texto in (fila.get("descripcion"), fila.get("nombre")):
            hallados.extend(_CPC_EN_TEXTO.findall(str(texto or "")))
    for fila in perfil.get("experiencia") or []:
        crudo = str(fila.get("cpc") or "").strip()
        if _CPC_SUELTO.match(crudo):
            hallados.append(crudo)
        else:
            hallados.extend(_CPC_EN_TEXTO.findall(crudo))
    return list(dict.fromkeys(hallados))


def criterios_desde_perfil(perfil: dict[str, Any], cpc: list[str]) -> CriteriosComerciales:
    """Arma los criterios con lo que la empresa registró, sin inventar lo que no dijo.

    Los CPC salen de la lista vigilada **y** del propio perfil (lo ofrecido y la experiencia), para
    que un CPC cargado desde el RUP cuente aunque no esté en la lista.
    """
    palabras: list[str] = []
    codigos: list[str] = []
    for texto in cpc:
        limpio = str(texto or "").strip()
        if not limpio:
            continue
        if any(caracter.isdigit() for caracter in limpio):
            codigos.append(limpio)
        else:
            palabras.append(limpio)
    for codigo in cpc_del_perfil(perfil):
        if codigo not in codigos:
            codigos.append(codigo)
    for fila in perfil.get("palabras") or []:
        palabras.append(str(fila.get("texto") or ""))
    for fila in perfil.get("ofertas") or []:
        palabras.append(str(fila.get("nombre") or ""))
        # «CPC 73210» como palabra no aparece en ningún objeto: el código ya entró como CPC arriba.
        descripcion = _CPC_EN_TEXTO.sub("", str(fila.get("descripcion") or "")).strip()
        palabras.append(descripcion)
    for fila in perfil.get("actividades") or []:
        palabras.append(str(fila.get("descripcion") or ""))
    experiencias = [
        " ".join(
            parte for parte in (str(fila.get("objeto") or ""), str(fila.get("cpc") or "")) if parte
        )
        for fila in perfil.get("experiencia") or []
    ]
    cobertura = list(perfil.get("cobertura") or [])
    return CriteriosComerciales(
        provincias=tuple(
            str(fila.get("provincia") or "") for fila in cobertura if fila.get("provincia")
        ),
        cantones=tuple(str(fila.get("canton") or "") for fila in cobertura if fila.get("canton")),
        cpc=tuple(codigos),
        palabras=tuple(palabra for palabra in palabras if plegar(palabra)),
        presupuesto_min=_numero(perfil.get("presupuesto_min")),
        presupuesto_max=_numero(perfil.get("presupuesto_max")),
        experiencias=tuple(texto for texto in experiencias if plegar(texto)),
    )


def unir_duplicados(filas: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Una fila por código de proceso. Si la ingesta repitió el mismo, se queda la más reciente."""
    elegidas: dict[str, dict[str, Any]] = {}
    orden: list[str] = []
    for fila in filas:
        clave = plegar(str(fila.get("codigo") or fila.get("clave_natural") or fila.get("id")))
        if clave not in elegidas:
            orden.append(clave)
            elegidas[clave] = fila
            continue
        previa = elegidas[clave]
        if str(fila.get("ultima_vez_visto") or "") >= str(previa.get("ultima_vez_visto") or ""):
            elegidas[clave] = fila
    unidas = [elegidas[clave] for clave in orden]
    return unidas, len(filas) - len(unidas)
