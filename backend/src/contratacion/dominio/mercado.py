"""Cifras de mercado a partir de procesos ya publicados.

El monto de una adjudicación es el total del proceso, no un precio por unidad. Por eso las
estadísticas se calculan dentro de un mismo CPC: mezclar un contrato de un equipo con uno de cien
produciría un promedio que no sirve para cotizar.
"""

from __future__ import annotations

from typing import Any

AVISO_PRECIOS = (
    "Estas cifras son el monto total de cada proceso, no un precio por unidad. "
    "Cada grupo es un solo CPC. Un contrato de un equipo y otro de cien no se comparan entre sí: "
    "el objeto de cada proceso está en la lista."
)

AVISO_SIN_CPC = (
    "Estos procesos coinciden en la búsqueda y no traen un CPC común. "
    "El promedio junta totales de contratos que pueden tener cantidades distintas."
)


def resumir(montos: list[float]) -> dict[str, Any] | None:
    """Mínimo, máximo, promedio y mediana. Vacío si no hay montos."""
    if not montos:
        return None
    ordenados = sorted(float(monto) for monto in montos)
    cantidad = len(ordenados)
    mitad = cantidad // 2
    mediana = ordenados[mitad]
    if cantidad % 2 == 0:
        mediana = (ordenados[mitad - 1] + ordenados[mitad]) / 2
    return {
        "n": cantidad,
        "minimo": ordenados[0],
        "maximo": ordenados[-1],
        "promedio": sum(ordenados) / cantidad,
        "mediana": mediana,
    }


def _clave_cpc(fila: dict[str, Any]) -> str:
    for codigo in fila.get("cpc") or []:
        limpio = str(codigo or "").strip()
        if limpio:
            return limpio
    return ""


def _cortar(filas: list[dict[str, Any]], campo: str, tope: int = 8) -> list[dict[str, Any]]:
    cubetas: dict[str, list[float]] = {}
    for fila in filas:
        nombre = str(fila.get(campo) or "").strip() or "Sin dato"
        cubetas.setdefault(nombre, []).append(float(fila["monto"]))
    salida = [{"nombre": nombre, **(resumir(valores) or {})} for nombre, valores in cubetas.items()]
    salida.sort(key=lambda item: (-int(item["n"]), str(item["nombre"])))
    return salida[:tope]


def agrupar_precios(filas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Un resumen por CPC. Los procesos sin CPC quedan en un grupo aparte, con su propio aviso."""
    cubetas: dict[str, list[dict[str, Any]]] = {}
    orden: list[str] = []
    for fila in filas:
        if not fila.get("monto"):
            continue
        clave = _clave_cpc(fila)
        if clave not in cubetas:
            orden.append(clave)
            cubetas[clave] = []
        cubetas[clave].append(fila)
    grupos = []
    for clave in orden:
        del_grupo = cubetas[clave]
        grupos.append(
            {
                "cpc": clave,
                "mismo_cpc": bool(clave),
                "aviso": AVISO_PRECIOS if clave else AVISO_SIN_CPC,
                "resumen": resumir([float(fila["monto"]) for fila in del_grupo]),
                "por_anio": _cortar(del_grupo, "anio"),
                "por_entidad": _cortar(del_grupo, "entidad"),
                "procesos": [
                    {
                        "codigo": fila.get("codigo") or "",
                        "objeto": fila.get("objeto") or "",
                        "entidad": fila.get("entidad") or "",
                        "proveedor": fila.get("proveedor") or "",
                        "monto": fila.get("monto"),
                        "anio": fila.get("anio") or "",
                        "tipo_proceso": fila.get("tipo_proceso") or "",
                    }
                    for fila in del_grupo[:30]
                ],
            }
        )
    return grupos


def requisitos_de(documentos: list[Any] | None) -> list[str]:
    """Nombres de documentos y campos pedidos, sin repetir."""
    vistos: list[str] = []
    for documento in documentos or []:
        candidatos: list[str] = []
        if isinstance(documento, dict):
            nombre = str(documento.get("nombre") or "").strip()
            if nombre:
                candidatos.append(nombre)
            for campo in documento.get("campos_pedido") or []:
                texto = str(campo or "").strip()
                if texto:
                    candidatos.append(texto)
        elif documento:
            candidatos.append(str(documento).strip())
        for texto in candidatos:
            if texto and texto not in vistos:
                vistos.append(texto)
    return vistos[:12]
