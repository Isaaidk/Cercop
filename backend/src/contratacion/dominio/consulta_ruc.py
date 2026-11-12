"""De lo que publica el SRI sobre un RUC a lo que se propone para el perfil de la empresa.

Es una **propuesta**: nada se guarda hasta que la persona la revisa y la aplica. El SRI no publica
todo lo que el perfil necesita (correo, teléfono, CIIU, RUP), así que esos campos no aparecen aquí
y la interfaz dice cuáles quedan por llenar.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# El SRI publica las provincias sin tilde («MANABI»). El perfil usa la grafía oficial.
_PROVINCIAS = (
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
_MINUSCULAS = {"de", "del", "la", "las", "los", "y", "e", "el"}
_ESTADOS_NORMALES = {"ACTIVO"}


def _titulo(texto: str | None) -> str:
    """«SANTO DOMINGO DE LOS TSÁCHILAS» → «Santo Domingo de los Tsáchilas»."""
    palabras = str(texto or "").strip().lower().split()
    return " ".join(
        palabra if indice and palabra in _MINUSCULAS else palabra.capitalize()
        for indice, palabra in enumerate(palabras)
    )


def _plano(texto: str) -> str:
    sin_marcas = unicodedata.normalize("NFD", str(texto or ""))
    return "".join(c for c in sin_marcas if not unicodedata.combining(c)).strip().lower()


_OFICIAL = {_plano(nombre): nombre for nombre in _PROVINCIAS}


def _provincia(texto: str | None) -> str:
    return _OFICIAL.get(_plano(str(texto or ""))) or _titulo(texto)


def _fecha(valor: Any) -> str | None:
    """«1997-12-02 00:00:00.0» → «1997-12-02». Vacío o ilegible, nada."""
    coincidencia = re.match(r"\d{4}-\d{2}-\d{2}", str(valor or ""))
    return coincidencia.group(0) if coincidencia else None


def _partes_direccion(completa: str | None) -> tuple[str, str, str, str]:
    """«PICHINCHA / QUITO / MARISCAL SUCRE / PÁEZ N22-53» → provincia, cantón, parroquia, calle."""
    partes = [parte.strip() for parte in str(completa or "").split("/")]
    partes += [""] * (4 - len(partes))
    provincia, canton, parroquia = partes[0], partes[1], partes[2]
    return provincia, canton, parroquia, " / ".join(p for p in partes[3:] if p)


def _tipo_persona(contribuyente: dict[str, Any]) -> str | None:
    tipo = str(contribuyente.get("tipoContribuyente") or "").upper()
    if "SOCIEDAD" in tipo or "JURID" in tipo:
        return "juridica"
    if "NATURAL" in tipo:
        return "natural"
    ruc = str(contribuyente.get("numeroRuc") or "")
    if len(ruc) == 13 and ruc[2].isdigit():
        return "natural" if int(ruc[2]) < 6 else "juridica"
    return None


def _regimen(contribuyente: dict[str, Any]) -> str:
    regimen = _titulo(contribuyente.get("regimen"))
    categoria = _titulo(contribuyente.get("categoria"))
    if regimen.lower() == "rimpe" or regimen.upper() == "RIMPE":
        regimen = "RIMPE"
    return f"{regimen} · {categoria}" if regimen and categoria else regimen


def propuesta_desde_sri(
    contribuyente: dict[str, Any], establecimientos: list[dict[str, Any]]
) -> dict[str, Any]:
    """Qué llenaría el perfil con lo que el SRI publica, y qué avisos conviene leer antes."""
    abiertos = [e for e in establecimientos if str(e.get("estado") or "").upper() == "ABIERTO"]
    matriz = next(
        (e for e in abiertos if str(e.get("matriz") or "").upper() == "SI"),
        abiertos[0] if abiertos else (establecimientos[0] if establecimientos else {}),
    )
    _, canton, _, calle = _partes_direccion(matriz.get("direccionCompleta"))
    fantasia = next(
        (
            str(e["nombreFantasiaComercial"]).strip()
            for e in [matriz, *abiertos]
            if str(e.get("nombreFantasiaComercial") or "").strip()
        ),
        "",
    )
    fechas = contribuyente.get("informacionFechasContribuyente") or {}
    identidad: dict[str, Any] = {
        "razon_social": str(contribuyente.get("razonSocial") or "").strip(),
        "nombre_comercial": _titulo(fantasia) if fantasia else "",
        "tipo_persona": _tipo_persona(contribuyente),
        "regimen_tributario": _regimen(contribuyente),
        "obligado_contabilidad": str(contribuyente.get("obligadoLlevarContabilidad") or "").upper()
        == "SI",
        "fecha_inicio_actividades": _fecha(fechas.get("fechaInicioActividades")),
        "direccion": calle.title() if calle else "",
        "ciudad": _titulo(canton),
    }
    identidad = {clave: valor for clave, valor in identidad.items() if valor not in ("", None)}

    representantes = [
        r for r in contribuyente.get("representantesLegales") or [] if isinstance(r, dict)
    ]
    representante = (
        {
            "tipo": "representante_legal",
            "nombre": _titulo(representantes[0].get("nombre")),
            "cedula": str(representantes[0].get("identificacion") or "").strip(),
            "cargo": "Representante legal",
            "principal": True,
        }
        if representantes and str(representantes[0].get("nombre") or "").strip()
        else None
    )

    vistas: set[tuple[str, str]] = set()
    cobertura: list[dict[str, str]] = []
    for establecimiento in abiertos:
        prov, cant, _, _ = _partes_direccion(establecimiento.get("direccionCompleta"))
        clave = (_provincia(prov), _titulo(cant))
        if clave[0] and clave not in vistas:
            vistas.add(clave)
            cobertura.append({"provincia": clave[0], "canton": clave[1]})

    actividad = str(contribuyente.get("actividadEconomicaPrincipal") or "").strip()
    estado = str(contribuyente.get("estadoContribuyenteRuc") or "").strip().upper()
    avisos: list[str] = []
    if estado and estado not in _ESTADOS_NORMALES:
        avisos.append(f"El SRI registra este RUC como {estado.lower()}.")
    if str(contribuyente.get("contribuyenteFantasma") or "").upper() == "SI":
        avisos.append("El SRI lo marca como contribuyente fantasma.")
    if str(contribuyente.get("transaccionesInexistente") or "").upper() == "SI":
        avisos.append("El SRI lo marca con transacciones inexistentes.")

    return {
        "ruc": str(contribuyente.get("numeroRuc") or "").strip(),
        "estado_sri": estado,
        "identidad": identidad,
        "representante": representante,
        "cobertura": cobertura[:24],
        "actividad": actividad,
        "avisos": avisos,
        "no_publica": ["Correo", "Teléfono", "Código CIIU", "Estado en el RUP"],
    }
