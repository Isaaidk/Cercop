"""Revisión de una proforma antes de enviarla o firmarla.

La proforma de ínfima cuantía «tendrá los efectos de la oferta» (art. 149 del RGLOSNCP, según el
material de capacitación del SERCOP). Una oferta incompleta se rechaza, así que aquí se separa lo
que impide enviarla (`errores`) de lo que conviene revisar (`avisos`). Nada de esto sustituye la
lectura del TDR: solo comprueba que el documento tenga lo que una entidad suele exigir.
"""

from __future__ import annotations

import re
from typing import Any

from contratacion.dominio.presupuesto import comparar_con_presupuesto, normalizar_presupuesto

IVA_VIGENTE = 15.0
_IVA_USUALES = (0.0, IVA_VIGENTE)
_SIN_RESPUESTA = ("por confirmar", "sin respuesta")


def ruc_valido(ruc: str) -> bool:
    """Forma del RUC ecuatoriano: 13 dígitos, provincia 01-24 o 30, tercer dígito 0-6 o 9,
    y un establecimiento que no sea 000. No consulta el SRI."""
    if not re.fullmatch(r"\d{13}", ruc or ""):
        return False
    provincia = int(ruc[:2])
    if not (1 <= provincia <= 24 or provincia == 30):
        return False
    if int(ruc[2]) in (7, 8):
        return False
    return ruc[10:] != "000"


def _hallazgo(codigo: str, texto: str, donde: str) -> dict[str, str]:
    return {"codigo": codigo, "texto": texto, "donde": donde}


def _texto(valor: Any) -> str:
    return str(valor or "").strip()


def verificar_proforma(documento: dict[str, Any]) -> dict[str, Any]:
    """Qué le falta a la proforma. `donde` dice en qué paso del armado se corrige."""
    extras = documento.get("extras") or {}
    empresa = extras.get("empresa") or {}
    condiciones = extras.get("condiciones") or {}
    cifras = documento.get("cifras") or {}
    lineas = documento.get("lineas") or []
    es_oferta = documento.get("tipo") == "proforma"
    errores: list[dict[str, str]] = []
    avisos: list[dict[str, str]] = []

    if not _texto(empresa.get("razon_social")):
        errores.append(_hallazgo("razon_social", "Falta la razón social del oferente.", "empresa"))
    if not ruc_valido(_texto(empresa.get("ruc"))):
        errores.append(
            _hallazgo(
                "ruc",
                "El RUC debe tener 13 dígitos, con provincia válida y establecimiento distinto "
                "de 000.",
                "empresa",
            )
        )
    if not (_texto(empresa.get("email")) or _texto(empresa.get("telefono"))):
        errores.append(
            _hallazgo("contacto", "Indica un correo o un teléfono de contacto.", "empresa")
        )
    if not _texto(empresa.get("representante")):
        avisos.append(
            _hallazgo("representante", "Falta el representante legal que firma.", "empresa")
        )
    if not _texto(empresa.get("direccion")):
        avisos.append(_hallazgo("direccion", "Falta la dirección del oferente.", "empresa"))

    if not _texto(documento.get("entidad")):
        errores.append(_hallazgo("entidad", "Falta la entidad contratante.", "proceso"))
    if not _texto(documento.get("objeto")):
        errores.append(_hallazgo("objeto", "Falta el objeto de la contratación.", "proceso"))
    if es_oferta and not _texto(extras.get("codigo")):
        avisos.append(
            _hallazgo(
                "codigo",
                "Falta el código del proceso; el formulario de integridad lo cita.",
                "proceso",
            )
        )
    if not _texto(extras.get("fecha")):
        errores.append(_hallazgo("fecha", "Falta la fecha de emisión.", "condiciones"))

    if not lineas:
        errores.append(_hallazgo("lineas", "No hay productos ni servicios.", "detalle"))
    for numero, linea in enumerate(lineas, start=1):
        if not _texto(linea.get("descripcion")):
            errores.append(
                _hallazgo("descripcion", f"La línea {numero} no tiene descripción.", "detalle")
            )
        if float(linea.get("cantidad") or 0) <= 0:
            errores.append(
                _hallazgo("cantidad", f"La línea {numero} no tiene cantidad.", "detalle")
            )
        if float(linea.get("precio_unitario") or 0) <= 0:
            errores.append(
                _hallazgo("precio", f"La línea {numero} no tiene precio unitario.", "detalle")
            )
        if not _texto(linea.get("unidad")):
            avisos.append(_hallazgo("unidad", f"La línea {numero} no indica la unidad.", "detalle"))
    if cifras and lineas:
        esperado = round(
            sum(
                float(linea.get("cantidad") or 0) * float(linea.get("precio_unitario") or 0)
                for linea in lineas
            ),
            2,
        )
        if abs(esperado - float(cifras.get("subtotal") or 0)) > 0.01:
            errores.append(
                _hallazgo(
                    "totales",
                    "Los totales no coinciden con las líneas. Guarda la proforma otra vez.",
                    "detalle",
                )
            )
    # El presupuesto viaja en `extras` desde que se lee el proceso (ver `dominio/presupuesto.py`):
    # pasarse es un error porque la oferta no se puede adjudicar; quedarse muy corto, un aviso.
    presupuesto = normalizar_presupuesto(extras.get("presupuesto"))
    if cifras and lineas and presupuesto:
        comparacion = comparar_con_presupuesto(cifras, lineas, presupuesto)
        if comparacion["supera"]:
            errores.append(_hallazgo("presupuesto", comparacion["mensaje"], "detalle"))
        for hallado in comparacion["avisos"]:
            avisos.append(_hallazgo(hallado["codigo"], hallado["texto"], "detalle"))
    iva = float(cifras.get("impuesto_porcentaje") or documento.get("impuesto_porcentaje") or 0)
    if cifras and iva not in _IVA_USUALES:
        avisos.append(
            _hallazgo(
                "iva",
                f"El IVA es {iva:g} %. La tarifa general vigente es {IVA_VIGENTE:g} %; "
                "usa otra solo si el bien o servicio tiene una tarifa distinta.",
                "detalle",
            )
        )

    for clave, etiqueta in (
        ("validez", "la vigencia de la oferta"),
        ("plazo_entrega", "el plazo de entrega"),
        ("forma_pago", "la forma de pago"),
    ):
        if not _texto(condiciones.get(clave)):
            errores.append(_hallazgo(clave, f"Falta {etiqueta}.", "condiciones"))
    for clave, etiqueta in (("lugar_entrega", "el lugar de entrega"), ("garantia", "la garantía")):
        if not _texto(condiciones.get(clave)):
            avisos.append(_hallazgo(clave, f"Falta {etiqueta}, si el TDR la pide.", "condiciones"))

    cumplimiento = [f for f in extras.get("cumplimiento") or [] if isinstance(f, dict)]
    sin_responder = [
        f
        for f in cumplimiento
        if not _texto(f.get("como_cumple"))
        or _texto(f.get("como_cumple")).lower() in _SIN_RESPUESTA
    ]
    if sin_responder:
        avisos.append(
            _hallazgo(
                "cumplimiento",
                f"{len(sin_responder)} requisito(s) del TDR sin respuesta.",
                "cumplimiento",
            )
        )
    if es_oferta and extras.get("integridad") is False:
        avisos.append(
            _hallazgo(
                "integridad",
                "La proforma va sin el Formulario de Perfil de Integridad. Inclúyelo si la "
                "entidad lo pide con la oferta.",
                "condiciones",
            )
        )

    return {
        "estado": "incompleta" if errores else "lista",
        "errores": errores,
        "avisos": avisos,
    }
