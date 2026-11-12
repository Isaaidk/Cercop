"""«Propuestas para ti»: todas las ínfimas abiertas que la empresa puede ofertar según su perfil.

Usa los mismos criterios que el radar (`criterios_desde_perfil`), pero con otra promesa: el radar
muestra lo más parecido entre lo reciente; esto muestra **todo** lo que la empresa puede ofertar hoy
—ínfimas vigentes con el plazo de proformas abierto—, paginado de verdad y con el motivo de cada
sugerencia.

Rendimiento: el cálculo cuesta una consulta acotada por plazo, CPC y palabras, y se guarda un par de
minutos por empresa. La clave del caché incluye una huella de los criterios, así que editar
el perfil o la lista de CPC da propuestas nuevas al momento sin borrar nada a mano.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.puertos.cache import Cache
from contratacion.aplicacion.puertos.cpc import RepositorioCpc
from contratacion.aplicacion.puertos.perfil import RepositorioPerfil
from contratacion.aplicacion.puertos.radar import InfimasAbiertas
from contratacion.dominio.acceso import Vista, fuentes_para_vistas
from contratacion.dominio.errores import DatoInvalido, SinPermiso
from contratacion.dominio.propuestas import (
    ORDENES,
    evaluar,
    ordenar,
    restringir_a_provincia,
    resumen_criterios,
    zonas_desde_perfil,
)
from contratacion.dominio.radar import criterios_desde_perfil, unir_duplicados
from contratacion.dominio.serializacion import a_json, de_json

_log = logging.getLogger(__name__)

# Red de seguridad, no un recorte de producto: hoy hay unas 2.000 ínfimas abiertas en todo el país y
# una empresa ve una fracción. Si alguna vez se llega al tope, la respuesta lo dice (`completo`).
TOPE_CONSULTA = 5000
TAMANO_MAXIMO = 50
TTL_CACHE_SEG = 120

_MENSAJE_SIN_NCO = (
    "Tu cuenta no tiene acceso a las ínfimas cuantías. Pide al administrador que active la vista "
    "de necesidades de contratación."
)
_MENSAJE_SIN_PERFIL = (
    "Aún no sabemos qué vende tu empresa. Sube tu RUP o agrega tus CPC para recibir propuestas."
)
AVISO = (
    "Son ínfimas que tu empresa puede ofertar según tu perfil. "
    "No es una probabilidad de adjudicación."
)


def _clave_cache(negocio: str, huella: dict[str, Any]) -> str:
    resumen = hashlib.sha256(
        json.dumps(huella, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()[:24]
    return f"propuestas:v1:{negocio}:{resumen}"


async def _leer_cache(cache: Cache, clave: str) -> dict[str, Any] | None:
    try:
        guardado = await cache.obtener(clave)
        if guardado:
            valor = de_json(guardado)
            if isinstance(valor, dict):
                return valor
    except Exception:  # noqa: BLE001 - el caché es una optimización: si falla, se calcula.
        _log.warning("propuestas.cache_lectura_fallida", exc_info=True)
    return None


async def _guardar_cache(cache: Cache, clave: str, valor: dict[str, Any]) -> None:
    try:
        await cache.guardar(clave, a_json(valor), TTL_CACHE_SEG)
    except Exception:  # noqa: BLE001 - mismo motivo: sin caché, la respuesta sigue siendo correcta.
        _log.warning("propuestas.cache_escritura_fallida", exc_info=True)


async def ver_propuestas(
    actor: Actor,
    *,
    vistas: frozenset[Vista],
    perfil: RepositorioPerfil,
    cpc: RepositorioCpc,
    infimas: InfimasAbiertas,
    cache: Cache,
    pagina: int = 1,
    tamano: int = 20,
    orden: str = "coincidencia",
    provincia: str | None = None,
    solo_abiertas: bool = True,
) -> dict[str, Any]:
    if orden not in ORDENES:
        raise DatoInvalido("El orden debe ser coincidencia, cierre o presupuesto.")
    if pagina < 1:
        raise DatoInvalido("La página empieza en 1.")
    if not 1 <= tamano <= TAMANO_MAXIMO:
        raise DatoInvalido(f"El tamaño de página va de 1 a {TAMANO_MAXIMO}.")
    if "NCO" not in fuentes_para_vistas(vistas):
        raise SinPermiso(_MENSAJE_SIN_NCO)

    ficha = await perfil.leer(actor.negocio_id)
    claves = await cpc.listar(negocio_id=actor.negocio_id)
    criterios = criterios_desde_perfil(ficha, [clave.texto for clave in claves])
    zonas = zonas_desde_perfil(ficha)
    if provincia and provincia.strip():
        zonas = restringir_a_provincia(zonas, provincia.strip())
    resumen = resumen_criterios(criterios, zonas)

    base: dict[str, Any] = {
        "pagina": pagina,
        "tamano": tamano,
        "orden": orden,
        "criterios": resumen,
        "aviso": AVISO,
    }
    if not criterios.tiene_interes:
        return {
            **base,
            "propuestas": [],
            "total": 0,
            "completo": True,
            "motivo": _MENSAJE_SIN_PERFIL,
        }

    huella = {
        "cpc": criterios.cpc,
        "palabras": criterios.palabras,
        "experiencias": criterios.experiencias,
        "zonas": [(zona.provincia, zona.canton) for zona in zonas],
        "min": criterios.presupuesto_min,
        "max": criterios.presupuesto_max,
        "solo_abiertas": solo_abiertas,
    }
    clave = _clave_cache(str(actor.negocio_id), huella)
    calculado = await _leer_cache(cache, clave)
    if calculado is None:
        filas = await infimas.infimas_abiertas(
            provincias=tuple(dict.fromkeys(zona.provincia for zona in zonas)),
            cpc=criterios.cpc,
            palabras=criterios.palabras,
            incluir_sin_plazo=not solo_abiertas,
            limite=TOPE_CONSULTA,
        )
        unidas, _ = unir_duplicados(filas)
        propuestas = [
            propuesta
            for propuesta in (evaluar(criterios, zonas, fila) for fila in unidas)
            if propuesta is not None
        ]
        calculado = {"propuestas": propuestas, "completo": len(filas) < TOPE_CONSULTA}
        # Se guarda ya serializado: la respuesta es la misma con o sin caché.
        calculado = de_json(a_json(calculado))
        await _guardar_cache(cache, clave, calculado)

    todas = ordenar(list(calculado["propuestas"]), orden)
    inicio = (pagina - 1) * tamano
    return {
        **base,
        "propuestas": todas[inicio : inicio + tamano],
        "total": len(todas),
        "completo": bool(calculado.get("completo", True)),
        "motivo": None if todas else "Hoy no hay ínfimas abiertas que encajen con tu perfil.",
    }
