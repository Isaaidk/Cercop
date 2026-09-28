"""
Controlador: Necesidades de Contratación y Recepción de Proformas (NCO - SERCOP).

Expone la tabla solicitada:

    Tipo de Necesidad | Código Necesidad de Contratación | Fecha de Publicación |
    Provincia - Cantón | Descripción del Objeto de compra | Estado de la Necesidad |
    Fecha límite para la entrega de proformas | Entidad Contratante |
    Dirección de Entrega | Contacto

con filtros por palabra clave, provincia, cantón, estado de la necesidad,
tipo de necesidad y rango de fechas.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Query
from fastapi.responses import StreamingResponse

from Consultoria.controller.utils import dataframe_a_excel, nombre_archivo
from Consultoria.model import necesidades

router = APIRouter(prefix="/api/necesidades", tags=["Necesidades de Contratación (NCO)"])

ANCHO_EXCEL = {
    "Tipo de Necesidad": 20,
    "Código Necesidad de Contratación": 34,
    "Fecha de Publicación": 20,
    "Provincia - Cantón": 34,
    "Descripción del Objeto de compra": 60,
    "Estado de la Necesidad": 20,
    "Fecha límite para la entrega de proformas": 24,
    "Entidad Contratante": 45,
    "Dirección de Entrega": 45,
    "Contacto": 55,
    "Enlace al detalle": 45,
}


async def _consultar(
    q: str | None,
    modo: str,
    provincia: str | None,
    canton: str | None,
    estado: str | None,
    tipo: str | None,
    fecha_desde: str | None,
    fecha_hasta: str | None,
    por_vencer_horas: float | None,
    solo_vigentes: bool,
    orden: str,
    dir_orden: str,
):
    """Descarga (o reutiliza el caché) y aplica todos los filtros."""
    df = await necesidades.obtener_necesidades()
    filtrado = necesidades.aplicar_filtros(
        df,
        palabras_clave=q,
        modo=modo,
        provincia=provincia,
        canton=canton,
        estado=estado,
        tipo=tipo,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        por_vencer_horas=por_vencer_horas,
        solo_vigentes=solo_vigentes,
    )
    return necesidades.ordenar(filtrado, orden, dir_orden)


@router.get("")
async def listar_necesidades(
    q: str | None = Query(None, description="Palabras clave separadas por comas."),
    modo: str = Query("todas", pattern="^(todas|cualquiera)$", description="todas = AND, cualquiera = OR"),
    provincia: str | None = Query(None, description="Provincia exacta (ej. PICHINCHA)."),
    canton: str | None = Query(None, description="Cantón (coincidencia parcial)."),
    estado: str | None = Query(None, description="Estado de la necesidad (ej. En Curso)."),
    tipo: str | None = Query(None, description="Tipo de necesidad (ej. Ínfimas Cuantías)."),
    fecha_desde: str | None = Query(None, description="Fecha de publicación mínima (YYYY-MM-DD)."),
    fecha_hasta: str | None = Query(None, description="Fecha de publicación máxima (YYYY-MM-DD)."),
    por_vencer_horas: float | None = Query(None, ge=0, description="Días/horas para vencer la entrega de proformas."),
    solo_vigentes: bool = Query(False, description="Excluye necesidades cuyo plazo ya venció."),
    orden: str = Query("fecha_publicacion"),
    dir_orden: str = Query("desc", alias="dir", pattern="^(asc|desc)$"),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(25, ge=1, le=500),
):
    """Tabla paginada de necesidades de contratación con filtros."""
    filtrado = await _consultar(
        q, modo, provincia, canton, estado, tipo, fecha_desde, fecha_hasta,
        por_vencer_horas, solo_vigentes, orden, dir_orden,
    )
    pagina_df, total, total_paginas = necesidades.paginar(filtrado, pagina, por_pagina)
    catalogo = necesidades.construir_filtros(await necesidades.obtener_necesidades())

    return {
        "data": necesidades.a_registros(pagina_df),
        "total": total,
        "pagina": pagina,
        "por_pagina": por_pagina,
        "total_paginas": total_paginas,
        "catalogo": catalogo,
    }


@router.get("/filtros")
async def catalogo_filtros():
    """Opciones disponibles para los selectores (provincias, cantones, estados, tipos)."""
    df = await necesidades.obtener_necesidades()
    return necesidades.construir_filtros(df)


@router.get("/estadisticas")
async def estadisticas(
    q: str | None = Query(None, description="Palabras clave separadas por comas."),
    modo: str = Query("todas", pattern="^(todas|cualquiera)$"),
    provincia: str | None = None,
    canton: str | None = None,
    estado: str | None = None,
    tipo: str | None = None,
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    solo_vigentes: bool = False,
    top: int = Query(12, ge=3, le=40, description="Cantones/provincias principales."),
    dias_serie: int = Query(30, ge=7, le=180, description="Días de la serie temporal."),
):
    """Agregados para las gráficas, respetando los mismos filtros de la tabla."""
    df = await necesidades.obtener_necesidades()
    filtrado = necesidades.aplicar_filtros(
        df,
        palabras_clave=q,
        modo=modo,
        provincia=provincia,
        canton=canton,
        estado=estado,
        tipo=tipo,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        solo_vigentes=solo_vigentes,
    )
    return necesidades.construir_estadisticas(filtrado, top=top, dias_serie=dias_serie)


@router.post("/actualizar")
async def actualizar_datos():
    """Fuerza una nueva descarga del listado desde el SERCOP."""
    df = await necesidades.obtener_necesidades(forzar=True)
    return {"mensaje": "Datos actualizados", "registros": int(len(df)), **necesidades.construir_filtros(df)}


@router.get("/exportar")
async def exportar_necesidades(
    q: str | None = None,
    modo: str = "todas",
    provincia: str | None = None,
    canton: str | None = None,
    estado: str | None = None,
    tipo: str | None = None,
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    por_vencer_horas: float | None = None,
    solo_vigentes: bool = False,
    orden: str = "fecha_publicacion",
    dir_orden: str = Query("desc", alias="dir"),
):
    """Exporta a Excel el resultado con los filtros actuales."""
    filtrado = await _consultar(
        q, modo, provincia, canton, estado, tipo, fecha_desde, fecha_hasta,
        por_vencer_horas, solo_vigentes, orden, dir_orden,
    )

    if filtrado.empty:
        return {"error": "No hay necesidades que coincidan con los filtros seleccionados."}

    export = necesidades.df_exportable(filtrado)
    buffer = dataframe_a_excel(export, "Necesidades", ANCHO_EXCEL)
    archivo = nombre_archivo(["necesidades", canton or provincia, estado, q])

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{archivo}.xlsx"'},
    )
