"""Si el portal no contesta al servidor: mensaje claro y enlaces para bajarlo desde el navegador."""

from __future__ import annotations

from typing import Any

from contratacion.aplicacion.casos_uso import preparar_documentos as pd


def test_un_error_del_proxy_no_llega_crudo_a_la_pantalla() -> None:
    for crudo in (
        "ProxyError: 500 Internal Server Error",
        "ConnectTimeout: timed out",
        "ReadTimeout: x",
        "RemoteProtocolError: y",
    ):
        mensaje = pd._error_de_bajada(crudo)
        assert "ProxyError" not in mensaje and "portal" in mensaje and "Súbelo" in mensaje


def test_los_errores_que_no_son_de_red_se_muestran_tal_cual() -> None:
    assert pd._error_de_bajada("El archivo supera 25 MB.") == "El archivo supera 25 MB."


def test_solo_se_ofrecen_enlaces_del_propio_portal(monkeypatch: Any) -> None:
    anexos = [
        {"nombre": "TDR.pdf", "enlace": "../GE/ExeGENBajarArchivoGeneral.cpe?Archivo=abc,"},
        {"nombre": "malo.pdf", "enlace": "https://atacante.example/x.pdf"},
        {"nombre": "http.pdf", "enlace": "http://www.compraspublicas.gob.ec/x.pdf"},
    ]
    monkeypatch.setattr(pd, "_anexos_del_proceso", lambda ficha: anexos)
    enlaces = pd._enlaces_al_portal({})
    assert enlaces == [
        {
            "nombre": "TDR.pdf",
            "url": "https://www.compraspublicas.gob.ec/ProcesoContratacion/compras/GE/"
            "ExeGENBajarArchivoGeneral.cpe?Archivo=abc,",
        }
    ]
