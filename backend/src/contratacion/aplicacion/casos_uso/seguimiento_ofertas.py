"""«Mis ofertas»: las proformas hechas, por etapa, y el recordatorio de cierre.

Las cifras (tasa de éxito, montos por etapa) se calculan aquí al leer y no se guardan: la base solo
lleva la etapa, el monto adjudicado y una nota corta de cada proforma.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.puertos.seguimiento import RepositorioSeguimiento
from contratacion.dominio.errores import DatoInvalido, NoEncontrado

registro = logging.getLogger(__name__)

ETAPAS = ("borrador", "enviada", "adjudicada", "perdida", "descartada")
LARGO_NOTA = 500
# Horas antes del cierre en que se avisa de un borrador sin enviar.
HORAS_RECORDATORIO = 24


def _numero(valor: Any) -> float:
    try:
        return float(valor or 0)
    except (TypeError, ValueError):
        return 0.0


def resumir(filas: list[dict[str, Any]]) -> dict[str, Any]:
    """Cuántas hay en cada etapa, cuánto suman y la tasa de éxito sobre las ya resueltas."""
    por_etapa = {etapa: {"cantidad": 0, "monto": 0.0} for etapa in ETAPAS}
    adjudicado = 0.0
    for fila in filas:
        etapa = str(fila.get("etapa") or "")
        if etapa not in por_etapa:
            etapa = "borrador"
        por_etapa[etapa]["cantidad"] += 1
        por_etapa[etapa]["monto"] += _numero(fila.get("total"))
        if etapa == "adjudicada":
            adjudicado += _numero(fila.get("monto_adjudicado") or fila.get("total"))
    ganadas = por_etapa["adjudicada"]["cantidad"]
    resueltas = ganadas + por_etapa["perdida"]["cantidad"]
    return {
        "por_etapa": por_etapa,
        "tasa_exito": round(ganadas / resueltas * 100, 1) if resueltas else None,
        "resueltas": resueltas,
        "adjudicado": round(adjudicado, 2),
        "en_juego": round(por_etapa["enviada"]["monto"] + por_etapa["borrador"]["monto"], 2),
    }


async def ver_ofertas(actor: Actor, *, repositorio: RepositorioSeguimiento) -> dict[str, Any]:
    actor.exigir_permiso("tdr.ver")
    filas = await repositorio.listar(negocio_id=actor.negocio_id)
    return {"ofertas": filas, "resumen": resumir(filas), "etapas": list(ETAPAS)}


async def mover_oferta(
    actor: Actor,
    *,
    repositorio: RepositorioSeguimiento,
    proforma_id: UUID,
    campos: dict[str, Any],
) -> None:
    actor.exigir_permiso("tdr.ver")
    limpio: dict[str, Any] = {}
    if "etapa" in campos:
        if campos["etapa"] not in ETAPAS:
            raise DatoInvalido(f"La etapa debe ser una de: {', '.join(ETAPAS)}.")
        limpio["etapa"] = campos["etapa"]
    if "monto_adjudicado" in campos:
        monto = campos["monto_adjudicado"]
        if monto is not None and (not isinstance(monto, int | float) or monto < 0):
            raise DatoInvalido("El monto adjudicado tiene que ser un número positivo.")
        limpio["monto_adjudicado"] = monto
    if "nota" in campos:
        nota = str(campos["nota"] or "").strip()
        if len(nota) > LARGO_NOTA:
            raise DatoInvalido(f"La nota no puede pasar de {LARGO_NOTA} caracteres.")
        limpio["nota"] = nota
    if not await repositorio.actualizar(
        negocio_id=actor.negocio_id, proforma_id=proforma_id, campos=limpio
    ):
        raise NoEncontrado("Esa proforma no está en tu empresa.")


async def recordar_cierres(repositorio: RepositorioSeguimiento) -> int:
    """Avisa en el panel de cada borrador cuyo proceso cierra en menos de un día. Una vez."""
    avisados = 0
    for fila in await repositorio.por_cerrar(horas=HORAS_RECORDATORIO):
        cierra = fila.get("cierra_en")
        cuando = ""
        if isinstance(cierra, datetime):
            horas = max(1, int((cierra - datetime.now(UTC)).total_seconds() // 3600))
            cuando = f"en {horas} h"
        que = str(fila.get("objeto_texto") or fila.get("titulo_texto") or "tu proforma")[:160]
        try:
            await repositorio.recordar(
                fila,
                titulo=f"Cierra {cuando or 'mañana'}: {que}"[:240],
                detalle=(
                    f"{fila.get('entidad_texto') or 'La entidad'} cierra la recepción de "
                    "proformas pronto y tu proforma sigue en borrador. Envíala o márcala "
                    "como descartada en «Mis ofertas»."
                ),
            )
            avisados += 1
        except Exception:  # noqa: BLE001 - un recordatorio no puede parar los demás
            registro.exception("No se pudo recordar la proforma %s", fila.get("id_proforma"))
    if avisados:
        registro.info("Recordatorios de cierre: %s", avisados)
    return avisados
