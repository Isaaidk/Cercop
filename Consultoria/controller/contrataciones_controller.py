"""
Controlador: Procesos de contratación publicados (API de Datos Abiertos - OCDS).

Complementa la vista de Necesidades (NCO) con los procesos publicados en la
plataforma y su detalle (estado, fecha límite de proformas, dirección y
contacto de la entidad contratante).
"""

from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from Consultoria.controller.utils import dataframe_a_excel, nombre_archivo
from Consultoria.model import sercop

router = APIRouter(prefix="/api", tags=["Procesos publicados (OCDS)"])

ANCHO_EXCEL = {
    "Tipo de Necesidad": 32,
    "Código Necesidad de Contratación": 32,
    "Fecha de Publicación": 20,
    "Provincia - Cantón": 34,
    "Descripción del Objeto de compra": 60,
    "Estado de la Necesidad": 20,
    "Fecha límite para la entrega de proformas": 24,
    "Entidad Contratante": 45,
    "Dirección de Entrega": 45,
    "Contacto": 45,
    "Enlace al detalle": 45,
    "Proveedor adjudicado": 40,
    "Monto": 16,
    "OCID": 45,
}

OPCIONES_DETALLE = """Se consulta el endpoint `record` del SERCOP para cada proceso
(estado, fecha límite de proformas, dirección y contacto). Es más lento: se
aplica sólo a los primeros resultados indicados en `limite_detalle`."""


@router.get("/contrataciones")
async def listar_contrataciones(
    fecha_inicio: str = Query("2025-01-01", description="YYYY-MM-DD"),
    fecha_fin: str = Query("2026-12-31", description="YYYY-MM-DD"),
    search: str = Query("salud", description="Palabras clave separadas por comas."),
    provincia: str | None = Query(None),
    canton: str | None = Query(None),
    estado: str | None = Query(None, description="En Curso | Finalizada | Cancelada | Desierto"),
    tipo: str | None = Query(None, description="Ej. Subasta Inversa Electrónica, Licitación..."),
    max_paginas: int = Query(3, ge=1, le=40, description="Páginas de 10 resultados por año/palabra."),
    incluir_detalle: bool = Query(False, description=OPCIONES_DETALLE),
    limite_detalle: int = Query(25, ge=1, le=100),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(25, ge=1, le=200),
):
    """Procesos publicados filtrados por fechas, provincia, cantón, tipo y estado."""
    resultado = await sercop.obtener_procesos_ocds(
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        palabras_clave=search,
        provincia=provincia,
        canton=canton,
        estado=estado,
        tipo=tipo,
        max_paginas=max_paginas,
        incluir_detalle=incluir_detalle,
        limite_detalle=limite_detalle,
    )
    avisos = resultado.attrs.get("avisos", [])

    if resultado.empty:
        return {
            "data": [],
            "total": 0,
            "pagina": pagina,
            "por_pagina": por_pagina,
            "total_paginas": 1,
            "tipos": [],
            "provincias": [],
            "cantones": [],
            "avisos": avisos,
        }

    total = len(resultado)
    total_paginas = max(1, -(-total // por_pagina))
    inicio = (pagina - 1) * por_pagina
    pagina_df = resultado.iloc[inicio : inicio + por_pagina]

    # `provincia` y `canton` viajan por separado para los filtros de la interfaz.
    columnas = (
        list(sercop.COLUMNAS_OCDS.keys())
        + ["provincia", "canton"]
        + list(sercop.COLUMNAS_EXTRA_OCDS.keys())
    )
    disponibles = [columna for columna in columnas if columna in pagina_df.columns]
    # `astype(object)` evita que los NaN se serialicen como `NaN` (JSON inválido).
    data = (
        pagina_df[disponibles]
        .astype(object)
        .where(pd.notnull(pagina_df[disponibles]), None)
        .to_dict(orient="records")
    )

    return {
        "data": data,
        "total": total,
        "pagina": pagina,
        "por_pagina": por_pagina,
        "total_paginas": total_paginas,
        "tipos": sorted(x for x in resultado["tipo_proceso"].unique() if x),
        "provincias": sorted(x for x in resultado["provincia"].unique() if x),
        "cantones": sorted(x for x in resultado["canton"].unique() if x),
        "detalle_aplicado": bool(incluir_detalle),
        "avisos": avisos,
    }


@router.get("/procesos/{ocid}/detalle")
async def detalle_proceso(ocid: str):
    """Detalle OCDS de un proceso (estado, proformas, dirección, contacto)."""
    detalle = await sercop.obtener_detalle_ocds(ocid)
    if not detalle:
        return {"error": f"No se encontró el proceso {ocid}."}
    return detalle


# --------------------------------------------------------------------------- #
# Compatibilidad con el endpoint histórico de exportación
# --------------------------------------------------------------------------- #
@router.get("/exportar")
async def exportar_excel(
    fecha_inicio: str = Query("2025-01-01"),
    fecha_fin: str = Query("2026-12-31"),
    search: str = Query("salud"),
    provincia: str | None = None,
    canton: str | None = None,
    estado: str | None = None,
    tipo: str | None = None,
    max_paginas: int = Query(3, ge=1, le=40),
    incluir_detalle: bool = False,
    limite_detalle: int = Query(25, ge=1, le=100),
):
    """Exporta a Excel los procesos publicados con los filtros actuales."""
    resultado = await sercop.obtener_procesos_ocds(
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        palabras_clave=search,
        provincia=provincia,
        canton=canton,
        estado=estado,
        tipo=tipo,
        max_paginas=max_paginas,
        incluir_detalle=incluir_detalle,
        limite_detalle=limite_detalle,
    )

    if resultado.empty:
        return {"error": "No hay datos para exportar con los filtros seleccionados."}

    export = sercop.exportar_ocds(resultado)
    buffer = dataframe_a_excel(export, "Procesos", ANCHO_EXCEL)
    archivo = nombre_archivo(["procesos_ocds", search, canton or provincia, estado])

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{archivo}.xlsx"'},
    )
