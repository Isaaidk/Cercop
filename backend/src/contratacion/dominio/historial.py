"""Lo que los datos abiertos de contratación dicen de una empresa, para rellenar su perfil.

El SERCOP no publica el RUP (qué CPC tiene habilitados cada proveedor), pero sí publica cada
contratación con su adjudicatario y los CPC de lo adjudicado. De ahí sale una aproximación honesta:
**los CPC con los que la empresa ya ha vendido al Estado** y los contratos que puede declarar como
experiencia. Es historial, no habilitación: lo que figura en el RUP puede ser más amplio.

Se confía en el RUC, no en el nombre: la búsqueda por nombre trae homónimos, y un contrato solo
cuenta si su adjudicatario trae ese RUC.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from contratacion.dominio.perfil import clasificar_objeto

# Formas societarias: el SERCOP las escribe de mil maneras («S.A.», «SA», «CIA. LTDA.»). Se quitan
# para que la búsqueda por nombre no falle por una coma o un punto.
_FORMAS = {"sa", "s", "a", "cia", "ltda", "limitada", "compania", "sas", "ca", "cl", "eirl", "cia."}
_MAX_TERMINO = 80


def termino_de_busqueda(razon_social: str) -> str:
    """Un trozo del nombre que el SERCOP también tenga escrito igual, para el filtro `supplier`.

    El filtro busca el texto tal cual dentro del nombre del adjudicatario. Por eso se corta en la
    primera comilla, paréntesis o coma —«… LA CANASTA BASICA "ASOCANASTA"» queda en «… LA CANASTA
    BASICA»— y solo se quitan las formas societarias del **final** («S.A.», «CIA. LTDA.»), que el
    SERCOP escribe de mil maneras. Las tildes y el resto se dejan como están.
    """
    cabeza = re.split(r"[\"“”(,]", str(razon_social or "").upper())[0]
    palabras = cabeza.split()
    while palabras and re.sub(r"\W", "", palabras[-1]).lower() in _FORMAS:
        palabras.pop()
    return " ".join(palabras)[:_MAX_TERMINO].strip(" .")


def _releases(carga: Any) -> list[dict[str, Any]]:
    """El `record` de OCDS llega como `releases` o como `records[].releases`: se aceptan las dos."""
    if not isinstance(carga, dict):
        return []
    salida = [r for r in carga.get("releases") or [] if isinstance(r, dict)]
    for registro in carga.get("records") or []:
        if isinstance(registro, dict):
            salida.extend(r for r in registro.get("releases") or [] if isinstance(r, dict))
    return salida


def contrato_de(carga: Any, ruc: str) -> dict[str, Any] | None:
    """Resume un proceso **solo si** su adjudicatario es ese RUC. Si no, `None`."""
    for release in _releases(carga):
        propios = [
            parte
            for parte in release.get("parties") or []
            if isinstance(parte, dict)
            and "supplier" in (parte.get("roles") or [])
            and ruc in str(parte.get("id") or parte.get("identifier", {}).get("id") or "")
        ]
        adjudicados = [
            a
            for a in release.get("awards") or []
            if isinstance(a, dict)
            and any(ruc in str(s.get("id") or "") for s in a.get("suppliers") or [])
        ]
        if not propios and not adjudicados:
            continue
        cpc: dict[str, str] = {}
        productos: list[str] = []
        monto = 0.0
        for adjudicacion in adjudicados or release.get("awards") or []:
            valor = (adjudicacion.get("value") or {}).get("amount")
            if isinstance(valor, (int, float)):
                monto += float(valor)
            for item in adjudicacion.get("items") or []:
                nombre = " ".join(str(item.get("description") or "").split())
                if nombre and nombre not in productos:
                    productos.append(nombre)
                clasificacion = item.get("classification") or {}
                es_cpc = str(clasificacion.get("scheme") or "").upper() == "CPC"
                if es_cpc and clasificacion.get("id"):
                    cpc[str(clasificacion["id"])] = str(clasificacion.get("description") or "")
        comprador = release.get("buyer") or {}
        tender = release.get("tender") or {}
        return {
            "ocid": release.get("ocid"),
            "entidad": str(comprador.get("name") or "").strip(),
            "titulo": str(tender.get("title") or "").strip(),
            "descripcion": " ".join(str(tender.get("description") or "").split()),
            "fecha": str(release.get("date") or "")[:10],
            "monto": monto or tender.get("value", {}).get("amount"),
            "cpc": cpc,
            "productos": productos,
            "categoria": str(tender.get("mainProcurementCategory") or ""),
            "metodo": str(tender.get("procurementMethodDetails") or ""),
        }
    return None


_CATEGORIAS = {"goods": "bienes", "services": "servicios", "works": "obras"}


def resumir_historial(
    ruc: str, contratos: list[dict[str, Any]], *, total: int, revisados: int, termino: str
) -> dict[str, Any]:
    """CPC más frecuentes y contratos que se pueden declarar como experiencia."""
    veces: Counter[str] = Counter()
    nombres: dict[str, str] = {}
    for contrato in contratos:
        for codigo, descripcion in contrato["cpc"].items():
            veces[codigo] += 1
            nombres.setdefault(codigo, descripcion)

    experiencia = []
    for contrato in sorted(contratos, key=lambda c: c["fecha"], reverse=True)[:8]:
        codigos = list(contrato["cpc"])
        # «Orden de compra para adquirir los siguientes productos…» no dice nada: se prefiere lo
        # que se compró.
        generico = contrato["descripcion"].lower().startswith(("orden de compra", "compra de"))
        objeto = (
            "; ".join(contrato["productos"][:3])
            if contrato["productos"] and (generico or not contrato["descripcion"])
            else contrato["descripcion"] or contrato["titulo"]
        )
        experiencia.append(
            {
                "entidad": contrato["entidad"],
                "objeto": objeto[:240],
                "monto": contrato["monto"],
                "anio": int(contrato["fecha"][:4]) if contrato["fecha"][:4].isdigit() else None,
                "cpc": codigos[0] if codigos else "",
                "tipo_contratacion": _CATEGORIAS.get(contrato["categoria"])
                or clasificar_objeto(contrato["categoria"]),
            }
        )

    return {
        "ruc": ruc,
        "termino": termino,
        "contratos_total": total,
        "revisados": revisados,
        "verificados": len(contratos),
        "monto_revisado": round(sum(float(c["monto"] or 0) for c in contratos), 2),
        "cpc": [
            {"codigo": codigo, "descripcion": nombres[codigo], "veces": cantidad}
            for codigo, cantidad in veces.most_common(15)
        ],
        "experiencia": experiencia,
        # Los procesos verificados por RUC, con su código y fecha: los usa el asistente para
        # contestar «¿qué ha ganado este RUC?». El perfil no los lee; añadirlos no le cambia nada.
        "procesos": [
            {
                "ocid": contrato.get("ocid") or "",
                "objeto": (contrato["descripcion"] or contrato["titulo"])[:240],
                "titulo": contrato["titulo"],
                "entidad": contrato["entidad"],
                "fecha": contrato["fecha"],
                "monto": contrato["monto"],
            }
            for contrato in sorted(contratos, key=lambda c: c["fecha"], reverse=True)
        ],
        "aviso": (
            "Es lo que figura como adjudicado a tu RUC en los datos abiertos de los últimos años. "
            "No es tu habilitación en el RUP: ese registro no tiene consulta pública."
        ),
    }
