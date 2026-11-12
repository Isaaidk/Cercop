"""Alertas: la vista previa usa la misma regla que la revisión, y la revisión no se queda corta."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from contratacion.aplicacion.casos_uso import revisar_alertas
from contratacion.infraestructura.adaptadores.salida.bd.radar import RepositorioRadar


def _oportunidad(
    objeto: str, *, provincia: str = "Pichincha", cpc: list[str] | None = None
) -> dict[str, Any]:
    return {
        "id": uuid4(),
        "fuente": "NCO",
        "codigo": "NIC-1",
        "objeto": objeto,
        "entidad": "GAD",
        "provincia": provincia,
        "canton": "",
        "cpc_codigos": cpc or [],
        "presupuesto": 1500.0,
        "plazo": None,
        "texto": objeto,
    }


class RadarFalso:
    def __init__(self, filas: list[dict[str, Any]]) -> None:
        self.filas = filas
        self.limites: list[int] = []
        self.avisos: list[dict[str, Any]] = []

    async def candidatos(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.limites.append(kwargs["limite"])
        return self.filas

    async def crear_aviso(self, aviso: dict[str, Any]) -> None:
        self.avisos.append(aviso)

    async def crear_avisos(self, avisos: list[dict[str, Any]]) -> int:
        self.avisos.extend(avisos)
        return len(avisos)


async def test_la_vista_previa_cuenta_solo_lo_que_cumple() -> None:
    radar = RadarFalso(
        [
            _oportunidad("Mantenimiento de aires acondicionados"),
            _oportunidad("Compra de papel bond"),
            _oportunidad("Mantenimiento preventivo de aire acondicionado", provincia="Guayas"),
        ]
    )
    resultado = await revisar_alertas.previsualizar_alerta(
        cast(RepositorioRadar, radar),
        {"palabras": ["aire acondicionado", "aires acondicionados"], "provincia": "Pichincha"},
    )

    assert resultado["total"] == 1
    assert resultado["muestras"][0]["objeto"] == "Mantenimiento de aires acondicionados"


async def test_sin_cpc_ni_palabras_no_consulta() -> None:
    radar = RadarFalso([_oportunidad("Lo que sea")])
    resultado = await revisar_alertas.previsualizar_alerta(cast(RepositorioRadar, radar), {})

    assert resultado["total"] == 0
    assert radar.limites == []


async def test_la_revision_mira_mas_que_cuarenta_candidatos() -> None:
    """Con 40, una alerta diaria perdía casi todo lo publicado en el día."""
    radar = RadarFalso([])
    await revisar_alertas._una(
        cast(RepositorioRadar, radar),
        {"id": uuid4(), "palabras": ["papel"], "revisada_en": None},
        datetime.now(UTC),
    )

    assert radar.limites == [revisar_alertas.CANDIDATOS_POR_REVISION]
    assert revisar_alertas.CANDIDATOS_POR_REVISION >= 1000
