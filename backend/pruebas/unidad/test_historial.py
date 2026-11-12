"""Historial de contratos por RUC: se verifica por RUC, no por nombre; el servicio se simula."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import uuid4

import httpx
import pytest

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.casos_uso.gestionar_perfil import consultar_historial
from contratacion.dominio.errores import DatoInvalido, EstadoInvalido, SinPermiso
from contratacion.dominio.historial import contrato_de, resumir_historial, termino_de_busqueda
from contratacion.infraestructura.adaptadores.salida import historial as modulo
from contratacion.infraestructura.adaptadores.salida.historial import HistorialOcds

RUC = "2390030234001"


def _record(ruc: str = RUC, cpc: str = "134929123", fecha: str = "2026-01-06") -> dict[str, Any]:
    return {
        "releases": [
            {
                "ocid": f"ocds-{cpc}-{fecha}",
                "date": f"{fecha}T00:00:00-05:00",
                "buyer": {"id": "EC-RUC-1791825314001", "name": "FUNDACION CALASANZ"},
                "tender": {
                    "title": "Orden de compra",
                    "description": "Frutas   frescas",
                    "value": {"amount": 222.01},
                },
                "parties": [
                    {"id": f"EC-RUC-{ruc}-821234", "name": "ASOCANASTA", "roles": ["supplier"]},
                ],
                "awards": [
                    {
                        "value": {"amount": 222.01},
                        "suppliers": [{"id": f"EC-RUC-{ruc}-821234", "name": "ASOCANASTA"}],
                        "items": [
                            {
                                "classification": {
                                    "id": cpc,
                                    "scheme": "CPC",
                                    "description": "CANASTA DE FRUTAS",
                                }
                            },
                            {"classification": {"id": "99", "scheme": "OTRO"}},
                        ],
                    }
                ],
            }
        ]
    }


def test_el_nombre_se_busca_sin_forma_societaria() -> None:
    assert termino_de_busqueda("Suministros Andinos S.A.") == "SUMINISTROS ANDINOS"
    assert termino_de_busqueda("ÁNDES CIA. LTDA.") == "ÁNDES"
    assert termino_de_busqueda('ASOCIACION LA CANASTA "ASOCANASTA"') == "ASOCIACION LA CANASTA"
    assert termino_de_busqueda("Comercial S.A. del Sur") == "COMERCIAL S.A. DEL SUR"


def test_un_contrato_solo_cuenta_si_el_adjudicatario_tiene_ese_ruc() -> None:
    propio = contrato_de(_record(), RUC)
    assert propio is not None
    assert propio["cpc"] == {"134929123": "CANASTA DE FRUTAS"}
    assert propio["descripcion"] == "Frutas frescas"
    assert propio["productos"] == []
    assert propio["monto"] == 222.01
    # Un homónimo (otro RUC) se descarta aunque el nombre coincida.
    assert contrato_de(_record(ruc="1790000000001"), RUC) is None
    assert contrato_de({"nada": 1}, RUC) is None


def test_los_cpc_se_cuentan_y_la_experiencia_sale_ordenada() -> None:
    contratos = [
        contrato_de(_record(cpc="111", fecha="2024-03-01"), RUC),
        contrato_de(_record(cpc="111", fecha="2026-02-01"), RUC),
        contrato_de(_record(cpc="222", fecha="2025-06-01"), RUC),
    ]
    resumen = resumir_historial(
        RUC, [c for c in contratos if c is not None], total=30, revisados=3, termino="X"
    )
    assert resumen["cpc"][0] == {"codigo": "111", "descripcion": "CANASTA DE FRUTAS", "veces": 2}
    assert [fila["anio"] for fila in resumen["experiencia"]] == [2026, 2025, 2024]
    assert resumen["verificados"] == 3 and resumen["contratos_total"] == 30
    assert "RUP" in resumen["aviso"]


def _servicio(homonimo: bool = False, caido: bool = False) -> HistorialOcds:
    def responder(peticion: httpx.Request) -> httpx.Response:
        if caido:
            return httpx.Response(503)
        if peticion.url.path.endswith("search_ocds"):
            anio = peticion.url.params["year"]
            return httpx.Response(
                200,
                content=json.dumps(
                    {
                        "total": 4,
                        "page": 1,
                        "pages": 1,
                        "data": [
                            {"ocid": f"{anio}-{n}", "date": f"{anio}-0{n + 1}-01"} for n in range(2)
                        ],
                    }
                ),
            )
        ruc = "1790000000001" if homonimo else RUC
        return httpx.Response(200, content=json.dumps(_record(ruc=ruc)))

    modulo._RECORDADOS.clear()
    return HistorialOcds(transporte=httpx.MockTransport(responder))


def test_el_historial_se_arma_con_lo_verificado() -> None:
    resumen = asyncio.run(_servicio().consultar(RUC, "Andinos S.A."))
    assert resumen["contratos_total"] == 12  # 3 años x 4
    assert resumen["revisados"] == 6
    assert resumen["verificados"] == 6
    assert resumen["cpc"][0]["codigo"] == "134929123"


def test_los_homonimos_no_entran() -> None:
    resumen = asyncio.run(_servicio(homonimo=True).consultar(RUC, "Andinos S.A."))
    assert resumen["verificados"] == 0 and resumen["cpc"] == []


def test_se_recuerda_la_respuesta() -> None:
    servicio = _servicio()
    primero = asyncio.run(servicio.consultar(RUC, "Andinos S.A."))
    caido = HistorialOcds(transporte=httpx.MockTransport(lambda _: httpx.Response(503)))
    assert asyncio.run(caido.consultar(RUC, "Andinos S.A.")) is primero


def test_el_servicio_caido_dice_que_se_agregue_a_mano() -> None:
    with pytest.raises(EstadoInvalido, match="a mano"):
        asyncio.run(_servicio(caido=True).consultar(RUC, "Andinos S.A."))


def _actor(rol: str = "dueno_empresa") -> Actor:
    return Actor(usuario_id=uuid4(), negocio_id=uuid4(), rol=rol)


def test_permisos_y_validacion_del_caso_de_uso() -> None:
    servicio = _servicio()
    with pytest.raises(SinPermiso):
        asyncio.run(
            consultar_historial(_actor("usuario"), ruc=RUC, razon_social="X Y", historial=servicio)
        )
    with pytest.raises(DatoInvalido):
        asyncio.run(
            consultar_historial(
                _actor(), ruc="1234567890000", razon_social="X Y", historial=servicio
            )
        )
    with pytest.raises(DatoInvalido):
        asyncio.run(consultar_historial(_actor(), ruc=RUC, razon_social="  ", historial=servicio))
