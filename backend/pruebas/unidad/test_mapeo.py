"""Pruebas del motor de mapeo.

El mapeo es lo que convierte el payload sucio de la fuente en campos canónicos. Se prueba con los
casos reales que se encontraron en el sistema anterior: HTML embebido, «AZUAY - CUENCA», fechas en
varios formatos y montos con separadores.
"""

from __future__ import annotations

from typing import Any

import pytest

from contratacion.aplicacion.mapeo import MapeoCampo, aplicar, campos_requeridos_ausentes, convertir


def _mapeo(
    clave: str,
    canonico: str,
    tipo: str = "texto",
    transformacion: dict[str, Any] | None = None,
    requerido: bool = False,
) -> MapeoCampo:
    return MapeoCampo(
        clave_cruda=clave,
        campo_canonico=canonico,
        tipo_dato=tipo,
        transformacion=transformacion or {},
        requerido=requerido,
    )


# --------------------------------------------------------------------------- #
# Transformaciones
# --------------------------------------------------------------------------- #


def test_html_a_texto_convierte_saltos_y_etiquetas() -> None:
    regla = _mapeo("contacto", "contacto", transformacion={"operacion": "html_a_texto"})
    valor = "<b>Juan Pérez</b><br/>Email: j@test.ec<br/>Teléfono: 0999999999"
    assert convertir(valor, regla) == "Juan Pérez | Email: j@test.ec | Teléfono: 0999999999"


def test_html_a_texto_desescapa_entidades() -> None:
    regla = _mapeo("x", "x", transformacion={"operacion": "html_a_texto"})
    assert convertir("Obras &amp; Servicios", regla) == "Obras & Servicios"


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("2026-09-27 14:30:00", "2026-09-27T14:30:00"),
        ("2026-09-27 14:30", "2026-09-27T14:30:00"),
        ("2026-09-27", "2026-09-27T00:00:00"),
        ("27/09/2026", "2026-09-27T00:00:00"),
    ],
)
def test_fechas_en_varios_formatos(entrada: str, esperado: str) -> None:
    regla = _mapeo("fecha", "fecha", tipo="fecha_hora")
    assert convertir(entrada, regla) == esperado


def test_una_fecha_ilegible_no_se_inventa() -> None:
    """Es preferible dejar el campo vacío que guardar una fecha falsa."""
    assert convertir("no es una fecha", _mapeo("fecha", "fecha", tipo="fecha")) is None


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("2026-02-09T00:00:00-05:00", "2026-02-09T00:00:00-05:00"),
        ("2026-09-26T15:04:07-05:00", "2026-09-26T15:04:07-05:00"),
        ("2026-09-26T15:04:07Z", "2026-09-26T15:04:07+00:00"),
    ],
)
def test_fechas_iso_8601_de_los_datos_abiertos(entrada: str, esperado: str) -> None:
    """La fecha de los datos abiertos llegaba en un formato que no se reconocía.

    OCDS publica sus fechas completas —con la `T` y el desfase horario—, y ninguno de los formatos
    de la lista las cubría. `convertir` devolvía `None` y el campo se descartaba en silencio: las
    cincuenta y tres filas de OCDS quedaban sin fecha de publicación, sin ningún error que lo
    dijera y con el filtro «desde/hasta» sin efecto sobre esa fuente.
    """
    regla = _mapeo("fecha", "fecha", tipo="fecha_hora")
    assert convertir(entrada, regla) == esperado


def test_los_formatos_de_siempre_no_cambian() -> None:
    """Añadir el ISO 8601 no puede alterar cómo se leen las fechas que ya funcionaban."""
    regla = _mapeo("fecha", "fecha", tipo="fecha_hora")
    assert convertir("27/09/2026", regla) == "2026-09-27T00:00:00"
    assert convertir("2026-09-27", regla) == "2026-09-27T00:00:00"


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [("1.234,56", 1234.56), ("1234.56", 1234.56), ("$ 500", 500.0), ("", None), ("n/a", None)],
)
def test_montos(entrada: str, esperado: float | None) -> None:
    assert convertir(entrada, _mapeo("monto", "monto", tipo="moneda")) == esperado


def test_entero() -> None:
    assert convertir("42", _mapeo("cantidad", "cantidad", tipo="entero")) == 42


@pytest.mark.parametrize(("entrada", "esperado"), [("Sí", True), ("NO", False), ("quizá", None)])
def test_booleano(entrada: str, esperado: bool | None) -> None:
    assert convertir(entrada, _mapeo("vigente", "vigente", tipo="booleano")) == esperado


def test_separar_por() -> None:
    regla = _mapeo(
        "etiquetas",
        "etiquetas",
        transformacion={"operacion": "separar_por", "separador": "|"},
    )
    assert convertir("salud|obras", regla) == ["salud", "obras"]


def test_regex_extrae_el_enlace_del_html() -> None:
    """La fuente entrega el enlace dentro de un `<a href=...>`."""
    regla = _mapeo(
        "url",
        "enlace",
        transformacion={"operacion": "regex", "patron": r"href\s*=\s*['\"]?([^'\"\s>]+)"},
    )
    crudo = "<a href=../NCO/NCORegistroDetalle.cpe?&id=1,&op=0>ENTIDAD</a>"
    assert convertir(crudo, regla) == "../NCO/NCORegistroDetalle.cpe?&id=1,&op=0"


def test_regex_conserva_el_valor_si_no_coincide() -> None:
    """Perder el dato por un cambio de formato sería peor que traerlo sin limpiar."""
    regla = _mapeo(
        "provincia", "provincia", transformacion={"operacion": "regex", "patron": r"^(.*?)\s+-\s+"}
    )
    assert convertir("AZUAY - CUENCA", regla) == "AZUAY"
    assert convertir("PICHINCHA", regla) == "PICHINCHA"


def test_un_valor_vacio_da_nulo() -> None:
    assert convertir("   ", _mapeo("x", "x")) is None


# --------------------------------------------------------------------------- #
# Aplicación del catálogo
# --------------------------------------------------------------------------- #


def test_aplicar_traduce_y_detecta_lo_desconocido() -> None:
    mapeos = [_mapeo("titulo", "codigo"), _mapeo("estado", "estado")]
    crudo = {"titulo": "NCO-1", "estado": "En Curso", "campo_nuevo": "algo"}

    datos, sin_mapear = aplicar(mapeos, crudo)

    assert datos == {"codigo": "NCO-1", "estado": "En Curso"}
    assert sin_mapear == ("campo_nuevo",)


def test_las_claves_internas_del_adaptador_se_ignoran() -> None:
    """`_termino_buscado` lo añade el adaptador; no es un campo de la fuente."""
    mapeos = [_mapeo("ocid", "ocid")]
    datos, sin_mapear = aplicar(mapeos, {"ocid": "x", "_termino_buscado": "salud"})

    assert datos == {"ocid": "x"}
    assert sin_mapear == ()


def test_los_campos_requeridos_ausentes_se_detectan() -> None:
    """Sirve para avisar de que la fuente dejó de publicar algo que el producto necesita."""
    mapeos = [_mapeo("codigo", "codigo", requerido=True), _mapeo("estado", "estado")]
    assert campos_requeridos_ausentes(mapeos, {"estado": "En Curso"}) == ("codigo",)


def test_un_campo_requerido_vacio_se_conserva_como_nulo() -> None:
    """Si es requerido, interesa que quede constancia de que llegó vacío."""
    mapeos = [_mapeo("codigo", "codigo", requerido=True)]
    datos, _ = aplicar(mapeos, {"codigo": ""})
    assert datos == {"codigo": None}
