"""Pruebas del cálculo de políticas pendientes.

Defienden el bucle que sufrió el superadministrador al publicarse la versión 2 de los términos:
quien ya había aceptado la 1 aceptaba la 2 y la pantalla de aceptación volvía a aparecer, porque el
cálculo se quedaba con la aceptación más antigua del historial.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from contratacion.dominio.politicas import (
    Consentimiento,
    Politica,
    TipoPolitica,
    huella_texto,
    pendientes,
)

TIPO = TipoPolitica("terminos_uso")
AHORA = datetime(2026, 10, 14, 12, tzinfo=UTC)


def _politica(version: int, texto: str) -> Politica:
    return Politica(
        tipo=TIPO, version=version, texto=texto, hash=huella_texto(texto), vigente_desde=AHORA
    )


def _aceptacion(politica: Politica, cuando: datetime) -> Consentimiento:
    return Consentimiento(
        tipo=TIPO, version=politica.version, hash_texto=politica.hash, aceptado_en=cuando
    )


V1 = _politica(1, "texto uno")
V2 = _politica(2, "texto dos")


def test_aceptar_la_version_nueva_sobre_una_anterior_no_deja_nada_pendiente() -> None:
    # El repositorio entrega el historial del más reciente al más antiguo.
    historial = (_aceptacion(V2, AHORA), _aceptacion(V1, AHORA - timedelta(days=30)))

    resultado = pendientes(publicadas=(V2,), aceptadas=historial)

    assert not resultado.hay_pendientes


def test_el_orden_del_historial_no_cambia_el_resultado() -> None:
    historial = (_aceptacion(V1, AHORA - timedelta(days=30)), _aceptacion(V2, AHORA))

    assert not pendientes(publicadas=(V2,), aceptadas=historial).hay_pendientes


def test_solo_la_version_anterior_aceptada_sigue_pendiente() -> None:
    historial = (_aceptacion(V1, AHORA - timedelta(days=30)),)

    resultado = pendientes(publicadas=(V2,), aceptadas=historial)

    assert resultado.tipos == (TIPO,)
