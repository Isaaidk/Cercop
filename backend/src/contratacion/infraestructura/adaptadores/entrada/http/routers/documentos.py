"""TDR, checklist, proforma y preguntas. El archivo subido no se guarda."""

from __future__ import annotations

import io
import json
from typing import Annotated, Any
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from contratacion.aplicacion.casos_uso.generar_oferta import generar_oferta
from contratacion.aplicacion.casos_uso.preparar_documentos import (
    comparar_con_tdr,
    crear_ficha,
    crear_proforma,
    estado_desde_codigo,
    leer_documento,
    marcar_requisito,
    preguntar,
    preparar_desde_codigo,
    proforma_guardada,
    resumir_proceso,
    titulos_usados,
)
from contratacion.aplicacion.hilos import en_hilo
from contratacion.dominio.errores import DatoInvalido, NoEncontrado
from contratacion.dominio.serializacion import cuerpo_json
from contratacion.dominio.verificacion import verificar_proforma
from contratacion.infraestructura.adaptadores.entrada.http.dependencias import (
    ActorDep,
    AuditoriaDep,
    ConsentimientoDep,
    CpcDep,
    CreditosDep,
    DocumentosDep,
    IaDep,
    MercadoDep,
    PerfilDep,
    RadarDep,
    TdrDep,
    VistasDep,
)
from contratacion.infraestructura.adaptadores.entrada.http.limites import LimitePorUsuario
from contratacion.infraestructura.adaptadores.salida.firma import TOPE_CERTIFICADO, firmar_pdf
from contratacion.infraestructura.adaptadores.salida.oficina import docx, parrafos_de
from contratacion.infraestructura.adaptadores.salida.proforma_pdf import (
    armar_ficha,
    armar_proforma,
)

router = APIRouter(prefix="/v1/documentos", tags=["Documentos"])

_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

# Topes **por persona**, no por IP: una oficina o un operador móvil comparten IP. Están pensados
# para el uso real —el sondeo del TDR pregunta cada pocos segundos— y no para frenar a quien lo usa.
_LEER = Depends(LimitePorUsuario("documentos.leer", 20, 60))
_BAJAR_TDR = Depends(LimitePorUsuario("documentos.desde_codigo", 30, 60))
_ESTADO_TDR = Depends(LimitePorUsuario("documentos.estado_tdr", 120, 60))
_PREGUNTAR = Depends(LimitePorUsuario("documentos.preguntar", 60, 60))
_GENERAR = Depends(LimitePorUsuario("documentos.generar", 20, 60))
_ARCHIVO = Depends(LimitePorUsuario("documentos.archivo", 40, 60))


class ResumenPedido(BaseModel):
    codigo: str = ""
    lectura_id: UUID | None = None


class DesdeCodigo(BaseModel):
    codigo: str = Field(min_length=3, max_length=80)
    reintentar: bool = False


class EstadoRequisito(BaseModel):
    estado: str


class LineaPrecio(BaseModel):
    descripcion: str = Field(min_length=2, max_length=1000)
    cantidad: float
    precio_unitario: float
    unidad: str = Field(default="", max_length=30)
    cpc: str = Field(default="", max_length=20)
    cpc_nombre: str = Field(default="", max_length=200)


class ProformaNueva(BaseModel):
    titulo: str = Field(default="", max_length=300)
    entidad: str = Field(default="", max_length=500)
    objeto: str = Field(default="", max_length=3000)
    contacto: str = Field(default="", max_length=500)
    impuesto_porcentaje: float
    lineas: list[LineaPrecio] = Field(min_length=1, max_length=200)
    registro_id: UUID | None = None
    extras: dict[str, Any] = Field(default_factory=dict)


class GenerarPedido(BaseModel):
    lectura_id: UUID | None = None
    entidad: str = Field(default="", max_length=500)
    objeto: str = Field(default="", max_length=3000)
    con_ia: bool = False


class Especificacion(BaseModel):
    requerido: str = Field(default="", max_length=2000)
    ofertado: str = Field(default="", max_length=2000)


class FichaNueva(BaseModel):
    nombre: str = Field(min_length=2, max_length=300)
    marca: str = Field(default="", max_length=200)
    modelo: str = Field(default="", max_length=200)
    pais_origen: str = Field(default="", max_length=100)
    anio_fabricacion: str = Field(default="", max_length=20)
    garantia: str = Field(default="", max_length=500)
    cpc: str = Field(default="", max_length=40)
    caracteristicas: str = Field(default="", max_length=10000)
    especificaciones: list[Especificacion] = Field(default_factory=list, max_length=80)
    entidad: str = Field(default="", max_length=500)
    objeto: str = Field(default="", max_length=3000)
    contacto: str = Field(default="", max_length=500)
    registro_id: UUID | None = None
    extras: dict[str, Any] = Field(default_factory=dict)


class Contraste(BaseModel):
    lectura_id: UUID
    proforma_id: UUID


class Pregunta(BaseModel):
    pregunta: str = Field(min_length=2, max_length=500)
    lectura_id: UUID | None = None


@router.post(
    "/leer",
    summary="Leer un PDF o un texto y extraer los apartados titulados",
    dependencies=[_LEER],
)
async def leer(
    actor: ActorDep,
    documentos: DocumentosDep,
    _: ConsentimientoDep,
    archivo: Annotated[UploadFile, File()],
) -> dict[str, Any]:
    contenido = await _leer_archivo(archivo)
    return cuerpo_json(
        await leer_documento(
            actor,
            documentos=documentos,
            nombre=archivo.filename or "documento",
            contenido=contenido,
        )
    )


@router.get("/lecturas", summary="Lecturas recientes de la empresa")
async def lecturas(
    actor: ActorDep, documentos: DocumentosDep, _: ConsentimientoDep
) -> dict[str, Any]:
    filas = await documentos.listar_lecturas(negocio_id=actor.negocio_id)
    return cuerpo_json({"lecturas": filas})


@router.post(
    "/desde-codigo", summary="Bajar el TDR de un código y leerlo", dependencies=[_BAJAR_TDR]
)
async def desde_codigo(
    cuerpo: DesdeCodigo,
    actor: ActorDep,
    vistas: VistasDep,
    documentos: DocumentosDep,
    tdr: TdrDep,
    _: ConsentimientoDep,
) -> dict[str, Any]:
    return cuerpo_json(
        await preparar_desde_codigo(
            actor,
            vistas,
            documentos=documentos,
            tdr=tdr,
            codigo=cuerpo.codigo,
            reintentar=cuerpo.reintentar,
        )
    )


@router.get(
    "/desde-codigo/estado",
    summary="Cómo va la bajada del TDR (no lee ningún archivo)",
    dependencies=[_ESTADO_TDR],
)
async def estado_tdr(
    codigo: Annotated[str, Query(min_length=3, max_length=120)],
    actor: ActorDep,
    vistas: VistasDep,
    documentos: DocumentosDep,
    tdr: TdrDep,
    _: ConsentimientoDep,
) -> dict[str, Any]:
    return cuerpo_json(
        await estado_desde_codigo(
            actor, vistas, documentos=documentos, tdr=tdr, codigo=codigo.strip()
        )
    )


@router.post("/resumen", summary="Resumen de un TDR leído o de un proceso publicado")
async def resumen(
    cuerpo: ResumenPedido,
    actor: ActorDep,
    vistas: VistasDep,
    documentos: DocumentosDep,
    _: ConsentimientoDep,
) -> dict[str, Any]:
    return cuerpo_json(
        await resumir_proceso(
            actor,
            vistas,
            documentos=documentos,
            codigo=cuerpo.codigo,
            lectura_id=cuerpo.lectura_id,
        )
    )


@router.get("/requisitos", summary="Checklist de la empresa")
async def requisitos(
    actor: ActorDep,
    documentos: DocumentosDep,
    _: ConsentimientoDep,
    lectura_id: UUID | None = None,
) -> dict[str, Any]:
    filas = await documentos.requisitos(negocio_id=actor.negocio_id, lectura_id=lectura_id)
    return cuerpo_json({"requisitos": filas})


@router.post("/requisitos/{requisito_id}", summary="Marcar un requisito")
async def marcar(
    requisito_id: UUID,
    cuerpo: EstadoRequisito,
    actor: ActorDep,
    documentos: DocumentosDep,
    _: ConsentimientoDep,
) -> dict[str, Any]:
    return cuerpo_json(
        await marcar_requisito(
            actor, documentos=documentos, requisito_id=requisito_id, estado=cuerpo.estado
        )
    )


@router.post("/proformas", status_code=201, summary="Proforma con precios escritos por el usuario")
async def proforma(
    cuerpo: ProformaNueva,
    actor: ActorDep,
    documentos: DocumentosDep,
    perfil: PerfilDep,
    _: ConsentimientoDep,
) -> dict[str, Any]:
    return cuerpo_json(
        await crear_proforma(
            actor,
            documentos=documentos,
            campos=cuerpo.model_dump(),
            tipo="proforma",
            perfil=perfil,
        )
    )


@router.post("/cotizaciones", status_code=201, summary="Cotización con precios confirmados")
async def cotizacion(
    cuerpo: ProformaNueva,
    actor: ActorDep,
    documentos: DocumentosDep,
    perfil: PerfilDep,
    _: ConsentimientoDep,
) -> dict[str, Any]:
    campos = cuerpo.model_dump()
    campos["titulo"] = campos["titulo"] or "Cotización"
    return cuerpo_json(
        await crear_proforma(
            actor, documentos=documentos, campos=campos, tipo="cotizacion", perfil=perfil
        )
    )


@router.post("/fichas", status_code=201, summary="Ficha con los datos que indica el usuario")
async def ficha(
    cuerpo: FichaNueva,
    actor: ActorDep,
    documentos: DocumentosDep,
    perfil: PerfilDep,
    _: ConsentimientoDep,
) -> dict[str, Any]:
    return cuerpo_json(
        await crear_ficha(actor, documentos=documentos, campos=cuerpo.model_dump(), perfil=perfil)
    )


@router.post("/contrastar", summary="Qué requisito del TDR aparece en la proforma")
async def contrastar(
    cuerpo: Contraste,
    actor: ActorDep,
    documentos: DocumentosDep,
    _: ConsentimientoDep,
) -> dict[str, Any]:
    return cuerpo_json(
        await comparar_con_tdr(
            actor,
            documentos=documentos,
            lectura_id=cuerpo.lectura_id,
            proforma_id=cuerpo.proforma_id,
        )
    )


@router.post(
    "/preguntar", summary="Pregunta contestada con datos guardados", dependencies=[_PREGUNTAR]
)
async def pregunta(
    cuerpo: Pregunta,
    actor: ActorDep,
    vistas: VistasDep,
    documentos: DocumentosDep,
    mercado: MercadoDep,
    perfil: PerfilDep,
    cpc: CpcDep,
    radar: RadarDep,
    creditos: CreditosDep,
    modelo: IaDep,
    _: ConsentimientoDep,
) -> dict[str, Any]:
    return cuerpo_json(
        await preguntar(
            actor,
            vistas,
            pregunta=cuerpo.pregunta,
            documentos=documentos,
            mercado=mercado,
            perfil=perfil,
            cpc=cpc,
            radar=radar,
            modelo=modelo,
            creditos=creditos,
            lectura_id=cuerpo.lectura_id,
        )
    )


@router.post(
    "/generar",
    summary="Borrador de oferta: plantilla o IA con los datos de la empresa",
    dependencies=[_GENERAR],
)
async def generar(
    cuerpo: GenerarPedido,
    actor: ActorDep,
    documentos: DocumentosDep,
    perfil: PerfilDep,
    creditos: CreditosDep,
    modelo: IaDep,
    _: ConsentimientoDep,
) -> dict[str, Any]:
    return cuerpo_json(
        await generar_oferta(
            actor,
            documentos=documentos,
            perfil=perfil,
            creditos=creditos,
            modelo=modelo,
            lectura_id=cuerpo.lectura_id,
            entidad=cuerpo.entidad,
            objeto=cuerpo.objeto,
            con_ia=cuerpo.con_ia,
        )
    )


@router.get("/proformas/titulos", summary="Títulos de proforma ya usados por la empresa")
async def titulos(actor: ActorDep, documentos: DocumentosDep) -> dict[str, Any]:
    return cuerpo_json(await titulos_usados(actor, documentos=documentos))


@router.get("/proformas/{proforma_id}", summary="El documento guardado, para el navegador")
async def ver_proforma(
    proforma_id: UUID,
    actor: ActorDep,
    documentos: DocumentosDep,
    _: ConsentimientoDep,
) -> dict[str, Any]:
    """El PDF lo arma el navegador de quien lo pide: el servidor solo entrega los datos."""
    documento = await proforma_guardada(actor, documentos=documentos, proforma_id=proforma_id)
    if documento is None:
        raise NoEncontrado("Esa proforma no está en la empresa.")
    return cuerpo_json(documento)


@router.get("/proformas/{proforma_id}/verificacion", summary="Qué le falta a la proforma")
async def verificacion(
    proforma_id: UUID,
    actor: ActorDep,
    documentos: DocumentosDep,
    _: ConsentimientoDep,
) -> dict[str, Any]:
    documento = await proforma_guardada(actor, documentos=documentos, proforma_id=proforma_id)
    if documento is None:
        raise NoEncontrado("Esa proforma no está en la empresa.")
    return cuerpo_json(verificar_proforma(documento))


@router.post(
    "/proformas/{proforma_id}/firmar",
    summary="PDF firmado con tu .p12 o .pfx",
    dependencies=[_ARCHIVO],
)
async def firmar(
    proforma_id: UUID,
    actor: ActorDep,
    documentos: DocumentosDep,
    auditoria: AuditoriaDep,
    _: ConsentimientoDep,
    certificado: Annotated[UploadFile, File()],
    clave: Annotated[str, Form(min_length=1, max_length=200)],
    lugar: Annotated[str, Form(max_length=80)] = "",
) -> StreamingResponse:
    """El certificado y la clave no se guardan: se usan en memoria y se descartan."""
    documento = await proforma_guardada(actor, documentos=documentos, proforma_id=proforma_id)
    if documento is None:
        raise NoEncontrado("Esa proforma no está en la empresa.")
    revision = verificar_proforma(documento)
    if documento.get("tipo") != "ficha" and revision["errores"]:
        pendientes = " ".join(fila["texto"] for fila in revision["errores"][:4])
        raise DatoInvalido(f"Antes de firmar, completa la proforma. {pendientes}")
    contenido = await certificado.read(TOPE_CERTIFICADO + 1)
    pdf, cajas = await en_hilo(_armar, documento)
    firmado, datos = await firmar_pdf(
        pdf,
        contenido,
        clave,
        motivo=f"Oferta: {documento.get('titulo') or 'Documento'}",
        lugar=lugar,
        cajas=cajas,
    )
    del contenido, clave
    await auditoria.auditar(
        accion="documento.firmar",
        negocio_id=actor.negocio_id,
        usuario_id=actor.usuario_id,
        entidad="proforma",
        resultado="ok",
        detalle={
            "proforma_id": str(proforma_id),
            "titular": datos["titular"],
            "emisor": datos["emisor"],
            "vence": datos["vence"],
            "firmas": datos["firmas"],
        },
    )
    return StreamingResponse(
        io.BytesIO(firmado),
        media_type="application/pdf",
        headers={
            "Content-Disposition": "attachment; filename=documento-firmado.pdf",
            "X-Firmante": quote(datos["titular"]),
            "X-Firmas": str(datos["firmas"]),
        },
    )


def _cajas_del_cliente(texto: str) -> list[tuple[int, tuple[float, float, float, float]]]:
    """Los recuadros de firma que dejó el navegador: `[{pagina, caja: [x1, y1, x2, y2]}]`."""
    try:
        crudas = json.loads(texto)
    except ValueError as error:
        raise DatoInvalido("Los recuadros de firma no tienen un formato válido.") from error
    if not isinstance(crudas, list) or not crudas:
        raise DatoInvalido("El PDF no trae recuadros de firma.")
    cajas: list[tuple[int, tuple[float, float, float, float]]] = []
    for fila in crudas:
        try:
            pagina = int(fila["pagina"])
            x1, y1, x2, y2 = (float(valor) for valor in fila["caja"])
        except (KeyError, TypeError, ValueError) as error:
            raise DatoInvalido("Un recuadro de firma no es válido.") from error
        if pagina < 0 or not (0 <= x1 < x2 <= 600 and 0 <= y1 < y2 <= 850):
            raise DatoInvalido("Un recuadro de firma queda fuera de la página.")
        cajas.append((pagina, (x1, y1, x2, y2)))
    return cajas


@router.post(
    "/proformas/{proforma_id}/firmar-pdf",
    summary="Firma el PDF que armó el navegador, en cada recuadro",
    dependencies=[_ARCHIVO],
)
async def firmar_pdf_del_navegador(
    proforma_id: UUID,
    actor: ActorDep,
    documentos: DocumentosDep,
    auditoria: AuditoriaDep,
    _: ConsentimientoDep,
    pdf: Annotated[UploadFile, File()],
    certificado: Annotated[UploadFile, File()],
    clave: Annotated[str, Form(min_length=1, max_length=200)],
    cajas: Annotated[str, Form(max_length=20000)],
    lugar: Annotated[str, Form(max_length=80)] = "",
) -> StreamingResponse:
    """El servidor ya no maqueta el PDF: solo lo firma. El certificado no se guarda."""
    documento = await proforma_guardada(actor, documentos=documentos, proforma_id=proforma_id)
    if documento is None:
        raise NoEncontrado("Esa proforma no está en la empresa.")
    revision = verificar_proforma(documento)
    if documento.get("tipo") != "ficha" and revision["errores"]:
        pendientes = " ".join(fila["texto"] for fila in revision["errores"][:4])
        raise DatoInvalido(f"Antes de firmar, completa la proforma. {pendientes}")
    contenido_pdf = await _leer_archivo(pdf)
    if not contenido_pdf.startswith(b"%PDF"):
        raise DatoInvalido("El archivo no es un PDF.")
    contenido = await certificado.read(TOPE_CERTIFICADO + 1)
    firmado, datos = await firmar_pdf(
        contenido_pdf,
        contenido,
        clave,
        motivo=f"Oferta: {documento.get('titulo') or 'Documento'}",
        lugar=lugar,
        cajas=_cajas_del_cliente(cajas),
    )
    del contenido, clave
    await auditoria.auditar(
        accion="documento.firmar",
        negocio_id=actor.negocio_id,
        usuario_id=actor.usuario_id,
        entidad="proforma",
        resultado="ok",
        detalle={
            "proforma_id": str(proforma_id),
            "titular": datos["titular"],
            "emisor": datos["emisor"],
            "vence": datos["vence"],
            "firmas": datos["firmas"],
        },
    )
    return StreamingResponse(
        io.BytesIO(firmado),
        media_type="application/pdf",
        headers={
            "Content-Disposition": "attachment; filename=documento-firmado.pdf",
            "X-Firmante": quote(datos["titular"]),
            "X-Firmas": str(datos["firmas"]),
        },
    )


@router.get("/proformas/{proforma_id}/docx", summary="Descargar Word", dependencies=[_ARCHIVO])
async def bajar_docx(
    proforma_id: UUID,
    actor: ActorDep,
    documentos: DocumentosDep,
    _: ConsentimientoDep,
) -> StreamingResponse:
    return await _bajar(actor, documentos, proforma_id, "docx")


@router.get("/proformas/{proforma_id}/pdf", summary="Descargar PDF", dependencies=[_ARCHIVO])
async def bajar_pdf(
    proforma_id: UUID,
    actor: ActorDep,
    documentos: DocumentosDep,
    _: ConsentimientoDep,
) -> StreamingResponse:
    return await _bajar(actor, documentos, proforma_id, "pdf")


async def _leer_archivo(archivo: UploadFile) -> bytes:
    """Corta a los 8 MB sin esperar a tener el archivo entero en memoria."""
    tope = 8 * 1024 * 1024
    partes: list[bytes] = []
    total = 0
    while True:
        bloque = await archivo.read(65536)
        if not bloque:
            break
        total += len(bloque)
        if total > tope:
            from contratacion.dominio.errores import DatoInvalido

            raise DatoInvalido("El archivo pasa de 8 MB.")
        partes.append(bloque)
    return b"".join(partes)


async def _bajar(
    actor: ActorDep,
    documentos: DocumentosDep,
    proforma_id: UUID,
    formato: str,
) -> StreamingResponse:
    documento = await proforma_guardada(actor, documentos=documentos, proforma_id=proforma_id)
    if documento is None:
        raise NoEncontrado("Esa proforma no está en la empresa.")
    # Maquetar el PDF o armar el Word es CPU: va en un hilo para no congelar a los demás.
    if formato == "pdf":
        pdf, _ = await en_hilo(_armar, documento)
        contenido, tipo, nombre = pdf, "application/pdf", "documento.pdf"
    else:
        contenido, tipo, nombre = await en_hilo(_word, documento), _DOCX, "documento.docx"
    return StreamingResponse(
        io.BytesIO(contenido),
        media_type=tipo,
        headers={"Content-Disposition": f"attachment; filename={nombre}"},
    )


def _word(documento: dict[str, Any]) -> bytes:
    return docx(parrafos_de(documento))


def _armar(documento: dict[str, Any]) -> tuple[bytes, list[Any]]:
    if documento.get("tipo") == "ficha":
        return armar_ficha(documento)
    return armar_proforma(documento)
