"""Pruebas del montaje del enrutador de la plataforma, y de sus borrados.

Comprueba lo que las pruebas de lógica no pueden: que los endpoints **existan**, que **exijan
autenticación** y que el borrado **exija la confirmación**. Una ruta sin montar es un 404
silencioso, una ruta montada sin la dependencia del actor es un endpoint abierto, y un borrado sin
el parámetro de confirmación sería la operación más destructiva del sistema a un clic de distancia.
Ninguna de las tres cosas se ve en una prueba de unidad.

No necesita base de datos: la negativa por falta de token ocurre antes de que ninguna dependencia
toque Postgres, y el contrato sale del propio esquema de OpenAPI.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from contratacion.infraestructura.app import crear_app

NEGOCIO = "22222222-2222-2222-2222-222222222222"
USUARIO = "11111111-1111-1111-1111-111111111111"

RUTAS_PROTEGIDAS = (
    ("GET", "/v1/plataforma/empresas"),
    ("GET", "/v1/plataforma/ingesta/historial"),
    ("POST", "/v1/plataforma/ingesta/solicitud"),
    ("POST", f"/v1/plataforma/empresas/{NEGOCIO}/suspension"),
    ("POST", f"/v1/plataforma/empresas/{NEGOCIO}/reactivacion"),
    ("DELETE", f"/v1/plataforma/empresas/{NEGOCIO}"),
    ("DELETE", f"/v1/plataforma/empresas/{NEGOCIO}/usuarios/{USUARIO}"),
)


@pytest.fixture
def cliente() -> TestClient:
    return TestClient(crear_app())


@pytest.mark.parametrize(("metodo", "ruta"), RUTAS_PROTEGIDAS)
def test_sin_credenciales_la_plataforma_no_se_sirve(
    cliente: TestClient, metodo: str, ruta: str
) -> None:
    """401 y no 404: el endpoint existe, y precisamente por existir está cerrado."""
    respuesta = cliente.request(metodo, ruta, json={})
    assert respuesta.status_code == 401, respuesta.text


def test_los_borrados_estan_en_el_contrato(cliente: TestClient) -> None:
    """Si desaparecen del contrato, el panel que los consume se entera en tiempo de desarrollo."""
    rutas = cliente.get("/openapi.json").json()["paths"]
    assert "delete" in rutas["/v1/plataforma/empresas/{negocio_id}"]
    assert "delete" in rutas["/v1/plataforma/empresas/{negocio_id}/usuarios/{usuario_id}"]


@pytest.mark.parametrize(
    "ruta",
    [
        "/v1/plataforma/empresas/{negocio_id}",
        "/v1/plataforma/empresas/{negocio_id}/usuarios/{usuario_id}",
    ],
)
def test_el_borrado_exige_la_confirmacion(cliente: TestClient, ruta: str) -> None:
    """`confirmacion` tiene que estar en el contrato y ser obligatoria.

    Es la única traba que separa un borrado irreversible de un clic de más, así que se comprueba en
    el contrato y no solo en el código: un parámetro que se colara como opcional convertiría la
    operación en algo que ocurre sin escribir nada.
    """
    operacion = cliente.get("/openapi.json").json()["paths"][ruta]["delete"]
    parametros = {p["name"]: p for p in operacion.get("parameters", [])}

    assert "confirmacion" in parametros, "el borrado sin confirmación no puede existir"
    assert parametros["confirmacion"]["required"] is True
    assert parametros["confirmacion"]["in"] == "query"


def test_falta_la_confirmacion_y_no_se_borra_nada(cliente: TestClient) -> None:
    """Sin el parámetro la petición ni llega al caso de uso: 401 primero, 422 después.

    Aquí se comprueba la forma de la negativa sin credenciales, que es la que se puede provocar sin
    base de datos: el orden de las dos comprobaciones —autenticación antes que validación— es el que
    hace que un desconocido no pueda usar los mensajes de validación para sondear el sistema.
    """
    respuesta = cliente.delete(f"/v1/plataforma/empresas/{NEGOCIO}")
    assert respuesta.status_code == 401, respuesta.text


def test_los_endpoints_de_la_plataforma_van_etiquetados(cliente: TestClient) -> None:
    """Para que el panel los encuentre juntos y no repartidos por la documentación."""
    operacion = cliente.get("/openapi.json").json()["paths"]["/v1/plataforma/empresas"]["get"]
    assert operacion["tags"] == ["Plataforma"]
