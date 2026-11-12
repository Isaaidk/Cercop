"""El presupuesto de un proceso y si la proforma cabe en él.

El cliente lo pidió así: «debe sacar el monto; el monto no puede superar el valor de la propuesta y
debe ser acorde». Una proforma de ínfima cuantía que pasa del presupuesto referencial no se puede
adjudicar, y una muy por debajo suele ser un error de tipeo (el total escrito como precio unitario,
un cero de menos). Aquí vive la regla, pura, para que la apliquen igual el backend al guardar y la
revisión antes de firmar; el panel la repite solo para avisar mientras se escribe.

**De dónde sale el monto**, en este orden de confianza (gana el primero que lo trae):

1. el **acta más reciente**, si fija un presupuesto: corrige a todo lo anterior;
2. la **ficha** del proceso (`registro.datos`): OCDS publica `planning.budget` como `presupuesto`;
   el portal de ínfimas trae `cantidad` x `valor_unitario`, que casi siempre llega en 0 y entonces
   no cuenta. El `monto` de OCDS es lo **adjudicado**, no el techo de la oferta: no se usa;
3. el texto del **TDR**, luego el del **pliego**, las **especificaciones** u otro anexo:
   «presupuesto referencial», «valor referencial», «valor estimado», «monto»… seguido de una
   cifra con moneda («$ 1.234,56», «USD 5.600,00», «5600.00 dólares»). Un hueco del formulario
   («$............») no es un monto y se ignora.

**IVA.** Si el texto dice «no incluye IVA», «sin IVA», «más IVA», se compara el **subtotal** de la
proforma (sin IVA). Si dice «incluye IVA» o «IVA incluido», se compara el **total** (con IVA). Si
no dice nada, se compara el subtotal: en la contratación pública ecuatoriana el presupuesto
referencial se publica, por regla, sin IVA, y comparar el total haría saltar el error por el
impuesto y no por el precio.

**La regla** (`comparar_con_presupuesto`):

- **error** si lo comparable (subtotal o total, según lo anterior) supera el presupuesto en más de
  medio centavo;
- **aviso** si usa menos del 50 % del presupuesto: no está prohibido, pero suele ser un error;
- **aviso** por cada línea con más de una unidad cuyo valor (precio x cantidad) pasa por sí solo del
  presupuesto aunque el precio unitario quepa: casi siempre es el total escrito como unitario.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from contratacion.dominio.errores import DatoInvalido

ACTA = "acta"
FICHA = "ficha"
TDR = "tdr"
PLIEGO = "pliego"
ESPECIFICACIONES = "especificaciones"
OTRO = "otro"

# Orden de confianza: ver el docstring del módulo.
PRIORIDAD_FUENTE = (ACTA, FICHA, TDR, PLIEGO, ESPECIFICACIONES, OTRO)
ETIQUETAS_FUENTE = {
    ACTA: "acta más reciente",
    FICHA: "ficha del proceso",
    TDR: "TDR",
    PLIEGO: "pliego",
    ESPECIFICACIONES: "especificaciones técnicas",
    OTRO: "documento del proceso",
}

USO_MINIMO = 0.5
_TOLERANCIA = 0.005
_MINIMO_CREIBLE = 1.0
_VENTANA = 160

# Misma longitud que el original: las posiciones del texto plano valen para el texto leído.
_PLANO = str.maketrans("áéíóúüñÁÉÍÓÚÜÑ", "aeiouunAEIOUUN")

# Las etiquetas que anuncian el presupuesto, de la más fiable a la más vaga. «monto» suelto puede
# ser el de la garantía: por eso va al final y solo cuenta si nada mejor trae cifra.
_ANCLAS = (
    "presupuesto referencial",
    "valor referencial",
    "monto referencial",
    "presupuesto estimado",
    "precio referencial",
    "valor estimado",
    "monto estimado",
    "presupuesto",
    "monto total",
    "valor total",
    "monto",
)
_ANCLA = re.compile(r"(?<![a-z])(" + "|".join(re.escape(a) for a in _ANCLAS) + r")(?![a-z])")

# Una cifra: con separador de miles («1.234,56», «1,234.56») o sin él («5600», «5600.00»). Los
# bordes impiden tomar un trozo de una partida presupuestaria («73.08.04») o de una fecha.
_NUMERO = r"\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"
_MONTO = re.compile(
    r"(?P<antes>(?:us\s?\$|\$|usd\.?|u\.s\.d\.?|dolares)\s*:?\s*)?"
    r"(?<![\d.,])(?P<numero>" + _NUMERO + r")(?![.,]?\d)"
    r"(?P<despues>\s*(?:usd|dolares|\$))?"
)
# Un hueco del formulario antes de la primera cifra: «$............», «USD ____», «[por completar]».
_HUECO = re.compile(r"[._…]{4,}|\[por completar\]")
_SIN_IVA = re.compile(
    r"(?:no\s+incluye|sin\s+incluir|no\s+incluido|excluye|excluido|sin|mas|\+)\s*(?:el\s+)?"
    r"(?:valor\s+del\s+)?(?:iva|impuesto\s+al\s+valor\s+agregado)"
    r"|iva\s+no\s+incluido|(?:antes|libre)\s+de\s+iva"
)
_CON_IVA = re.compile(
    r"(?:incluye|incluido|incluida|inclusive|con)\s*(?:el\s+)?(?:iva|impuesto\s+al\s+valor\s+agregado)"
    r"|iva\s+incluido"
)


def numero_de(crudo: str) -> float | None:
    """«1.234,56», «1,234.56», «5600.00», «1.234» → float. El último separador con dos cifras
    detrás es el decimal; con tres, es de miles («1.234» son mil doscientos treinta y cuatro)."""
    texto = crudo.strip()
    if "." in texto and "," in texto:
        decimal = "." if texto.rfind(".") > texto.rfind(",") else ","
        miles = "," if decimal == "." else "."
        texto = texto.replace(miles, "").replace(decimal, ".")
    else:
        for separador in (".", ","):
            if separador in texto:
                partes = texto.split(separador)
                if len(partes) > 2 or len(partes[-1]) == 3:
                    texto = texto.replace(separador, "")
                else:
                    texto = texto.replace(separador, ".")
    try:
        return float(texto)
    except ValueError:
        return None


def _iva(trozo: str) -> bool | None:
    """Qué dice del IVA el texto cercano al monto. «no incluye IVA» se mira antes que «incluye»."""
    if _SIN_IVA.search(trozo):
        return False
    if _CON_IVA.search(trozo):
        return True
    return None


def _primer_monto(plano: str, desde: int) -> re.Match[str] | None:
    """La primera cifra con forma de dinero tras la etiqueta, salvo que antes haya un hueco."""
    ventana = plano[desde : desde + _VENTANA]
    for hallado in _MONTO.finditer(ventana):
        antes = ventana[: hallado.start()]
        if _HUECO.search(antes):
            return None
        con_moneda = bool(hallado.group("antes") or hallado.group("despues"))
        con_centavos = re.search(r"[.,]\d{2}$", hallado.group("numero")) is not None
        if con_moneda or con_centavos:
            return hallado
    return None


def extraer_presupuesto(texto: str, fuente: str = TDR) -> dict[str, Any] | None:
    """El presupuesto que declara un documento, con su cita y lo que dice del IVA.

    Se prueba cada etiqueta en orden de fiabilidad; dentro de una misma etiqueta gana la primera
    aparición que trae cifra. Un monto menor de 1 dólar no es un presupuesto (es «$ 0,00» de un
    formulario sin llenar) y se descarta.
    """
    original = str(texto or "")
    plano = original.translate(_PLANO).lower()
    anclas = list(_ANCLA.finditer(plano))
    for etiqueta in _ANCLAS:
        for ancla in (a for a in anclas if a.group(1) == etiqueta):
            hallado = _primer_monto(plano, ancla.end())
            if hallado is None:
                continue
            valor = numero_de(hallado.group("numero"))
            if valor is None or valor < _MINIMO_CREIBLE:
                continue
            fin = ancla.end() + hallado.end()
            cita = " ".join(original[ancla.start() : min(len(original), fin + 60)].split())
            return {
                "valor": round(valor, 2),
                "fuente": fuente,
                "etiqueta_fuente": ETIQUETAS_FUENTE.get(fuente, fuente),
                "incluye_iva": _iva(plano[ancla.start() : fin + 80]),
                "cita": cita[:200],
            }
    return None


def presupuesto_de_ficha(fila: Mapping[str, Any]) -> dict[str, Any] | None:
    """El presupuesto que publica la ficha (`registro.datos`), si es un número creíble.

    OCDS trae `presupuesto` (`planning.budget.amount`). El portal de ínfimas trae `cantidad` y
    `valor_unitario`, casi siempre en 0: solo cuentan si los dos son positivos.
    """
    directo = (
        numero_de(str(fila.get("presupuesto") or "").strip()) if fila.get("presupuesto") else None
    )
    if directo is not None and directo >= _MINIMO_CREIBLE:
        return {
            "valor": round(directo, 2),
            "fuente": FICHA,
            "etiqueta_fuente": ETIQUETAS_FUENTE[FICHA],
            "incluye_iva": None,
            "cita": "Presupuesto referencial publicado en la ficha del proceso.",
        }
    cantidad = numero_de(str(fila.get("cantidad") or "0"))
    unitario = numero_de(str(fila.get("valor_unitario") or "0"))
    if cantidad and unitario and cantidad > 0 and unitario > 0:
        valor = round(cantidad * unitario, 2)
        if valor >= _MINIMO_CREIBLE:
            return {
                "valor": valor,
                "fuente": FICHA,
                "etiqueta_fuente": ETIQUETAS_FUENTE[FICHA],
                "incluye_iva": None,
                "cita": f"Cantidad {cantidad:g} x valor unitario {unitario:,.2f} de la ficha.",
            }
    return None


def elegir_presupuesto(candidatos: Iterable[Mapping[str, Any] | None]) -> dict[str, Any] | None:
    """El presupuesto que vale: el de la fuente más fiable (ver `PRIORIDAD_FUENTE`).

    Entre dos de la misma fuente gana el primero, que es el del anexo leído primero.
    """
    validos = [dict(c) for c in candidatos if c and float(c.get("valor") or 0) > 0]
    if not validos:
        return None

    def orden(candidato: dict[str, Any]) -> int:
        fuente = str(candidato.get("fuente") or OTRO)
        return (
            PRIORIDAD_FUENTE.index(fuente) if fuente in PRIORIDAD_FUENTE else len(PRIORIDAD_FUENTE)
        )

    return min(validos, key=orden)


def normalizar_presupuesto(valor: Any) -> dict[str, Any] | None:
    """El presupuesto que llega del navegador con la proforma, revisado: número positivo, fuente
    conocida e IVA como sí, no o sin dato. Cualquier otra cosa equivale a «sin presupuesto»."""
    if not isinstance(valor, Mapping):
        return None
    try:
        cifra = float(valor.get("valor") or 0)
    except (TypeError, ValueError):
        return None
    if not cifra > 0 or cifra > 1e12:
        return None
    fuente = str(valor.get("fuente") or OTRO)
    fuente = fuente if fuente in PRIORIDAD_FUENTE else OTRO
    incluye = valor.get("incluye_iva")
    return {
        "valor": round(cifra, 2),
        "fuente": fuente,
        "etiqueta_fuente": ETIQUETAS_FUENTE[fuente],
        "incluye_iva": incluye if isinstance(incluye, bool) else None,
        "cita": str(valor.get("cita") or "")[:200],
    }


def dinero(valor: float) -> str:
    """$1.234,56: como se escribe en Ecuador."""
    return "$" + f"{valor:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def comparar_con_presupuesto(
    cifras: Mapping[str, Any],
    lineas: Iterable[Mapping[str, Any]],
    presupuesto: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Cuánto del presupuesto usa la proforma y qué conviene revisar. Ver la regla en el módulo.

    Devuelve `supera` (bool), `mensaje` (el error, si supera), `avisos` ({codigo, texto}),
    `comparado`, `base` («sin IVA» o «con IVA») y `porcentaje` usado. Sin presupuesto, nada salta.
    """
    if not presupuesto or float(presupuesto.get("valor") or 0) <= 0:
        return {"supera": False, "mensaje": "", "avisos": [], "porcentaje": None}
    techo = float(presupuesto["valor"])
    con_iva = presupuesto.get("incluye_iva") is True
    comparado = float(cifras.get("total" if con_iva else "subtotal") or 0)
    base = "con IVA" if con_iva else "sin IVA"
    fuente = str(
        presupuesto.get("etiqueta_fuente")
        or ETIQUETAS_FUENTE.get(str(presupuesto.get("fuente")), "el proceso")
    )
    porcentaje = round(comparado / techo * 100, 1)
    supera = comparado > techo + _TOLERANCIA
    mensaje = (
        f"El {'total' if con_iva else 'subtotal'} de la proforma ({dinero(comparado)} {base}) "
        f"supera el presupuesto de la entidad ({dinero(techo)} {base}, según {fuente}). "
        "Baja los precios: una oferta por encima del presupuesto no se puede adjudicar."
        if supera
        else ""
    )
    avisos: list[dict[str, str]] = []
    if not supera and 0 < comparado < techo * USO_MINIMO:
        avisos.append(
            {
                "codigo": "presupuesto_bajo",
                "texto": (
                    f"La proforma usa solo el {porcentaje:g} % del presupuesto "
                    f"({dinero(comparado)} de {dinero(techo)} {base}). Revisa que no falte un "
                    "ítem ni un cero en algún precio."
                ),
            }
        )
    for numero, linea in enumerate(lineas, start=1):
        cantidad = float(linea.get("cantidad") or 0)
        precio = float(linea.get("precio_unitario") or 0)
        if cantidad > 1 and 0 < precio <= techo < precio * cantidad:
            avisos.append(
                {
                    "codigo": "precio_unitario",
                    "texto": (
                        f"La línea {numero}: {cantidad:g} x {dinero(precio)} pasa sola del "
                        f"presupuesto ({dinero(techo)}). ¿Escribiste el total de la línea como "
                        "precio unitario?"
                    ),
                }
            )
    return {
        "supera": supera,
        "mensaje": mensaje,
        "avisos": avisos,
        "comparado": round(comparado, 2),
        "base": base,
        "porcentaje": porcentaje,
    }


def exigir_dentro_del_presupuesto(
    cifras: Mapping[str, Any],
    lineas: Iterable[Mapping[str, Any]],
    presupuesto: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Como `comparar_con_presupuesto`, pero una proforma que supera el presupuesto no se guarda."""
    comparacion = comparar_con_presupuesto(cifras, lineas, presupuesto)
    if comparacion["supera"]:
        raise DatoInvalido(comparacion["mensaje"])
    return comparacion
