"""Pruebas del montaje del enrutador de presencia.

Comprueba lo que las pruebas de lógica no pueden: que los endpoints **existan** y que **exijan
autenticación**. Un enrutador sin montar es un 404 silencioso, y uno montado sin la dependencia del
actor es un endpoint abierto que sirve a quien pregunte; ninguna de las dos cosas se ve en una
prueba de unidad.

No necesita base de datos: la negativa por falta de token ocurre antes de que ninguna dependencia
toque Postgres.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from contratacion.infraestructura.app import crear_app

RUTAS_PROTEGIDAS = (
    ("GET", "/v1/presencia"),
    ("POST", "/v1/presencia/latido"),
    ("POST", "/v1/presencia/cierre"),
    ("GET", "/v1/presencia/eventos"),
)


@pytest.fixture
def cliente() -> TestClient:
    return TestClient(crear_app())


@pytest.mark.parametrize(("metodo", "ruta"), RUTAS_PROTEGIDAS)
def test_sin_credenciales_la_presencia_no_se_sirve(
    cliente: TestClient, metodo: str, ruta: str
) -> None:
    """401 y no 404: el endpoint existe, y precisamente por existir está cerrado.

    La diferencia importa. Un 404 significaría que el enrutador no se montó y que el panel fallaría
    en producción con un error que parece un problema de rutas; un 401 significa que la ruta está y
    que hay que autenticarse, que es lo correcto.
    """
    respuesta = cliente.request(metodo, ruta, json={})
    assert respuesta.status_code == 401, respuesta.text


@pytest.mark.parametrize(("metodo", "ruta"), RUTAS_PROTEGIDAS)
def test_la_negativa_indica_que_hace_falta_un_token(
    cliente: TestClient, metodo: str, ruta: str
) -> None:
    """El encabezado es lo que hace que un cliente sepa que debe autenticarse, y no reintentar."""
    respuesta = cliente.request(metodo, ruta, json={})
    assert respuesta.headers.get("WWW-Authenticate") == "Bearer"


def test_las_rutas_de_presencia_estan_en_el_contrato(cliente: TestClient) -> None:
    """Si desaparecen del contrato, el panel que las consume se entera en tiempo de desarrollo."""
    rutas = cliente.get("/openapi.json").json()["paths"]
    assert "/v1/presencia" in rutas
    assert "/v1/presencia/latido" in rutas
    assert "/v1/presencia/cierre" in rutas
    assert "/v1/presencia/eventos" in rutas


def test_el_canal_de_eventos_se_anuncia_como_flujo(cliente: TestClient) -> None:
    """Un canal que se consume por partes no se puede documentar como una respuesta normal.

    Se comprueba que el contrato lo declare como `text/event-stream`, porque es lo que hace que el
    panel sepa que debe leerlo por trozos y no esperar a que termine —cosa que nunca ocurriría, ya
    que el flujo está pensado para quedarse abierto mientras la persona mire el panel—.
    """
    operacion = cliente.get("/openapi.json").json()["paths"]["/v1/presencia/eventos"]["get"]
    respuestas = operacion["responses"]["200"]
    assert "text/event-stream" in str(respuestas)


def test_los_endpoints_de_presencia_van_etiquetados(cliente: TestClient) -> None:
    """Para que el panel los encuentre juntos y no repartidos por la documentación."""
    operacion = cliente.get("/openapi.json").json()["paths"]["/v1/presencia"]["get"]
    assert operacion["tags"] == ["Presencia"]
