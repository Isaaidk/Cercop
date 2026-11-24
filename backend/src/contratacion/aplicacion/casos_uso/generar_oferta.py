"""Armar la oferta desde el TDR y el perfil: con plantilla (gratis) o con IA (consume créditos)."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.creditos_actor import creditos_de
from contratacion.dominio.creditos import (
    COSTO_GENERAR_OFERTA,
    COSTO_GENERAR_OFERTA_AVANZADO,
    PAQUETES,
    costo_generar_oferta,
    paquete,
)
from contratacion.dominio.documentos import items_pedidos
from contratacion.dominio.errores import DatoInvalido, EstadoInvalido, NoEncontrado, SinPermiso
from contratacion.dominio.oferta import (
    SISTEMA,
    borrador_plantilla,
    limpiar_respuesta,
    mensaje_para_modelo,
    texto_de_lineas,
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
    registro_id: UUID | None = None,
    avanzado: bool = False,
) -> dict[str, Any]:
    secciones: dict[str, str] = {}
    if lectura_id is not None:
        lectura = await documentos.lectura(negocio_id=actor.negocio_id, lectura_id=lectura_id)
        if lectura is None:
            raise NoEncontrado("Ese TDR no está en la empresa.")
        secciones = dict(lectura["secciones"] or {})
        registro_id = registro_id or lectura.get("registro_id")
    if not secciones and not objeto.strip():
        raise DatoInvalido("Trae el TDR o escribe el objeto para armar la oferta.")

    # Los ítems que la entidad publicó en la ficha mandan sobre todo lo demás: son las líneas.
    items = items_pedidos(await documentos.items_de_registro(registro_id)) if registro_id else []
    datos = await perfil.leer(actor.negocio_id)
    base = borrador_plantilla(
        secciones=secciones, perfil=datos, entidad=entidad, objeto=objeto, items=items
    )
    if not con_ia:
        return {**base, "saldo": None}
    if not modelo.disponible:
        return {
            **base,
            "saldo": None,
            "aviso": "La IA no está configurada en el servidor. La oferta se armó con la "
            "plantilla y los datos de tu empresa, sin gastar créditos.",
        }

    if avanzado and not modelo.avanzado_disponible:
        raise DatoInvalido("El modelo avanzado no está disponible ahora. Usa el estándar.")
    costo = costo_generar_oferta(avanzado)
    uso = "avanzado" if avanzado else "documentos"
    creditos = creditos_de(actor, creditos)
    queda = await creditos.consumir(
        actor.negocio_id,
        actor.usuario_id,
        costo,
        "Generar oferta con IA (modelo avanzado)" if avanzado else "Generar oferta con IA",
    )
    try:
        respuesta = await modelo.completar_json(
            SISTEMA,
            mensaje_para_modelo(
                secciones=secciones,
                perfil=datos,
                entidad=entidad,
                objeto=objeto,
                lineas_publicadas=base["lineas"] if base["fuente_lineas"] else [],
            ),
            max_tokens=8000,
            uso=uso,
        )
    except EstadoInvalido:
        await creditos.devolver(
            actor.negocio_id, costo, "Devolución: la IA no respondió"
        )
        raise
    limpio = limpiar_respuesta(
        respuesta, base, modelo=modelo.modelo_de(uso), texto_tdr=texto_de_lineas(secciones)
    )
    return {**limpio, "saldo": queda}


async def ver_creditos(
    actor: Actor, *, creditos: RepositorioCreditos, modelo: ModeloIa
) -> dict[str, Any]:
    saldo = await creditos_de(actor, creditos).saldo(actor.negocio_id)
    return {
        **saldo,
        "ia_activa": modelo.disponible,
        "costos": {
            "generar_oferta": COSTO_GENERAR_OFERTA,
            "generar_oferta_avanzado": COSTO_GENERAR_OFERTA_AVANZADO,
            "pregunta": 1,
        },
        # Los modelos que el usuario puede elegir para armar la proforma.
        "modelos": [
            {
                "codigo": "estandar",
                "nombre": "Estándar",
                "detalle": "Rápido y económico. Sirve para la mayoría de ínfimas.",
                "costo": COSTO_GENERAR_OFERTA,
            },
            *(
                [
                    {
                        "codigo": "avanzado",
                        "nombre": "Avanzado",
                        "detalle": "Razona más el TDR: mejor en procesos largos o técnicos. "
                        "Tarda más.",
                        "costo": COSTO_GENERAR_OFERTA_AVANZADO,
                    }
                ]
                if modelo.avanzado_disponible
                else []
            ),
        ],
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
