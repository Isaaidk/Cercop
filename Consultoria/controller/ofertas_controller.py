"""
Controlador: Ofertas / Procesos publicados en recepción de ofertas.

Equivale a la búsqueda de procesos del portal SOCE
(`PC/buscarProceso.cpe`), usando la API oficial de Datos Abiertos OCDS porque el
portal clásico exige captcha y sesión.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from Consultoria.controller.utils import dataframe_a_excel, nombre_archivo
from Consultoria.model import ofertas

router = APIRouter(prefix="/api/ofertas", tags=["Ofertas / Procesos publicados"])

ANCHO_EXCEL = {
    "Tipo de Proceso": 32,
    "Código del Proceso": 34,
    "Entidad Contratante": 46,
    "Provincia - Cantón": 34,
    "Objeto de Contratación": 60,
    "Estado del Proceso": 20,
    "Fecha de Publicación": 20,
    "Inicio de Recepción de Ofertas": 24,
    "Fecha límite de Recepción de Ofertas": 24,
    "Días restantes": 14,
    "Presupuesto Referencial": 20,
    "Dirección": 45,
    "Contacto": 45,
    "Enlace al detalle": 45,
    "Proveedor adjudicado": 40,
    "OCID": 45,
}

NOTA_DETALLE = (
    "Las fechas de recepción de ofertas y el estado provienen del detalle de cada "
    "proceso (`record`), por lo que se consultan solo para los primeros `analizar` "
    "resultados (el SERCOP limita la tasa de peticiones)."
)


async def _consultar(
    search: str,
    fecha_inicio: str,
    fecha_fin: str,
    provincia: str | None,
    canton: str | None,
    estado: str | None,
    tipo: str | None,
    solo_abiertas: bool,
    cierra_en_horas: float | None,
    analizar: int,
    max_paginas: int,
    orden: str,
    dir_orden: str,
    incluir_detalle: bool,
):
    df, avisos, analizados = await ofertas.obtener_ofertas(
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        palabras_clave=search,
        provincia=provincia,
        canton=canton,
        estado=estado,
        tipo=tipo,
        solo_abiertas=solo_abiertas,
        cierra_en_horas=cierra_en_horas,
        analizar=analizar,
        max_paginas=max_paginas,
        incluir_detalle=incluir_detalle,
    )
    return ofertas.ordenar(df, orden, dir_orden), avisos, analizados


@router.get("")
async def listar_ofertas(
    search: str = Query("mantenimiento", description="Palabras clave separadas por comas."),
    fecha_inicio: str = Query(..., description="Fecha de publicación desde (YYYY-MM-DD)."),
    fecha_fin: str = Query(..., description="Fecha de publicación hasta (YYYY-MM-DD)."),
    provincia: str | None = None,
    canton: str | None = None,
    estado: str | None = Query(None, description="En Curso | Finalizada | Cancelada | Desierto"),
    tipo: str | None = Query(None, description="Ej. Subasta Inversa Electrónica, Licitación..."),
    solo_abiertas: bool = Query(
        False,
        description="Solo procesos cuyo plazo de ofertas está publicado y sigue vigente.",
    ),
    cierra_en_horas: float | None = Query(None, ge=0, description="Ofertas que cierran en N horas."),
    incluir_detalle: bool = Query(
        False,
        description=(
            "Consulta el detalle (`record`) de los primeros `analizar` procesos para "
            "obtener estado, fechas de ofertas y nº de ofertas. Es lento (límite de "
            "tasa del SERCOP) y se activa solo cuando se solicita."
        ),
    ),
    analizar: int = Query(10, ge=1, le=60, description="Procesos a los que se consulta el detalle."),
    max_paginas: int = Query(3, ge=1, le=40, description="Páginas de 10 resultados por año/palabra."),
    orden: str = Query("fecha_publicacion"),
    dir_orden: str = Query("desc", alias="dir", pattern="^(asc|desc)$"),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(25, ge=1, le=200),
):
    """Tabla paginada de procesos en recepción de ofertas."""
    filtrado, avisos, analizados = await _consultar(
        search, fecha_inicio, fecha_fin, provincia, canton, estado, tipo,
        solo_abiertas, cierra_en_horas, analizar, max_paginas, orden, dir_orden,
        incluir_detalle,
    )

    pagina_df, total, total_paginas = ofertas.paginar(filtrado, pagina, por_pagina)

    if analizados and total and analizados < total:
        avisos = avisos + [
            f"Se analizaron {analizados} de {total} procesos: aumente «Procesos a "
            "detallar» o acote los filtros para ver más fechas de ofertas."
        ]

    return {
        "data": ofertas.a_registros(pagina_df, ofertas.columnas_json()),
        "total": total,
        "pagina": pagina,
        "por_pagina": por_pagina,
        "total_paginas": total_paginas,
        "analizados": analizados,
        "catalogo": ofertas.catalogo(filtrado),
        "avisos": avisos,
        "nota": NOTA_DETALLE,
    }


@router.get("/exportar")
async def exportar_ofertas(
    search: str = Query("mantenimiento"),
    fecha_inicio: str = Query(...),
    fecha_fin: str = Query(...),
    provincia: str | None = None,
    canton: str | None = None,
    estado: str | None = None,
    tipo: str | None = None,
    solo_abiertas: bool = False,
    cierra_en_horas: float | None = None,
    incluir_detalle: bool = False,
    analizar: int = Query(10, ge=1, le=60),
    max_paginas: int = Query(3, ge=1, le=40),
    orden: str = "fecha_publicacion",
    dir_orden: str = Query("desc", alias="dir"),
):
    """Exporta a Excel los procesos en recepción de ofertas."""
    filtrado, _, _ = await _consultar(
        search, fecha_inicio, fecha_fin, provincia, canton, estado, tipo,
        solo_abiertas, cierra_en_horas, analizar, max_paginas, orden, dir_orden,
        incluir_detalle,
    )

    if filtrado.empty:
        return {"error": "No hay procesos que coincidan con los filtros seleccionados."}

    export = ofertas.df_exportable(filtrado)
    buffer = dataframe_a_excel(export, "Ofertas", ANCHO_EXCEL)
    archivo = nombre_archivo(["ofertas", search, canton or provincia, estado])

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{archivo}.xlsx"'},
    )
