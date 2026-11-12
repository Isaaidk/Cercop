"""Datos de la entidad desde el texto del TDR: lo que la proforma necesitaba y salía vacío."""

from __future__ import annotations

from contratacion.dominio.entidad import completar_entidad, datos_entidad_de_texto

TDR = """
GOBIERNO AUTÓNOMO DESCENTRALIZADO PARROQUIAL RURAL DE FACUNDO VELA
RUC: 0260008780001
Dirección: Calle principal s/n y Av. 10 de Agosto, junto al parque central
Teléfono: 03 297 1234
Correo: gadfacundovela@yahoo.es  ·  compras@facundovela.gob.ec

ACEPTACIÓN: …………… con RUC ……………: certifica que el bien cumplirá…
El proveedor con RUC 1715234660001, teléfono 0987861415, dirección: Quito.
ADMINISTRADOR DE LA ORDEN: Ing. Pérez, celular: ……….., correo electrónico: ……@heg.gob.ec
"""


def test_saca_ruc_direccion_telefono_y_correo_de_la_entidad() -> None:
    datos = datos_entidad_de_texto(TDR)
    assert datos["ruc"] == "0260008780001"
    assert datos["direccion"].startswith("Calle principal s/n y Av. 10 de Agosto")
    assert datos["telefono"] == "03 297 1234"
    assert datos["correo"] == "compras@facundovela.gob.ec"


def test_no_toma_los_datos_del_proveedor_ni_los_huecos() -> None:
    texto = (
        "El proveedor con RUC 1715234660001 y teléfono 0987861415.\n"
        "Dirección: ……………………\nTeléfono: ………..\n"
    )
    assert datos_entidad_de_texto(texto) == {}


def test_la_ficha_manda_y_el_tdr_completa() -> None:
    ficha = {"ruc": "0960001234001", "direccion": "", "telefono": ""}
    del_tdr = {"ruc": "0260008780001", "direccion": "Calle 1", "telefono": "03 297 1234"}
    assert completar_entidad(ficha, del_tdr) == {
        "ruc": "0960001234001",
        "direccion": "Calle 1",
        "telefono": "03 297 1234",
    }
