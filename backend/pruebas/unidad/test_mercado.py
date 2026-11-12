"""Los precios se resumen dentro de un CPC y no se mezclan entre categorías."""

from contratacion.dominio.mercado import agrupar_precios, requisitos_de, resumir


def test_mediana_de_una_lista_par() -> None:
    cifra = resumir([10, 30, 20, 40])
    assert cifra is not None
    assert cifra["minimo"] == 10
    assert cifra["maximo"] == 40
    assert cifra["promedio"] == 25
    assert cifra["mediana"] == 25


def test_dos_cpc_no_comparten_promedio() -> None:
    grupos = agrupar_precios(
        [
            {"cpc": ["111"], "monto": 100, "entidad": "A", "anio": "2024", "objeto": "Uno"},
            {"cpc": ["222"], "monto": 900, "entidad": "B", "anio": "2025", "objeto": "Otro"},
        ]
    )
    assert len(grupos) == 2
    assert {grupo["cpc"] for grupo in grupos} == {"111", "222"}
    assert all(grupo["mismo_cpc"] for grupo in grupos)
    assert grupos[0]["resumen"]["promedio"] != 500


def test_sin_cpc_advierte_que_el_alcance_puede_distinto() -> None:
    grupos = agrupar_precios(
        [
            {"cpc": [], "monto": 10, "entidad": "A", "anio": "2024", "objeto": "Un equipo"},
            {"cpc": [], "monto": 1000, "entidad": "A", "anio": "2024", "objeto": "Cien equipos"},
        ]
    )
    assert len(grupos) == 1
    assert grupos[0]["mismo_cpc"] is False
    assert "cantidades distintas" in grupos[0]["aviso"]


def test_requisitos_salen_de_los_documentos() -> None:
    nombres = requisitos_de(
        [
            {"nombre": "Pliego", "campos_pedido": ["garantía"]},
            {"nombre": "Pliego", "campos_pedido": []},
        ]
    )
    assert nombres == ["Pliego", "garantía"]
