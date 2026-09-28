"""Pruebas de los endpoints de salud.

No necesitan Postgres ni Redis: comprueban que `/salud` responde siempre y que `/listo` informa
correctamente el estado de sus dependencias, sea cual sea.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from contratacion.infraestructura.app import crear_app


def _cliente() -> TestClient:
    return TestClient(crear_app())


def test_salud_responde_200() -> None:
    respuesta = _cliente().get("/salud")
    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "ok"


def test_salud_no_expone_inventario_de_endpoints() -> None:
    """El legado publicaba la lista de rutas en `/`; aquí no se repite (vulnerabilidad V11)."""
    cuerpo = _cliente().get("/salud").json()
    assert "endpoints" not in cuerpo


def test_listo_informa_el_estado_de_las_dependencias() -> None:
    respuesta = _cliente().get("/listo")
    cuerpo = respuesta.json()

    assert set(cuerpo["dependencias"]) == {"postgres", "cache"}
    assert respuesta.status_code in (200, 503)
    assert cuerpo["listo"] == (respuesta.status_code == 200)


def test_cors_no_permite_cualquier_origen() -> None:
    """Un origen no listado no debe recibir la cabecera de permiso (corrección de V1)."""
    respuesta = _cliente().get("/salud", headers={"Origin": "http://origen-no-permitido.test"})
    assert respuesta.headers.get("access-control-allow-origin") != "*"
    assert respuesta.headers.get("access-control-allow-origin") is None


def test_cors_permite_el_origen_configurado() -> None:
    respuesta = _cliente().get("/salud", headers={"Origin": "http://localhost:5173"})
    assert respuesta.headers.get("access-control-allow-origin") == "http://localhost:5173"
