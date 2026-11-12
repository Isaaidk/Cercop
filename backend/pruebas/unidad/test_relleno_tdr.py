"""El perfil rellena el TDR solo cuando la ínfima encaja."""

from typing import Any

from contratacion.dominio.relleno import proponer


def _perfil() -> dict[str, Any]:
    return {
        "razon_social": "Andina",
        "ruc": "1799999999001",
        "dedicaciones": [{"tipo_contratacion": "servicios", "tipo_procedimiento": "infima"}],
        "cpc": ["871410032"],
        "cobertura": [{"provincia": "pichincha"}],
        "contactos": [{"tipo": "representante_legal", "nombre": "Ana Ruiz"}],
        "experiencia": [
            {
                "entidad": "Municipio",
                "objeto": "Lavado",
                "cpc": "871410032",
                "tipo_contratacion": "servicios",
            }
        ],
        "personal": [{"perfil": "Técnico"}],
        "equipo": [],
        "documentos": [],
    }


def test_si_coincide_rellena_oferente_y_experiencia() -> None:
    resultado = proponer(
        _perfil(),
        provincia="pichincha",
        cpc_codigos=["871410032"],
        tipo_texto="servicios",
        es_infima=True,
        campos_pedido=["experiencia", "personal"],
    )
    assert resultado["aplica"] is True
    assert resultado["anexos"]["oferente"]["razon_social"] == "Andina"
    assert resultado["anexos"]["experiencia"]


def test_si_el_cpc_o_la_provincia_no_coinciden_no_rellena() -> None:
    resultado = proponer(
        _perfil(),
        provincia="guayas",
        cpc_codigos=["111"],
        tipo_texto="servicios",
        es_infima=True,
        campos_pedido=[],
    )
    assert resultado["aplica"] is False
    assert resultado["anexos"] == {}
    assert any("CPC" in motivo for motivo in resultado["motivos"])
    assert any("guayas" in motivo for motivo in resultado["motivos"])
