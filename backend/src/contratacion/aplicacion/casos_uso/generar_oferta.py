"""Armar la oferta desde el TDR y el perfil: con plantilla (gratis) o con IA (consume créditos)."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.creditos_actor import creditos_de
from contratacion.dominio.creditos import COSTO_GENERAR_OFERTA, PAQUETES, paquete
from contratacion.dominio.errores import DatoInvalido, EstadoInvalido, NoEncontrado, SinPermiso
from contratacion.dominio.oferta import (
    SISTEMA,
    borrador_plantilla,
    limpiar_respuesta,
    mensaje_para_modelo,
)
from contratacion.dominio.roles import es_de_plataforma
from contratacion.infraestructura.adaptadores.salida.bd.creditos import RepositorioCreditos
from contratacion.infraestructura.adaptadores.salida.bd.documentos import RepositorioDocumentos
from contratacion.infraestructura.adaptadores.salida.bd.perfil import RepositorioPerfil
from contratacion.infraestructura.adaptadores.salida.ia import ModeloIa

registro = logging.getLogger(__name__)


async def generar_oferta(
    actor: Actor,
    *,
    documentos: RepositorioDocumentos,
    perfil: RepositorioPerfil,
    creditos: RepositorioCreditos,
    modelo: ModeloIa,
    lectura_id: UUID | None,
    entidad: str,
    objeto: str,
    con_ia: bool,
) -> dict[str, Any]:
    secciones: dict[str, str] = {}
    if lectura_id is not None:
        lectura = await documentos.lectura(negocio_id=actor.negocio_id, lectura_id=lectura_id)
        if lectura is None:
            raise NoEncontrado("Ese TDR no está en la empresa.")
        secciones = dict(lectura["secciones"] or {})
    if not secciones and not objeto.strip():
        raise DatoInvalido("Trae el TDR o escribe el objeto para armar la oferta.")

    datos = await perfil.leer(actor.negocio_id)
    base = borrador_plantilla(secciones=secciones, perfil=datos, entidad=entidad, objeto=objeto)
    if not con_ia:
        return {**base, "saldo": None}
    if not modelo.disponible:
        return {
            **base,
            "saldo": None,
            "aviso": "La IA no está configurada en el servidor. La oferta se armó con la "
            "plantilla y los datos de tu empresa, sin gastar créditos.",
        }

    creditos = creditos_de(actor, creditos)
    queda = await creditos.consumir(
        actor.negocio_id, actor.usuario_id, COSTO_GENERAR_OFERTA, "Generar oferta con IA"
    )
    try:
        respuesta = await modelo.completar_json(
            SISTEMA,
            mensaje_para_modelo(secciones=secciones, perfil=datos, entidad=entidad, objeto=objeto),
            max_tokens=8000,
        )
    except EstadoInvalido:
        await creditos.devolver(
            actor.negocio_id, COSTO_GENERAR_OFERTA, "Devolución: la IA no respondió"
        )
        raise
    return {**limpiar_respuesta(respuesta, base, modelo=modelo.modelo), "saldo": queda}


async def ver_creditos(
    actor: Actor, *, creditos: RepositorioCreditos, modelo: ModeloIa
) -> dict[str, Any]:
    saldo = await creditos_de(actor, creditos).saldo(actor.negocio_id)
    return {
        **saldo,
        "ia_activa": modelo.disponible,
        "costos": {"generar_oferta": COSTO_GENERAR_OFERTA, "pregunta": 1},
        "paquetes": [
            {
                "codigo": p.codigo,
                "nombre": p.nombre,
                "creditos": p.creditos,
                "precio_usd": p.precio_usd,
            }
            for p in PAQUETES
        ],
    }


def _exigir_plataforma(actor: Actor) -> None:
    if not es_de_plataforma(actor.rol):
        raise SinPermiso("Solo la plataforma confirma pagos de créditos.")


async def compras_pendientes(
    actor: Actor, *, creditos: RepositorioCreditos
) -> list[dict[str, Any]]:
    _exigir_plataforma(actor)
    return await creditos.compras_pendientes()


async def resolver_compra(
    actor: Actor,
    *,
    creditos: RepositorioCreditos,
    negocio_id: UUID,
    compra_id: UUID,
    pagada: bool,
) -> dict[str, Any]:
    _exigir_plataforma(actor)
    return await creditos.resolver_compra(
        negocio_id, compra_id, pagada=pagada, por=actor.usuario_id
    )


async def otorgar_creditos(
    actor: Actor,
    *,
    creditos: RepositorioCreditos,
    negocio_id: UUID,
    cantidad: int,
    motivo: str,
) -> dict[str, Any]:
    """La plataforma regala o repone créditos a una empresa. Queda en sus movimientos."""
    _exigir_plataforma(actor)
    if not 1 <= cantidad <= 100_000:
        raise EstadoInvalido("La cantidad debe estar entre 1 y 100 000 créditos.")
    texto = " ".join(motivo.split())[:120] or "Créditos entregados por la plataforma"
    return await creditos.otorgar(negocio_id, cantidad, texto, por=actor.usuario_id)


async def pedir_compra(
    actor: Actor, *, creditos: RepositorioCreditos, codigo: str
) -> dict[str, Any]:
    actor.exigir_permiso("empresa.editar_perfil")
    compra = await creditos.solicitar_compra(actor.negocio_id, actor.usuario_id, paquete(codigo))
    return {
        **compra,
        "mensaje": "Solicitud registrada. Los créditos se suman cuando se confirme el pago.",
    }
