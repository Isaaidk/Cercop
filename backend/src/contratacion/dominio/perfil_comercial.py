"""Qué vende la empresa, en pocas líneas: lo que el asistente le cuenta al modelo y a la persona.

El asistente decía «no tienes nada cargado» a empresas con el perfil completo. Leía solo la **lista
de CPC del buscador** —la que se vacía con «Vaciar la lista» al limpiar los filtros de búsqueda— y
la tomaba por todo lo que la empresa hace. Pero lo que la empresa vende está en su **perfil**: los
CPC de lo ofrecido y de la experiencia (el RUP), las palabras clave comerciales, los productos y
servicios, la cobertura y la dedicación. Las propuestas ya se calculaban así
(`radar.criterios_desde_perfil`); este resumen usa la misma fuente para que el chat diga lo mismo
que la pantalla «Propuestas para ti», tenga o no filtros el buscador.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from contratacion.dominio.radar import cpc_del_perfil

MAX_CPC = 20
MAX_PALABRAS = 15


@dataclass(frozen=True, slots=True)
class PerfilComercial:
    nombre: str
    ruc: str
    cpc: tuple[str, ...]
    palabras: tuple[str, ...]
    provincias: tuple[str, ...]
    dedicaciones: tuple[str, ...]
    presupuesto: str

    @property
    def tiene_datos(self) -> bool:
        """¿Sabemos qué vende? Con un CPC o una palabra ya se pueden recomendar procesos."""
        return bool(self.cpc or self.palabras)


def _limpio(valor: Any) -> str:
    return " ".join(str(valor or "").split())


def _sin_repetir(textos: list[str], tope: int) -> tuple[str, ...]:
    vistos: dict[str, str] = {}
    for texto in textos:
        limpio = _limpio(texto)
        if len(limpio) >= 3 and limpio.lower() not in vistos:
            vistos[limpio.lower()] = limpio
    return tuple(list(vistos.values())[:tope])


def _dinero(valor: Any) -> str:
    try:
        return f"${float(valor):,.0f}"
    except (TypeError, ValueError):
        return ""


def resumen_comercial(perfil: dict[str, Any], lista_cpc: list[str]) -> PerfilComercial:
    """El perfil primero; la lista de CPC del buscador solo suma, nunca reemplaza."""
    codigos: list[str] = list(cpc_del_perfil(perfil))
    palabras: list[str] = [str(f.get("texto") or "") for f in perfil.get("palabras") or []]
    palabras += [str(f.get("nombre") or "") for f in perfil.get("ofertas") or []]
    for texto in lista_cpc:
        limpio = _limpio(texto)
        if any(caracter.isdigit() for caracter in limpio):
            codigos.append(limpio)
        else:
            palabras.append(limpio)
    provincias = sorted(
        {_limpio(f.get("provincia")) for f in perfil.get("cobertura") or [] if f.get("provincia")}
    )
    dedicaciones = [
        " · ".join(
            parte
            for parte in (_limpio(f.get("tipo_contratacion")), _limpio(f.get("tipo_procedimiento")))
            if parte
        )
        for f in perfil.get("dedicaciones") or []
    ]
    minimo, maximo = _dinero(perfil.get("presupuesto_min")), _dinero(perfil.get("presupuesto_max"))
    presupuesto = (
        f"{minimo or '$0'} a {maximo}" if maximo else (f"desde {minimo}" if minimo else "")
    )
    return PerfilComercial(
        nombre=_limpio(
            perfil.get("nombre_comercial") or perfil.get("razon_social") or perfil.get("nombre")
        ),
        ruc=_limpio(perfil.get("ruc")),
        cpc=tuple(dict.fromkeys(c for c in codigos if c))[:MAX_CPC],
        palabras=_sin_repetir(palabras, MAX_PALABRAS),
        provincias=tuple(provincias),
        dedicaciones=_sin_repetir(dedicaciones, 6),
        presupuesto=presupuesto,
    )
