"""«Mis ofertas»: etapas, tasa de éxito y recordatorio de cierre."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import pytest

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.casos_uso.seguimiento_ofertas import (
    mover_oferta,
    recordar_cierres,
    resumir,
)
from contratacion.dominio.errores import DatoInvalido, NoEncontrado
from contratacion.infraestructura.adaptadores.salida.bd.seguimiento import (
    RepositorioSeguimiento,
)

ACTOR = Actor(usuario_id=uuid4(), negocio_id=uuid4(), rol="usuario")


def test_la_tasa_de_exito_cuenta_solo_las_resueltas() -> None:
    resumen = resumir(
        [
            {"etapa": "adjudicada", "total": 1000, "monto_adjudicado": 950},
            {"etapa": "perdida", "total": 500},
            {"etapa": "perdida", "total": 300},
            {"etapa": "enviada", "total": 700},
            {"etapa": "borrador", "total": 200},
        ]
    )

    assert resumen["tasa_exito"] == pytest.approx(33.3)
    assert resumen["adjudicado"] == 950
    assert resumen["en_juego"] == 900
    assert resumen["por_etapa"]["perdida"]["cantidad"] == 2


def test_sin_resueltas_no_hay_tasa() -> None:
    assert resumir([{"etapa": "enviada", "total": 10}])["tasa_exito"] is None


class RepoFalso:
    def __init__(self, existe: bool = True) -> None:
        self.existe = existe
        self.cambios: list[dict[str, Any]] = []
        self.recordados: list[str] = []
        self.pendientes: list[dict[str, Any]] = []

    async def actualizar(self, **kwargs: Any) -> bool:
        self.cambios.append(kwargs["campos"])
        return self.existe

    async def por_cerrar(self, *, horas: int) -> list[dict[str, Any]]:
        return self.pendientes

    async def recordar(self, fila: dict[str, Any], *, titulo: str, detalle: str) -> None:
        self.recordados.append(titulo)


async def test_mover_valida_la_etapa_y_la_nota() -> None:
    repo = RepoFalso()
    with pytest.raises(DatoInvalido):
        await mover_oferta(
            ACTOR,
            repositorio=cast(RepositorioSeguimiento, repo),
            proforma_id=uuid4(),
            campos={"etapa": "ganadisima"},
        )
    with pytest.raises(DatoInvalido):
        await mover_oferta(
            ACTOR,
            repositorio=cast(RepositorioSeguimiento, repo),
            proforma_id=uuid4(),
            campos={"nota": "x" * 501},
        )
    await mover_oferta(
        ACTOR,
        repositorio=cast(RepositorioSeguimiento, repo),
        proforma_id=uuid4(),
        campos={"etapa": "adjudicada", "monto_adjudicado": 950.5},
    )
    assert repo.cambios == [{"etapa": "adjudicada", "monto_adjudicado": 950.5}]


async def test_mover_una_proforma_ajena_es_no_encontrada() -> None:
    with pytest.raises(NoEncontrado):
        await mover_oferta(
            ACTOR,
            repositorio=cast(RepositorioSeguimiento, RepoFalso(existe=False)),
            proforma_id=uuid4(),
            campos={"etapa": "enviada"},
        )


async def test_recordatorio_de_cierre() -> None:
    repo = RepoFalso()
    repo.pendientes = [
        {
            "id_proforma": uuid4(),
            "id_negocio": uuid4(),
            "id_usuario": uuid4(),
            "id_registro": uuid4(),
            "objeto_texto": "Mantenimiento de aires",
            "titulo_texto": "Proforma",
            "entidad_texto": "GAD",
            "cierra_en": datetime.now(UTC) + timedelta(hours=10),
        }
    ]

    assert await recordar_cierres(cast(RepositorioSeguimiento, repo)) == 1
    assert repo.recordados[0].startswith("Cierra en")
    assert "Mantenimiento de aires" in repo.recordados[0]
