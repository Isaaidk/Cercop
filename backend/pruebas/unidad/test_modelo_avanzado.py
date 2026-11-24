"""El modelo avanzado cuesta más créditos y usa su propio modelo; sin configurarlo no se ofrece."""

from contratacion.dominio.creditos import (
    COSTO_GENERAR_OFERTA,
    COSTO_GENERAR_OFERTA_AVANZADO,
    costo_generar_oferta,
)
from contratacion.infraestructura.adaptadores.salida.ia import ModeloIa


def _modelo(**extra):
    return ModeloIa(
        url="https://api.deepseek.com",
        clave="x",
        modelo="deepseek-flash",
        concurrencia=1,
        tiempo_seg=30,
        modelo_documentos="deepseek-flash",
        **extra,
    )


def test_costos():
    assert costo_generar_oferta(False) == COSTO_GENERAR_OFERTA == 3
    assert costo_generar_oferta(True) == COSTO_GENERAR_OFERTA_AVANZADO == 5


def test_avanzado_usa_su_modelo_y_su_modo_pensar():
    ia = _modelo(modelo_avanzado="deepseek-v4-pro", pensar_avanzado=True)
    assert ia.avanzado_disponible
    cuerpo: dict = {"max_tokens": 100}
    ia._modo(cuerpo, "avanzado")
    assert cuerpo["model"] == "deepseek-v4-pro"
    assert cuerpo["thinking"] == {"type": "enabled"}
    normal: dict = {}
    ia._modo(normal, "documentos")
    assert normal["model"] == "deepseek-flash"


def test_sin_modelo_avanzado_no_se_ofrece():
    ia = _modelo()
    assert not ia.avanzado_disponible
    assert ia.modelo_de("avanzado") == "deepseek-flash"
