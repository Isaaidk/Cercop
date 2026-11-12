"""Anexos y monto de un proceso con oferta (OCDS), para armar la proforma.

El pedido del cliente: «que traiga los anexos para que con ellos se puedan realizar las proformas:
TDR, pliegos, actas —de las actas, solo la última— y que se sepa el monto del proceso».

La elección de anexos es la de `dominio.anexos.elegir_anexos`, la misma que usan las ínfimas: TDR,
pliego, especificaciones y **una sola acta**, la de `datePublished` más reciente. Lo que añade este
caso de uso es de dónde salen los documentos (la ficha del proceso en los datos abiertos), el monto
con su fuente y la explicación cuando la fuente no publica archivos, que hoy es lo normal (ver
`infraestructura/adaptadores/salida/fuentes/ocds_proceso.py`).

No importa infraestructura: depende de los puertos de `aplicacion/puertos/anexos.py`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any
from uuid import UUID

from contratacion.aplicacion.puertos.anexos import FichasDeProceso, RegistrosDeProceso
from contratacion.dominio.acceso import Vista, fuentes_para_vistas
from contratacion.dominio.anexos import elegir_anexos
from contratacion.dominio.errores import ErrorDominio, NoEncontrado, SinPermiso
from contratacion.dominio.presupuesto import numero_de

FUENTE_OCDS = "OCDS"

# El buscador público de procesos del portal transaccional, que es donde están los archivos. Se
# comprobó que responde (200, «Búsqueda de Procesos de Contratación»); no admite el código por la
# dirección, así que se da el código aparte para pegarlo.
BUSCADOR_PORTAL = (
    "https://www.compraspublicas.gob.ec/ProcesoContratacion/compras/PC/buscarProceso.cpe?sg=1"
)

AVISO_SIN_DOCUMENTOS = (
    "Los datos abiertos del SERCOP no publican los archivos de este proceso "
    "(TDR, pliego ni actas). "
    "Descárgalos del portal de compras públicas buscando el código del proceso."
)


class NoEsProcesoOcds(ErrorDominio):
    """Se pidieron los anexos de OCDS para un registro de otra fuente. Se traduce a 400."""

    codigo = "no_es_proceso_ocds"


def _monto_guardado(datos: Mapping[str, Any]) -> dict[str, Any] | None:
    """El monto que dejó la ingesta en `registro.datos`, por si la ficha no trae ninguno."""
    for campo, etiqueta in (
        ("presupuesto", "Presupuesto referencial (dato ingestado)"),
        ("monto", "Monto (dato ingestado)"),
    ):
        crudo = datos.get(campo)
        if crudo in (None, ""):
            continue
        numero = numero_de(str(crudo).strip())
        if numero is not None and numero > 0:
            return {
                "monto": round(numero, 2),
                "moneda": "USD",
                "fuente": f"registro.{campo}",
                "etiqueta_fuente": etiqueta,
            }
    return None


def _anexos(documentos: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    campos = ("tipo", "etiqueta_tipo", "nombre", "enlace", "fecha", "formato", "tipo_fuente")
    return [{c: d.get(c) for c in campos} for d in elegir_anexos(documentos)]


async def anexos_del_proceso(
    vistas: Iterable[Vista],
    registro_id: UUID,
    *,
    registros: RegistrosDeProceso,
    fichas: FichasDeProceso,
) -> dict[str, Any]:
    """Anexos elegidos, monto y aclaraciones de un proceso con oferta."""
    if FUENTE_OCDS not in fuentes_para_vistas(vistas):
        raise SinPermiso("No tienes acceso a los procesos con oferta.")

    registro = await registros.leer(registro_id)
    if registro is None:
        raise NoEncontrado("No se encontró ese proceso.")
    if str(registro.get("fuente") or "").upper() != FUENTE_OCDS:
        raise NoEsProcesoOcds(
            "Este registro no es un proceso con oferta: las ínfimas traen sus anexos por la ficha."
        )

    datos: Mapping[str, Any] = registro.get("datos") or {}
    ocid = str(datos.get("ocid") or registro.get("clave_natural") or "").strip()
    if not ocid:
        raise NoEncontrado("Este proceso no tiene identificador OCDS con el que buscarlo.")

    ficha = await fichas.leer(ocid)
    anexos = _anexos(ficha.get("documentos") or [])
    presupuesto = ficha.get("presupuesto") or _monto_guardado(datos)
    codigo = ficha.get("codigo") or datos.get("codigo") or ocid

    return {
        "registro_id": str(registro_id),
        "ocid": ocid,
        "codigo": codigo,
        "estado": ficha.get("estado"),
        "anexos": anexos,
        "presupuesto": presupuesto,
        "moneda": (presupuesto or {}).get("moneda") or "USD",
        "adjudicado": ficha.get("adjudicado"),
        "aclaraciones": list(ficha.get("aclaraciones") or []),
        "aviso": None if anexos else AVISO_SIN_DOCUMENTOS,
        "buscador_portal": None if anexos else BUSCADOR_PORTAL,
    }
