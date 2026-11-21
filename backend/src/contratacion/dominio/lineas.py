"""Las líneas de la proforma salen de lo que la entidad publicó, nunca de la imaginación.

Dos fuentes valen, en este orden:

1. **ficha**: los ítems que la entidad publica en el portal (`registro.items`, con CPC, unidad y
   cantidad).
2. **tdr**: la tabla de productos o servicios del TDR («7. PRODUCTOS O SERVICIOS ESPERADOS»), leída
   renglón por renglón del texto del anexo.

La IA no agrega ítems, no cambia cantidades ni unidades y no pone precios: `validar_lineas`
confronta cada línea que propone con la fuente, devuelve la publicada tal cual y descarta lo que no
se puede ubicar. Si no hay fuente, solo queda una línea del modelo que el texto del TDR respalde.
Cada línea lleva su `origen` (`ficha`, `tdr` o `usuario`).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from contratacion.dominio.palabras import normalizar

ORIGENES = ("ficha", "tdr", "usuario")
TOPE_LINEAS = 60

_UNIDADES = (
    r"UNIDADES|UNIDAD|UNID\.?|UND\.?|UNDS\.?|U\.|U|GLOBAL|GLB\.?|SERVICIOS?|KITS?|JUEGOS?|"
    r"CAJAS?|PAQUETES?|GAL[OÓ]N(?:ES)?|GALONES|LITROS?|LTS?\.?|METROS?|MTS?\.?|ROLLOS?|PARES|PAR|"
    r"RESMAS?|FRASCOS?|SACOS?|CANECAS?|PIEZAS?|PZAS?\.?|LIBRAS?|KILOS?|KG\.?|HORAS?|D[IÍ]AS?|"
    r"MES(?:ES)?|EVENTOS?|PERSONAS?|PLANCHAS?|TUBOS?|FUNDAS?|CIENTOS?|DOCENAS?|BLOQUES?|LOTES?|"
    r"CONTRATOS?|SESIONES?|TALLERES?|ATENCIONES?|PROCEDIMIENTOS?|EJEMPLARES?|M2|M3|ML"
)
_NUMERO = r"\d{1,7}(?:[.,]\d{1,3})?"
# Tras la cantidad puede venir la columna de precios sin llenar: «$», «0,00», «[por completar]».
_COLA = r"(?:\s+(?:\$|USD|\[por completar\]|_+|\d[\d.,]*))*"
_INICIO = r"^\s*(?P<n>\d{1,3})[.)\-]?\s+(?:(?P<cpc>\d{5,9}(?:\s\d{1,3})?)\s+)?"
_UNIDAD_CANTIDAD = re.compile(
    _INICIO + rf"(?P<desc>.+?\S)\s+(?P<u>{_UNIDADES})\s+(?P<c>{_NUMERO}){_COLA}\s*$",
    re.IGNORECASE,
)
_CANTIDAD_UNIDAD = re.compile(
    _INICIO + rf"(?P<desc>.+?\S)\s+(?P<c>{_NUMERO})\s+(?P<u>{_UNIDADES}){_COLA}\s*$",
    re.IGNORECASE,
)
_FIN_DE_TABLA = re.compile(r"^\s*(sub\s*total|total|iva|son:|valor total)\b", re.IGNORECASE)


def _numero(texto: str) -> float:
    try:
        return float(texto.replace(",", "."))
    except ValueError:
        return 0.0


def _cabecera(linea: str) -> str | None:
    """«unidad» o «cantidad» según cuál columna va primero, si la línea es la cabecera."""
    plana = normalizar(linea)
    if "descrip" not in plana or "cantidad" not in plana:
        return None
    unidad = plana.find("unidad")
    if unidad < 0:
        return "cantidad"
    return "unidad" if unidad < plana.find("cantidad") else "cantidad"


def items_de_tdr(texto: str) -> list[dict[str, Any]]:
    """Los renglones de la tabla de productos/servicios del TDR, tal como están escritos.

    Solo cuenta una tabla con cabecera («… DESCRIPCIÓN … CANTIDAD …») y renglones numerados desde
    1 y seguidos. Lo que no se lee con seguridad no se devuelve: sin tabla, lista vacía, y la
    proforma no se llena con suposiciones.
    """
    mejores: list[dict[str, Any]] = []
    lineas = [" ".join(linea.split()) for linea in str(texto or "").splitlines()]
    for inicio, linea in enumerate(lineas):
        orden = _cabecera(linea)
        if orden is None:
            continue
        patrones = (
            (_UNIDAD_CANTIDAD, _CANTIDAD_UNIDAD)
            if orden == "unidad"
            else (_CANTIDAD_UNIDAD, _UNIDAD_CANTIDAD)
        )
        filas: list[dict[str, Any]] = []
        for renglon in lineas[inicio + 1 : inicio + 1 + TOPE_LINEAS * 2]:
            if not renglon:
                continue
            if _FIN_DE_TABLA.match(renglon) or _cabecera(renglon):
                break
            hallado = next((m for p in patrones if (m := p.match(renglon))), None)
            if hallado is None or int(hallado.group("n")) != len(filas) + 1:
                if filas:
                    break
                continue
            cantidad = _numero(hallado.group("c"))
            if cantidad <= 0:
                break
            filas.append(
                {
                    "numero": len(filas) + 1,
                    "cpc": (hallado.group("cpc") or "").replace(" ", ""),
                    "descripcion": hallado.group("desc").strip(" -:"),
                    "unidad": hallado.group("u").upper(),
                    "cantidad": cantidad,
                }
            )
        if len(filas) > len(mejores):
            mejores = filas
    return mejores[:TOPE_LINEAS]


def _linea(item: dict[str, Any], origen: str) -> dict[str, Any]:
    cantidad = float(item.get("cantidad") or 0) or 1.0
    linea: dict[str, Any] = {
        "descripcion": " ".join(str(item.get("descripcion") or "").split()),
        "cantidad": int(cantidad) if cantidad.is_integer() else cantidad,
        "unidad": str(item.get("unidad") or "").strip(),
        "precio_unitario": None,
        "origen": origen,
    }
    if item.get("cpc"):
        linea["cpc"] = str(item["cpc"]).strip()
        linea["cpc_nombre"] = str(item.get("cpc_nombre") or "").strip()
    return linea


def lineas_de_fuente(items_ficha: Sequence[dict[str, Any]], texto_tdr: str) -> list[dict[str, Any]]:
    """Las líneas publicadas: los ítems de la ficha o, sin ellos, la tabla del TDR."""
    if items_ficha:
        return [_linea(item, "ficha") for item in list(items_ficha)[:TOPE_LINEAS]]
    return [_linea(item, "tdr") for item in items_de_tdr(texto_tdr)]


def _palabras(texto: str) -> set[str]:
    return {p for p in re.split(r"[^a-z0-9ñ]+", normalizar(texto)) if len(p) >= 2}


def _parecido(a: str, b: str) -> float:
    """Coincidencia de palabras entre dos descripciones (0 a 1), sobre la más corta."""
    uno, otro = _palabras(a), _palabras(b)
    if not uno or not otro:
        return 0.0
    return len(uno & otro) / min(len(uno), len(otro))


_MINIMO_PARECIDO = 0.6


def _en_texto(valor: str, texto_plano: str) -> bool:
    plano = normalizar(valor).strip()
    return (
        bool(plano)
        and re.search(rf"(?<![a-z0-9]){re.escape(plano)}(?![a-z0-9])", texto_plano) is not None
    )


def _cantidad_en_texto(cantidad: float, texto: str) -> bool:
    numeros = {_numero(n) for n in re.findall(r"\d+(?:[.,]\d+)?", texto)}
    return cantidad in numeros


def validar_lineas(
    propuestas: Sequence[Any], fuente: Sequence[dict[str, Any]], texto_tdr: str
) -> tuple[list[dict[str, Any]], list[str]]:
    """Las líneas de la IA confrontadas con lo publicado. Devuelve (líneas, descartadas).

    Con fuente, el resultado son **las líneas publicadas**, en su orden, con su descripción,
    cantidad y unidad: la IA solo puede completar la unidad que falte si esa unidad está escrita en
    el TDR. Lo que propuso y no corresponde a ningún ítem publicado se descarta.

    Sin fuente, una línea del modelo queda solo si sus palabras están en el TDR (al menos el 60 %);
    su cantidad y unidad se conservan solo si aparecen en el texto, y si no se marcan para que la
    persona las confirme (`verificar`). Ninguna lleva precio.
    """
    plano = normalizar(texto_tdr)
    validas = [
        p for p in propuestas if isinstance(p, dict) and str(p.get("descripcion") or "").strip()
    ]
    if fuente:
        salida = [dict(linea) for linea in fuente]
        usadas: set[int] = set()
        for linea in salida:
            mejor, puntaje = None, 0.0
            for indice, propuesta in enumerate(validas):
                if indice in usadas:
                    continue
                valor = _parecido(linea["descripcion"], str(propuesta["descripcion"]))
                if valor > puntaje:
                    mejor, puntaje = indice, valor
            if mejor is None or puntaje < _MINIMO_PARECIDO:
                continue
            usadas.add(mejor)
            unidad = " ".join(str(validas[mejor].get("unidad") or "").split())[:30]
            if not linea.get("unidad") and unidad and _en_texto(unidad, plano):
                linea["unidad"] = unidad
        descartadas = [
            str(p["descripcion"])[:200] for i, p in enumerate(validas) if i not in usadas
        ]
        return salida, descartadas

    salida = []
    descartadas = []
    palabras_tdr = _palabras(texto_tdr)
    for propuesta in validas[:TOPE_LINEAS]:
        descripcion = " ".join(str(propuesta["descripcion"]).split())[:400]
        propias = {p for p in _palabras(descripcion) if len(p) >= 4}
        if not propias or len(propias & palabras_tdr) / len(propias) < _MINIMO_PARECIDO:
            descartadas.append(descripcion[:200])
            continue
        verificar = []
        try:
            cantidad = float(str(propuesta.get("cantidad")).replace(",", "."))
        except (TypeError, ValueError):
            cantidad = 0.0
        if cantidad <= 0 or not _cantidad_en_texto(cantidad, texto_tdr):
            cantidad = cantidad if cantidad > 0 else 1.0
            verificar.append("cantidad")
        unidad = " ".join(str(propuesta.get("unidad") or "").split())[:30]
        if unidad and not _en_texto(unidad, plano):
            unidad = ""
        if not unidad:
            verificar.append("unidad")
        linea = _linea({"descripcion": descripcion, "cantidad": cantidad, "unidad": unidad}, "tdr")
        if verificar:
            linea["verificar"] = verificar
        salida.append(linea)
    return salida, descartadas
