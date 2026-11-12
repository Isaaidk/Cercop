"""«Propuestas para ti»: las ínfimas abiertas que la empresa puede ofertar según su perfil.

Se apoya en el radar (`dominio/radar.py`): los mismos criterios comerciales, la misma comparación de
palabras y la misma nota de parecido. Cambian tres cosas, y cada una tiene su porqué:

- **El CPC coincide por el inicio del código**, no por un trozo cualquiera. El radar acepta que
  «73210» aparezca en medio de otro código; aquí eso sugeriría un proceso de otra familia, y una
  propuesta es una invitación a preparar una proforma, no una pista para revisar.
- **La ubicación se compara por pares provincia y cantón.** Si la empresa cubre «Pichincha (toda)» y
  «Guayas / Guayaquil», una ínfima en Cuenca no entra y una en Cayambe sí. Con dos listas sueltas,
  el cantón de una provincia acababa excluyendo todas las demás provincias.
- **Cada propuesta dice por qué se sugiere** con frases cortas en positivo («Tu CPC 73210 coincide»,
  «En tu provincia»). Es lo que lee una persona que no conoce la nota de 0 a 100.

Nada de esto predice la adjudicación: dice que la empresa **puede** ofertar, no que vaya a ganar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from contratacion.dominio.radar import (
    CriteriosComerciales,
    coincide_texto,
    plegar,
    puntuar,
)

# Un código de CPC más corto que esto ya no dice qué se compra: «73» es toda una división. Por
# debajo de cuatro dígitos no se acepta la coincidencia en ningún sentido.
_MINIMO_DIGITOS = 4

ORDENES = ("coincidencia", "cierre", "presupuesto")

# El Distrito Metropolitano de Quito se publica con su nombre largo y el perfil lo guarda como
# «Quito». Son el mismo cantón; sin esta equivalencia la cobertura «Pichincha / Quito» dejaba fuera
# justo las ínfimas de Quito.
_PREFIJOS_CANTON = ("distrito metropolitano de ",)


def solo_digitos(codigo: str | None) -> str:
    """«73210.00.1» y «732100001» se comparan igual: lo que cuenta es la secuencia de dígitos."""
    return re.sub(r"\D", "", str(codigo or ""))


def cpc_que_coinciden(propios: tuple[str, ...], ajenos: list[str]) -> list[str]:
    """CPC del perfil que encajan con alguno de la ínfima, por el inicio, en cualquier sentido.

    «73210» (perfil) encaja con «732100011» (ínfima): es una subcategoría de lo que la empresa
    ofrece. Al revés también: una ínfima que publica solo «7321» pide algo de esa clase, y la
    empresa con «73210» la puede ofertar.
    """
    codigos_ajenos = [solo_digitos(codigo) for codigo in ajenos]
    codigos_ajenos = [codigo for codigo in codigos_ajenos if len(codigo) >= _MINIMO_DIGITOS]
    halladas: list[str] = []
    for propio in propios:
        digitos = solo_digitos(propio)
        if len(digitos) < _MINIMO_DIGITOS:
            continue
        if any(ajeno.startswith(digitos) or digitos.startswith(ajeno) for ajeno in codigos_ajenos):
            halladas.append(propio)
    return list(dict.fromkeys(halladas))


def condiciones_cpc(propios: tuple[str, ...]) -> tuple[list[str], list[str]]:
    """Lo que necesita la consulta para hacer en SQL la misma comparación que `cpc_que_coinciden`.

    Devuelve dos listas: los códigos del perfil (la ínfima **empieza** por uno de ellos) y todos sus
    inicios de cuatro o más dígitos (la ínfima **es** uno de ellos). Así la base de datos
    descarta lo que no encaja sin traer cada fila, y la regla sigue viviendo en un solo sitio.
    """
    codigos: list[str] = []
    inicios: list[str] = []
    for propio in propios:
        digitos = solo_digitos(propio)
        if len(digitos) < _MINIMO_DIGITOS:
            continue
        codigos.append(digitos)
        inicios.extend(digitos[:largo] for largo in range(_MINIMO_DIGITOS, len(digitos) + 1))
    return list(dict.fromkeys(codigos)), list(dict.fromkeys(inicios))


@dataclass(frozen=True, slots=True)
class Zona:
    """Una fila de la cobertura del perfil. Cantón vacío significa «toda la provincia»."""

    provincia: str
    canton: str = ""


def zonas_desde_perfil(perfil: dict[str, Any]) -> tuple[Zona, ...]:
    """La cobertura del perfil sin repetir. Vacía significa «todo el país»."""
    zonas: dict[tuple[str, str], Zona] = {}
    for fila in perfil.get("cobertura") or []:
        provincia = str(fila.get("provincia") or "").strip()
        if not provincia:
            continue
        canton = str(fila.get("canton") or "").strip()
        zonas.setdefault((plegar(provincia), _canton_plegado(canton)), Zona(provincia, canton))
    return tuple(zonas.values())


def _canton_plegado(canton: str | None) -> str:
    plano = plegar(canton)
    for prefijo in _PREFIJOS_CANTON:
        if plano.startswith(prefijo):
            return plano[len(prefijo) :]
    return plano


def restringir_a_provincia(zonas: tuple[Zona, ...], provincia: str) -> tuple[Zona, ...]:
    """El filtro «provincia» de la pantalla: deja solo esa provincia.

    Si la empresa no la cubre, se busca igual en toda la provincia. Quien la elige en el filtro la
    está pidiendo a propósito, y responder «nada» sin decir por qué sería peor.
    """
    propias = tuple(zona for zona in zonas if plegar(zona.provincia) == plegar(provincia))
    return propias or (Zona(provincia),)


def lugar_en_zona(zonas: tuple[Zona, ...], provincia: str, canton: str) -> str | None:
    """Motivo positivo si la ínfima cae en la cobertura; `None` si queda fuera.

    Sin cobertura no se excluye nada y el motivo queda vacío: no hay nada que decirle a la persona.
    """
    if not zonas:
        return ""
    provincia_plana = plegar(provincia)
    canton_plano = _canton_plegado(canton)
    en_provincia = False
    for zona in zonas:
        if plegar(zona.provincia) != provincia_plana:
            continue
        if not zona.canton:
            en_provincia = True
        elif canton_plano and _canton_plegado(zona.canton) == canton_plano:
            return f"En tu cantón ({zona.canton})"
    return "En tu provincia" if en_provincia else None


def _numero(valor: Any) -> float | None:
    if valor is None or valor == "":
        return None
    try:
        return float(str(valor).replace(",", ""))
    except ValueError:
        return None


def _presupuesto(criterios: CriteriosComerciales, monto: float | None) -> tuple[bool, str]:
    """(entra, motivo). Un monto desconocido entra: la ínfima suele publicarlo en la ficha."""
    minimo, maximo = criterios.presupuesto_min, criterios.presupuesto_max
    if minimo is None and maximo is None:
        return True, ""
    if monto is None:
        return True, ""
    if minimo is not None and monto < minimo:
        return False, ""
    if maximo is not None and monto > maximo:
        return False, ""
    return True, "Dentro de tu presupuesto"


def evaluar(
    criterios: CriteriosComerciales,
    zonas: tuple[Zona, ...],
    fila: dict[str, Any],
) -> dict[str, Any] | None:
    """La propuesta lista para mostrar, o `None` si la empresa no la puede ofertar.

    Entra si coincide el CPC **o** lo que la empresa ofrece (palabras, productos); y, cuando el
    perfil los define, si cae en su cobertura y en su rango de presupuesto.
    """
    lugar = lugar_en_zona(zonas, str(fila.get("provincia") or ""), str(fila.get("canton") or ""))
    if lugar is None:
        return None
    monto = _numero(fila.get("presupuesto"))
    cabe, motivo_monto = _presupuesto(criterios, monto)
    if not cabe:
        return None
    codigos = cpc_que_coinciden(criterios.cpc, list(fila.get("cpc_codigos") or []))
    texto = " ".join(str(fila.get(clave) or "") for clave in ("objeto", "texto", "entidad"))
    palabras = coincide_texto(criterios, texto)
    if not codigos and not palabras:
        return None

    motivos: list[str] = []
    if codigos:
        lista = ", ".join(codigos[:3])
        motivos.append(
            f"Tu CPC {lista} coincide" if len(codigos) == 1 else f"Tus CPC {lista} coinciden"
        )
    if palabras:
        cortas = [palabra for palabra in palabras if len(palabra) <= 40][:3]
        if cortas:
            motivos.append("Menciona: " + ", ".join(cortas))
        elif not codigos:
            motivos.append("Coincide con lo que ofreces")
    if lugar:
        motivos.append(lugar)
    if motivo_monto:
        motivos.append(motivo_monto)

    # La zona ya se comprobó con la regla por pares; se le quita al radar para que no la vuelva a
    # juzgar con sus dos listas sueltas y reste puntos a una ínfima que sí está en la cobertura.
    nota = puntuar(replace(criterios, provincias=(), cantones=()), fila)
    puntos = int(nota["puntos"])
    # Un CPC que coincide por el inicio pesa más que una palabra suelta: es la misma clasificación
    # con la que la entidad publicó lo que necesita.
    if codigos and puntos < 100:
        puntos = min(100, puntos + 5)
    return {
        "id": fila.get("id"),
        "codigo": fila.get("codigo"),
        "objeto": fila.get("objeto") or "",
        "entidad": fila.get("entidad") or "",
        "provincia": fila.get("provincia") or "",
        "canton": fila.get("canton") or "",
        "plazo": fila.get("plazo"),
        "fecha_publicacion": fila.get("fecha_publicacion"),
        "presupuesto": monto,
        "cpc_codigos": list(fila.get("cpc_codigos") or []),
        "cpc_coinciden": codigos,
        "puntos": puntos,
        "motivos": motivos,
    }


def _marca_tiempo(valor: Any) -> float:
    if isinstance(valor, datetime):
        return valor.timestamp()
    if isinstance(valor, str) and valor:
        try:
            return datetime.fromisoformat(valor).timestamp()
        except ValueError:
            return float("inf")
    return float("inf")


def ordenar(propuestas: list[dict[str, Any]], orden: str) -> list[dict[str, Any]]:
    """Orden estable. El desempate es siempre «cierra antes»: lo urgente no se queda al fondo."""
    if orden == "cierre":
        return sorted(propuestas, key=lambda fila: (_marca_tiempo(fila["plazo"]), -fila["puntos"]))
    if orden == "presupuesto":
        # Sin presupuesto publicado va al final: «mayor presupuesto» promete montos.
        return sorted(
            propuestas,
            key=lambda fila: (
                fila["presupuesto"] is None,
                -(fila["presupuesto"] or 0),
                _marca_tiempo(fila["plazo"]),
            ),
        )
    return sorted(propuestas, key=lambda fila: (-fila["puntos"], _marca_tiempo(fila["plazo"])))


def _dinero(valor: float) -> str:
    entero = f"{valor:,.0f}".replace(",", ".")
    return f"${entero}"


def resumen_criterios(criterios: CriteriosComerciales, zonas: tuple[Zona, ...]) -> dict[str, Any]:
    """Con qué se armaron las propuestas, para la línea «Te sugerimos según: …»."""
    partes: list[str] = []
    if criterios.cpc:
        partes.append(f"{len(criterios.cpc)} CPC")
    if criterios.palabras:
        partes.append("lo que ofreces")
    provincias = list(dict.fromkeys(zona.provincia for zona in zonas))
    if provincias:
        partes.append(
            ", ".join(provincias[:3])
            + (f" y {len(provincias) - 3} más" if len(provincias) > 3 else "")
        )
    else:
        partes.append("todo el país")
    minimo, maximo = criterios.presupuesto_min, criterios.presupuesto_max
    if minimo is not None and maximo is not None:
        partes.append(f"de {_dinero(minimo)} a {_dinero(maximo)}")
    elif maximo is not None:
        partes.append(f"hasta {_dinero(maximo)}")
    elif minimo is not None:
        partes.append(f"desde {_dinero(minimo)}")
    return {
        "cpc": list(criterios.cpc),
        "total_cpc": len(criterios.cpc),
        "total_palabras": len(criterios.palabras),
        "provincias": provincias,
        "zonas": [{"provincia": zona.provincia, "canton": zona.canton} for zona in zonas],
        "presupuesto_min": minimo,
        "presupuesto_max": maximo,
        "texto": " · ".join(partes),
    }
