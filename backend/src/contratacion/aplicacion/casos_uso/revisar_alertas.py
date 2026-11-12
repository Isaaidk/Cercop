"""Crea avisos cuando aparece una oportunidad que cabe en una alerta activa."""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from contratacion.aplicacion.hilos import MemoLru
from contratacion.aplicacion.puertos.radar import CandidatosRadar, RepositorioAlertas
from contratacion.dominio.radar import CriteriosComerciales, excluir, puntuar

registro = logging.getLogger(__name__)

# Candidatos que se miran por alerta y revisión. Antes eran 40: una alerta diaria ve un día entero
# de publicaciones —cientos, con el rabo de OCDS—, y los 40 más recientes dejaban fuera casi todo
# lo que coincidía. El filtro por CPC y palabras es en Python, así que el tope tiene que cubrir
# lo publicado entre dos revisiones, no lo que cabe en una pantalla.
CANDIDATOS_POR_REVISION = 2000
# La vista previa recorre lo vigente para decir «hoy coincidirían N». Se acota igual.
CANDIDATOS_VISTA_PREVIA = 2000
MUESTRAS_VISTA_PREVIA = 5
# La vista previa se pide mientras se escribe, y lee hasta 2.000 filas con su JSON. Dos minutos de
# memoria por criterio bastan: lo vigente no cambia más rápido que la vuelta corta del worker, y
# así cien personas armando la misma alerta («mantenimiento» en Pichincha) cuestan una consulta.
_TTL_VISTA_PREVIA_SEG = 120.0
_TOPE_VISTA_PREVIA = 500
# Memoria acotada (LRU): al llenarse se olvida la menos usada, no todo de golpe. Lo guardado es
# público (lo vigente del histórico) y la llave lleva las fuentes que la persona puede ver, así que
# dos personas con vistas distintas nunca comparten una vista previa.
_vistas_previas: MemoLru[str, tuple[float, dict[str, Any]]] = MemoLru(_TOPE_VISTA_PREVIA)
TODAS_LAS_FUENTES = ("NCO", "OCDS")

_ESPERA = {
    "inmediata": timedelta(minutes=2),
    "diaria": timedelta(days=1),
    "semanal": timedelta(days=7),
}


def _toca(alerta: dict[str, Any], ahora: datetime) -> bool:
    revisada = alerta.get("revisada_en")
    if revisada is None:
        return True
    if revisada.tzinfo is None:
        revisada = revisada.replace(tzinfo=UTC)
    espera = _ESPERA.get(alerta.get("frecuencia") or "diaria", _ESPERA["diaria"])
    return bool(ahora - revisada >= espera)


async def revisar_alertas(radar: RepositorioAlertas) -> int:
    """Revisa las alertas activas. Un fallo de una no impide las demás. Devuelve avisos creados."""
    ahora = datetime.now(UTC)
    creados = 0
    for alerta in await radar.listar_alertas():
        if not _toca(alerta, ahora):
            continue
        try:
            creados += await _una(radar, alerta, ahora)
        except Exception:  # noqa: BLE001 - una alerta rota no para el resto
            registro.exception("No se pudo revisar la alerta %s", alerta.get("id"))
        await radar.marcar_revisada(alerta["id"], ahora, negocio_id=alerta.get("negocio_id"))
    return creados


def criterios_de_alerta(alerta: dict[str, Any]) -> CriteriosComerciales:
    """Los criterios de una alerta, igual para la revisión del worker y para la vista previa."""
    return CriteriosComerciales(
        provincias=(alerta["provincia"],) if alerta.get("provincia") else (),
        cantones=(alerta["canton"],) if alerta.get("canton") else (),
        cpc=tuple(str(c).strip() for c in alerta.get("cpc") or [] if str(c).strip()),
        palabras=tuple(str(p).strip() for p in alerta.get("palabras") or [] if str(p).strip()),
        presupuesto_min=alerta.get("presupuesto_min"),
        presupuesto_max=alerta.get("presupuesto_max"),
    )


async def previsualizar_alerta(
    radar: CandidatosRadar,
    alerta: dict[str, Any],
    *,
    fuentes: tuple[str, ...] = TODAS_LAS_FUENTES,
) -> dict[str, Any]:
    """Cuántos procesos vigentes cumplirían hoy la alerta, y los mejores.

    Usa exactamente la misma regla que la revisión (`excluir` y `puntuar`), así que lo que se ve
    al armar la alerta es lo que después llega como aviso. No guarda nada.

    `fuentes` son las que la persona puede ver (sus vistas): la vista previa enseña muestras con
    código, objeto y entidad, así que no puede sacar procesos de una vista oculta.
    """
    criterios = criterios_de_alerta(alerta)
    fuentes = tuple(sorted(f for f in fuentes if f in TODAS_LAS_FUENTES))
    if not criterios.tiene_interes or not fuentes:
        return {"total": 0, "tope": False, "muestras": [], "por_fuente": {}}
    clave = json.dumps(
        [
            sorted(criterios.palabras),
            sorted(criterios.cpc),
            criterios.provincias,
            criterios.cantones,
            criterios.presupuesto_min,
            criterios.presupuesto_max,
            fuentes,
        ],
        default=str,
    )
    ahora = time.monotonic()
    guardada = _vistas_previas.get(clave)
    if guardada and ahora - guardada[0] < _TTL_VISTA_PREVIA_SEG:
        return guardada[1]
    resultado = await _calcular_vista_previa(radar, criterios, fuentes)
    _vistas_previas[clave] = (ahora, resultado)
    return resultado


async def _calcular_vista_previa(
    radar: CandidatosRadar, criterios: CriteriosComerciales, fuentes: tuple[str, ...]
) -> dict[str, Any]:
    filas = await radar.candidatos(
        fuentes=fuentes,
        provincias=criterios.provincias,
        desde=None,
        limite=CANDIDATOS_VISTA_PREVIA,
    )
    compatibles: list[dict[str, Any]] = []
    por_fuente: dict[str, int] = {}
    for fila in filas:
        if excluir(criterios, fila) is not None:
            continue
        nota = puntuar(criterios, fila)
        por_fuente[fila["fuente"]] = por_fuente.get(fila["fuente"], 0) + 1
        compatibles.append(
            {
                "id": fila["id"],
                "fuente": fila["fuente"],
                "codigo": fila["codigo"],
                "objeto": fila["objeto"],
                "entidad": fila["entidad"],
                "provincia": fila["provincia"],
                "canton": fila["canton"],
                "presupuesto": fila["presupuesto"],
                "plazo": fila["plazo"],
                "puntos": nota["puntos"],
            }
        )
    compatibles.sort(key=lambda fila: fila["puntos"], reverse=True)
    return {
        "total": len(compatibles),
        "tope": len(filas) >= CANDIDATOS_VISTA_PREVIA,
        "muestras": compatibles[:MUESTRAS_VISTA_PREVIA],
        "por_fuente": por_fuente,
    }


async def _una(radar: RepositorioAlertas, alerta: dict[str, Any], ahora: datetime) -> int:
    criterios = criterios_de_alerta(alerta)
    if not criterios.tiene_interes:
        return 0
    filas = await radar.candidatos(
        fuentes=("NCO", "OCDS"),
        provincias=criterios.provincias,
        desde=alerta.get("revisada_en"),
        limite=CANDIDATOS_POR_REVISION,
    )
    avisos: list[dict[str, Any]] = []
    for fila in filas:
        if excluir(criterios, fila) is not None:
            continue
        nota = puntuar(criterios, fila)
        titulo = str(fila.get("objeto") or fila.get("codigo") or "Oportunidad compatible")
        avisos.append(
            {
                "negocio_id": alerta["negocio_id"],
                "usuario_id": alerta["usuario_id"],
                "alerta_id": alerta["id"],
                "registro_id": fila["id"],
                "titulo": titulo[:240],
                "detalle": f"{nota['puntos']}/100. {nota['aviso']}",
                "puntuacion": nota["puntos"],
            }
        )
    # Todos de una vez, y sin repetir los que ya existían (ver `crear_avisos`).
    creados = await radar.crear_avisos(avisos) if avisos else 0
    if creados:
        registro.info("Alerta %s: %s avisos a las %s", alerta["id"], creados, ahora.isoformat())
    return creados
