"""Perfil de la empresa: los datos con los que después se rellena un TDR."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile, status
from pydantic import BaseModel, Field

from contratacion.aplicacion.casos_uso.gestionar_perfil import (
    TEXTO_OCR_MAXIMO,
    TEXTO_OCR_MINIMO,
    agregar_fila,
    aplicar_rup,
    consultar_historial,
    consultar_ruc,
    guardar_identidad,
    leer_rup_pdf,
    leer_rup_texto,
    quitar_fila,
    ver_perfil,
)
from contratacion.dominio.serializacion import cuerpo_json
from contratacion.infraestructura.adaptadores.entrada.http.dependencias import (
    ActorDep,
    ConsentimientoDep,
    CpcDep,
    PerfilDep,
)
from contratacion.infraestructura.adaptadores.entrada.http.limites import LimitePorUsuario
from contratacion.infraestructura.adaptadores.salida.historial import (
    HistorialOcds,
    obtener_historial,
)
from contratacion.infraestructura.adaptadores.salida.pdf import texto_de_pdf
from contratacion.infraestructura.adaptadores.salida.sri import ConsultaSri, obtener_sri

router = APIRouter(prefix="/v1/empresa/perfil", tags=["Empresa"])


class Identidad(BaseModel):
    razon_social: str | None = None
    nombre_comercial: str | None = None
    tipo_persona: str | None = None
    ruc: str | None = None
    sitio_web: str | None = None
    estado_rup: str | None = None
    fecha_inicio_actividades: str | None = None
    obligado_contabilidad: bool | None = None
    regimen_tributario: str | None = None
    email_contacto: str | None = None
    telefono: str | None = None
    direccion: str | None = None
    ciudad: str | None = None
    presupuesto_min: float | None = None
    presupuesto_max: float | None = None
    capacidad_ejecucion: str | None = None


class ConsultaRuc(BaseModel):
    ruc: str = Field(min_length=13, max_length=13, pattern=r"^\d{13}$")


class ConsultaContratos(BaseModel):
    ruc: str = Field(min_length=13, max_length=13, pattern=r"^\d{13}$")
    razon_social: str = Field(min_length=3, max_length=300)


class Fila(BaseModel):
    """Una fila de dedicación, contacto, cobertura u otro anexo.

    Los campos que no aplican a esa colección se ignoran en el caso de uso: cada colección
    valida los suyos.
    """

    tipo_contratacion: str | None = None
    tipo_procedimiento: str | None = None
    monto_min: float | None = None
    monto_max: float | None = None
    principal: bool | None = None
    tipo: str | None = None
    nombre: str | None = None
    cedula: str | None = None
    cargo: str | None = None
    email: str | None = None
    telefono: str | None = None
    ciiu: str | None = None
    descripcion: str | None = None
    provincia: str | None = None
    canton: str | None = None
    ruta_almacen: str | None = None
    sha256: str | None = None
    emitido_en: str | None = None
    vence_en: str | None = None
    entidad: str | None = None
    objeto: str | None = None
    monto: float | None = None
    anio: int | None = None
    cpc: str | None = None
    perfil: str | None = None
    titulo: str | None = None
    anios: int | None = None
    cantidad: int | None = None
    estado: str | None = None
    texto: str | None = None


class CpcDelRup(BaseModel):
    codigo: str = Field(max_length=20, pattern=r"^\d{4,12}$")
    descripcion: str = Field(default="", max_length=300)


class RepresentanteDelRup(BaseModel):
    nombre: str | None = Field(default=None, max_length=160)
    cedula: str | None = Field(default=None, max_length=20)


class ActividadDelRup(BaseModel):
    ciiu: str = Field(max_length=20)
    descripcion: str = Field(default="", max_length=400)
    principal: bool = False


class LugarDelRup(BaseModel):
    provincia: str = Field(max_length=80)
    canton: str = Field(default="", max_length=80)


class TextoRup(BaseModel):
    """El texto que el navegador sacó por OCR de un RUP escaneado o de una foto."""

    texto: str = Field(min_length=TEXTO_OCR_MINIMO, max_length=TEXTO_OCR_MAXIMO)


class AplicarRup(BaseModel):
    """Lo que la persona eligió de la lectura del RUP y del RUC."""

    identidad: dict[str, str | bool] = Field(default_factory=dict)
    representante: RepresentanteDelRup | None = None
    cpc: list[CpcDelRup] = Field(default_factory=list, max_length=150)
    actividades: list[ActividadDelRup] = Field(default_factory=list, max_length=40)
    cobertura: list[LugarDelRup] = Field(default_factory=list, max_length=24)


_TOPE_RUP = 8 * 1024 * 1024


def _presentes(modelo: BaseModel) -> dict[str, Any]:
    return {clave: valor for clave, valor in modelo.model_dump().items() if valor is not None}


@router.get("", summary="Perfil de la empresa")
async def leer(actor: ActorDep, perfil: PerfilDep, _: ConsentimientoDep) -> dict[str, Any]:
    return cuerpo_json(await ver_perfil(actor, repositorio=perfil))


@router.put("", summary="Guardar la identidad de la empresa")
async def guardar(
    cuerpo: Identidad, actor: ActorDep, perfil: PerfilDep, _: ConsentimientoDep
) -> dict[str, Any]:
    return cuerpo_json(
        await guardar_identidad(actor, repositorio=perfil, campos=_presentes(cuerpo))
    )


@router.post("/consulta-ruc", summary="Propuesta de perfil a partir del RUC, según el SRI")
async def consulta_ruc(
    cuerpo: ConsultaRuc,
    actor: ActorDep,
    _: ConsentimientoDep,
    sri: Annotated[ConsultaSri, Depends(obtener_sri)],
) -> dict[str, Any]:
    """No guarda nada: devuelve lo que se llenaría para que la persona lo revise y lo aplique."""
    return cuerpo_json(await consultar_ruc(actor, ruc=cuerpo.ruc, sri=sri))


@router.post(
    "/consulta-contratos",
    summary="CPC y experiencia que los datos abiertos atribuyen a tu RUC",
    dependencies=[Depends(LimitePorUsuario("perfil.consulta_contratos", 6, 60))],
)
async def consulta_contratos(
    cuerpo: ConsultaContratos,
    actor: ActorDep,
    _: ConsentimientoDep,
    historial: Annotated[HistorialOcds, Depends(obtener_historial)],
) -> dict[str, Any]:
    """No guarda nada. Tarda varios segundos: consulta un servicio ajeno y lo recuerda un rato."""
    return cuerpo_json(
        await consultar_historial(
            actor, ruc=cuerpo.ruc, razon_social=cuerpo.razon_social, historial=historial
        )
    )


@router.post(
    "/leer-rup",
    summary="Leer el certificado del RUP en PDF: datos y CPC con su descripción",
    dependencies=[Depends(LimitePorUsuario("perfil.leer_rup", 10, 60))],
)
async def leer_rup(
    actor: ActorDep, _: ConsentimientoDep, archivo: Annotated[UploadFile, File()]
) -> dict[str, Any]:
    """No guarda nada: devuelve la propuesta para que la persona elija qué cargar."""
    contenido = await archivo.read(_TOPE_RUP + 1)
    if len(contenido) > _TOPE_RUP:
        from contratacion.dominio.errores import DatoInvalido

        raise DatoInvalido("El archivo pasa de 8 MB.")
    return cuerpo_json(await leer_rup_pdf(actor, contenido=contenido, extraer_texto=texto_de_pdf))


@router.post(
    "/leer-rup-texto",
    summary="Leer el RUP a partir del texto sacado por OCR en el navegador",
    dependencies=[Depends(LimitePorUsuario("perfil.leer_rup_texto", 10, 60))],
)
async def leer_rup_texto_ruta(
    cuerpo: TextoRup, actor: ActorDep, _: ConsentimientoDep
) -> dict[str, Any]:
    """Devuelve lo mismo que `/leer-rup`. No guarda nada.

    Para un RUP escaneado o una foto: `pypdf` no saca texto de una imagen y el OCR es demasiado
    pesado para el servidor, así que lo hace el navegador (`frontend/src/utils/ocr.js`) y aquí
    llega solo el texto.
    """
    return cuerpo_json(await leer_rup_texto(actor, texto=cuerpo.texto))


@router.post("/aplicar-rup", summary="Cargar en el perfil lo elegido del RUP")
async def aplicar_rup_ruta(
    cuerpo: AplicarRup,
    actor: ActorDep,
    perfil: PerfilDep,
    cpc: CpcDep,
    _: ConsentimientoDep,
) -> dict[str, Any]:
    return cuerpo_json(
        await aplicar_rup(
            actor,
            repositorio=perfil,
            cpc=cpc,
            propuesta=cuerpo.model_dump(exclude_none=True),
        )
    )


def _ruta_coleccion(coleccion: str) -> None:
    async def agregar(
        cuerpo: Fila, actor: ActorDep, perfil: PerfilDep, _: ConsentimientoDep
    ) -> dict[str, Any]:
        fila = await agregar_fila(
            actor, repositorio=perfil, coleccion=coleccion, campos=_presentes(cuerpo)
        )
        return cuerpo_json(fila)

    async def quitar(
        fila_id: UUID, actor: ActorDep, perfil: PerfilDep, _: ConsentimientoDep
    ) -> None:
        await quitar_fila(actor, repositorio=perfil, coleccion=coleccion, fila_id=fila_id)

    agregar.__name__ = f"agregar_{coleccion}"
    quitar.__name__ = f"quitar_{coleccion}"
    router.add_api_route(
        f"/{coleccion}", agregar, methods=["POST"], status_code=status.HTTP_201_CREATED
    )
    router.add_api_route(f"/{coleccion}/{{fila_id}}", quitar, methods=["DELETE"], status_code=204)


for _coleccion in (
    "dedicaciones",
    "contactos",
    "actividades",
    "cobertura",
    "documentos",
    "experiencia",
    "personal",
    "equipo",
    "ofertas",
    "palabras",
):
    _ruta_coleccion(_coleccion)
