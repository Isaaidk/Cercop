"""Radar: oportunidades compatibles con el perfil comercial de la empresa."""

from __future__ import annotations

from typing import Any

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.puertos.cpc import RepositorioCpc
from contratacion.aplicacion.puertos.perfil import RepositorioPerfil
from contratacion.aplicacion.puertos.radar import CandidatosRadar
from contratacion.dominio.acceso import Vista, fuentes_para_vistas
from contratacion.dominio.errores import SinPermiso
from contratacion.dominio.radar import criterios_desde_perfil, excluir, puntuar, unir_duplicados

_TOPE = 300
_MENSAJE_SIN_FUENTES = (
    "No hay ninguna vista concedida que dé acceso al histórico. Pide al administrador que active "
    "al menos una."
)


async def ver_radar(
    actor: Actor,
    *,
    vistas: frozenset[Vista],
    perfil: RepositorioPerfil,
    cpc: RepositorioCpc,
    radar: CandidatosRadar,
) -> dict[str, Any]:
    fuentes = fuentes_para_vistas(vistas)
    if not fuentes:
        raise SinPermiso(_MENSAJE_SIN_FUENTES)

    ficha = await perfil.leer(actor.negocio_id)
    claves = await cpc.listar(negocio_id=actor.negocio_id)
    criterios = criterios_desde_perfil(ficha, [clave.texto for clave in claves])
    if not criterios.tiene_interes:
        return {
            "oportunidades": [],
            "duplicados_unidos": 0,
            "motivo": excluir(criterios, {}),
            "aviso": (
                "La nota del radar mide parecido con el perfil. "
                "No es una probabilidad de adjudicación."
            ),
        }

    filas = await radar.candidatos(
        fuentes=fuentes,
        provincias=criterios.provincias,
        desde=None,
        limite=_TOPE,
    )
    unidas, duplicados = unir_duplicados(filas)
    oportunidades = []
    for fila in unidas:
        if excluir(criterios, fila) is not None:
            continue
        nota = puntuar(criterios, fila)
        oportunidades.append(
            {
                "id": fila["id"],
                "codigo": fila["codigo"],
                "objeto": fila["objeto"],
                "entidad": fila["entidad"],
                "provincia": fila["provincia"],
                "canton": fila["canton"],
                "presupuesto": fila["presupuesto"],
                "fuente": fila["fuente"],
                "fecha_publicacion": fila["fecha_publicacion"],
                "compatibilidad": nota,
            }
        )
    oportunidades.sort(key=lambda fila: fila["compatibilidad"]["puntos"], reverse=True)
    return {
        "oportunidades": oportunidades[:50],
        "duplicados_unidos": duplicados,
        "motivo": None,
        "aviso": (
            "Cada nota explica el parecido con el perfil comercial. "
            "No es una probabilidad de ganar el proceso. "
            "Si el mismo código llega otra vez, se actualiza el registro que ya existía "
            "en lugar de mostrarlo como oportunidad nueva."
        ),
    }
