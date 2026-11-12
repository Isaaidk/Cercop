"""Ver y rellenar un TDR. La API encola; el worker descarga.

Regla R-01: ninguna petición de un usuario abre una conexión al portal. Si el archivo ya está en
el almacén temporal y no venció, se sirve. Si no, se deja una fila `pendiente` y se responde 202.
"""

from __future__ import annotations

import contextlib
import io
import zipfile
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from contratacion.dominio.acceso import fuentes_para_vistas
from contratacion.dominio.anexos import elegir_anexos
from contratacion.dominio.documentos import parece_enlace
from contratacion.dominio.errores import SinPermiso
from contratacion.dominio.relleno import presentar_anexos, proponer
from contratacion.dominio.serializacion import cuerpo_json
from contratacion.infraestructura.adaptadores.entrada.http.dependencias import (
    ActorDep,
    ConsentimientoDep,
    CpcDep,
    PerfilDep,
    TdrDep,
    VistasDep,
)
from contratacion.infraestructura.adaptadores.entrada.http.limites import LimitePorUsuario
from contratacion.infraestructura.config.ajustes import obtener_ajustes

router = APIRouter(prefix="/v1/tdr", tags=["TDR"])


# Topes por persona (no por IP): ver `limites.py`.
_PEDIR = Depends(LimitePorUsuario("tdr.pedir", 30, 60))
_ESTADO = Depends(LimitePorUsuario("tdr.estado", 120, 60))
_ARCHIVO = Depends(LimitePorUsuario("tdr.archivo", 40, 60))
_RELLENO = Depends(LimitePorUsuario("tdr.relleno", 30, 60))


async def exigir_vista_del_proceso(registro_id: UUID, vistas: VistasDep, tdr: TdrDep) -> None:
    """Los anexos y el borrador de un proceso son datos de su fuente: hace falta su vista.

    Sin esto, a quien el superadministrador le ocultó «Ínfimas cuantías» le bastaba con conocer el
    identificador de una ínfima (un enlace compartido, el historial del navegador) para bajar sus
    TDR. Un proceso que no existe se deja pasar: cada ruta ya responde 404 por su cuenta.
    """
    fuente = await tdr.fuente_de(registro_id)
    if fuente is not None and fuente not in fuentes_para_vistas(vistas):
        raise SinPermiso(
            "Tu cuenta no tiene acceso a los procesos de esta fuente. Pide al administrador que "
            "active la vista correspondiente."
        )


_VISTA = Depends(exigir_vista_del_proceso)


def _carpeta() -> Path:
    return Path(obtener_ajustes().tdr_dir)


@router.post(
    "/{registro_id}",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Pedir el TDR",
    dependencies=[_PEDIR, _VISTA],
)
async def pedir(
    registro_id: UUID, actor: ActorDep, tdr: TdrDep, _: ConsentimientoDep
) -> JSONResponse:
    actor.exigir_permiso("tdr.ver")
    # Solo los anexos que sirven para la proforma: TDR, pliegos, especificaciones y la última acta.
    # Las actas anteriores no se piden: cada archivo de menos es una petición de menos al portal.
    documentos = elegir_anexos(await tdr.documentos_del_registro(registro_id))
    if not documentos:
        raise HTTPException(status_code=404, detail="Esta ínfima no publica documentos.")
    # Solo se pide lo que aún no está pedido: casi siempre ya existe y no se escribe nada.
    existentes = {
        str(fila["nombre"]): str(fila["estado"]) for fila in await tdr.listar(registro_id)
    }
    estados = []
    for documento in documentos:
        nombre = str(documento.get("nombre") or "tdr")
        estado_actual = existentes.get(nombre) or await tdr.pedir(registro_id, documento)
        estados.append({"nombre": documento.get("nombre"), "estado": estado_actual})
    with contextlib.suppress(Exception):
        await tdr.auditar(actor.negocio_id, actor.usuario_id, registro_id)
    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content={"documentos": estados})


@router.get(
    "/{registro_id}", summary="Estado de los TDR de una ínfima", dependencies=[_ESTADO, _VISTA]
)
async def estado(
    registro_id: UUID, actor: ActorDep, tdr: TdrDep, _: ConsentimientoDep
) -> dict[str, Any]:
    actor.exigir_permiso("tdr.ver")
    filas = await tdr.listar(registro_id)
    anexos = elegir_anexos(await tdr.documentos_del_registro(registro_id))
    if not anexos:
        return cuerpo_json({"documentos": filas, "anexos": []})
    por_nombre = {str(fila["nombre"]): fila for fila in filas}
    lista = []
    for posicion, anexo in enumerate(anexos, start=1):
        nombre = str(anexo.get("nombre") or "").strip()
        fila = por_nombre.get(nombre or "tdr") or {}
        lista.append(
            {
                "nombre": f"Documento {posicion}"
                if not nombre or parece_enlace(nombre)
                else nombre,
                "tipo": anexo["tipo"],
                "etiqueta_tipo": anexo["etiqueta_tipo"],
                "fecha": str(anexo.get("fecha") or "")[:10],
                "estado": fila.get("estado") or "sin_pedir",
                "id": fila.get("id"),
                "mime": fila.get("mime") or "",
            }
        )
    # `documentos` son las filas de la cola, solo de los anexos elegidos: las actas viejas pedidas
    # antes de esta regla no se enseñan ni se bajan.
    elegidas = [
        fila for fila in filas if str(fila["nombre"]) in {a.get("nombre") or "tdr" for a in anexos}
    ]
    return cuerpo_json({"documentos": elegidas, "anexos": lista})


@router.get(
    "/{registro_id}/archivo/{documento_id}",
    summary="Ver el archivo, si ya está",
    dependencies=[_ARCHIVO, _VISTA],
)
async def archivo(
    registro_id: UUID,
    documento_id: UUID,
    actor: ActorDep,
    tdr: TdrDep,
    _: ConsentimientoDep,
) -> FileResponse:
    actor.exigir_permiso("tdr.ver")
    fila = await tdr.uno(documento_id)
    if fila is None or fila["registro_id"] != registro_id or fila["estado"] != "listo":
        raise HTTPException(status_code=404, detail="El TDR todavía no está listo.")
    ruta = Path(str(fila["ruta"]))
    if not ruta.is_file():
        raise HTTPException(status_code=404, detail="El archivo temporal ya venció.")
    return FileResponse(
        ruta,
        media_type=fila.get("mime") or "application/octet-stream",
        filename=str(fila["nombre"]),
        content_disposition_type="inline",
    )


@router.get(
    "/{registro_id}/relleno",
    summary="Borrador de oferta, si la ínfima aplica",
    dependencies=[_RELLENO, _VISTA],
)
async def relleno(
    registro_id: UUID,
    actor: ActorDep,
    tdr: TdrDep,
    perfil: PerfilDep,
    cpc: CpcDep,
    _: ConsentimientoDep,
) -> dict[str, Any]:
    actor.exigir_permiso("tdr.rellenar")
    fila = await tdr.registro(registro_id)
    if fila is None:
        raise HTTPException(status_code=404, detail="No existe esa ínfima.")
    datos = dict(fila.get("datos") or {})
    ficha = await perfil.leer(actor.negocio_id)
    claves = await cpc.listar(negocio_id=actor.negocio_id)
    ficha["cpc"] = [clave.texto for clave in claves]
    pedidos: list[str] = []
    for documento in await tdr.listar(registro_id):
        pedidos.extend(documento.get("campos_pedido") or [])
    propuesta = proponer(
        ficha,
        provincia=str(fila.get("provincia") or datos.get("provincia") or ""),
        cpc_codigos=list(fila.get("cpc_codigos") or []),
        tipo_texto=str(datos.get("tipo_necesidad") or datos.get("tipo_proceso") or ""),
        # NCO es la fuente de ínfimas. El resto se clasifica por el texto del procedimiento.
        es_infima=str(fila.get("fuente") or "").upper() == "NCO",
        campos_pedido=pedidos,
    )
    propuesta["legible"] = presentar_anexos(propuesta.get("anexos") or {})
    return cuerpo_json(propuesta)


@router.get(
    "/{registro_id}/borrador.docx",
    summary="Descargar el borrador, sin guardarlo",
    dependencies=[_RELLENO, _VISTA],
)
async def descargar_borrador(
    registro_id: UUID,
    actor: ActorDep,
    tdr: TdrDep,
    perfil: PerfilDep,
    cpc: CpcDep,
    _: ConsentimientoDep,
) -> StreamingResponse:
    cuerpo = await relleno(registro_id, actor, tdr, perfil, cpc, _)
    if not cuerpo.get("aplica"):
        raise HTTPException(status_code=409, detail=cuerpo.get("motivos"))
    contenido = _docx(cuerpo.get("legible") or presentar_anexos(cuerpo["anexos"]))
    return StreamingResponse(
        io.BytesIO(contenido),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": "attachment; filename=borrador-oferta.docx"},
    )


def _docx(secciones: list[dict[str, Any]]) -> bytes:
    """Un DOCX mínimo, armado en memoria. No se escribe en disco."""
    lineas = ["Borrador de oferta", ""]
    for seccion in secciones:
        lineas.append(str(seccion["titulo"]).upper())
        for fila in seccion["filas"]:
            lineas.append(
                f"{fila['etiqueta']}: {fila['valor']}" if isinstance(fila, dict) else f"- {fila}"
            )
        if not seccion["filas"]:
            lineas.append("Sin datos en el perfil.")
        lineas.append("")
    parrafos = "".join(f"<w:p><w:r><w:t>{_xml(linea)}</w:t></w:r></w:p>" for linea in lineas)
    documento = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{parrafos}</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archivo:
        tipos = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>"
        )
        relaciones = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            "Type="
            '"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="word/document.xml"/>'
            "</Relationships>"
        )
        archivo.writestr("[Content_Types].xml", tipos)
        archivo.writestr("_rels/.rels", relaciones)
        archivo.writestr("word/document.xml", documento)
    return buffer.getvalue()


def _xml(texto: str) -> str:
    return texto.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
