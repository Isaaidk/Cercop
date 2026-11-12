"""La puntuación explica el parecido. No predice quién gana."""

from datetime import UTC, datetime, timedelta
from typing import Any

from contratacion.dominio.radar import (
    CriteriosComerciales,
    excluir,
    puntuar,
    unir_duplicados,
)


def _criterios() -> CriteriosComerciales:
    return CriteriosComerciales(
        provincias=("Pichincha",),
        cantones=("Quito",),
        cpc=("45210",),
        palabras=("mantenimiento", "computadoras"),
        presupuesto_min=1000,
        presupuesto_max=50000,
        experiencias=("mantenimiento de equipos",),
    )


def _oportunidad(**extra: Any) -> Any:
    base = {
        "provincia": "Pichincha",
        "canton": "Quito",
        "cpc_codigos": ["452100011"],
        "objeto": "Mantenimiento de computadoras del municipio",
        "texto": "",
        "presupuesto": 12000,
        "documentos": [{"nombre": "Pliego.pdf"}],
        "plazo": datetime.now(UTC) + timedelta(days=5),
        "codigo": "NIC-1",
        "ultima_vez_visto": "2026-11-01",
    }
    base.update(extra)
    return base


def test_una_oportunidad_compatible_puntua_alto_y_lo_explica() -> None:
    nota = puntuar(_criterios(), _oportunidad())
    assert nota["puntos"] >= 90
    assert nota["de"] == 100
    assert "probabilidad" in nota["aviso"]
    motivos = " ".join(factor["motivo"] for factor in nota["factores"])
    assert "CPC" in motivos
    assert "computadoras" in motivos or "mantenimiento" in motivos


def test_otra_provincia_queda_fuera() -> None:
    assert excluir(_criterios(), _oportunidad(provincia="Guayas")) is not None


def test_sin_perfil_no_hay_radar() -> None:
    vacio = CriteriosComerciales()
    assert excluir(vacio, _oportunidad()) is not None


def test_el_mismo_codigo_no_se_lista_dos_veces() -> None:
    filas = [
        _oportunidad(id="a", ultima_vez_visto="2026-11-01"),
        _oportunidad(id="b", ultima_vez_visto="2026-11-09", objeto="otra redaccion"),
    ]
    unidas, quitadas = unir_duplicados(filas)
    assert quitadas == 1
    assert len(unidas) == 1
    assert unidas[0]["id"] == "b"
