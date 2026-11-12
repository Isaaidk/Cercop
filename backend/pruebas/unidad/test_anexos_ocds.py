"""Anexos y monto de un proceso con oferta (OCDS): lectura del `record`, elección y caso de uso.

El fixture `datos/ocds_record_reducido.json` sale de dos `record?ocid=` reales pedidos el
2026-11-11, recortados a los campos que se leen. Ninguno trae documentos —la fuente no los
publica—, así que los documentos de las pruebas de elección se añaden con la forma del estándar.
"""

from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from contratacion.aplicacion.casos_uso.anexos_ocds import (
    AVISO_SIN_DOCUMENTOS,
    NoEsProcesoOcds,
    anexos_del_proceso,
)
from contratacion.dominio.acceso import Vista
from contratacion.dominio.anexos import ACTA, PLIEGO, TDR, clasificar
from contratacion.dominio.errores import EstadoInvalido, NoEncontrado, SinPermiso
from contratacion.infraestructura.adaptadores.salida.fuentes import ocds_proceso as modulo
from contratacion.infraestructura.adaptadores.salida.fuentes.ocds_masiva import (
    traducir_publicacion,
)
from contratacion.infraestructura.adaptadores.salida.fuentes.ocds_proceso import (
    FichasOcds,
    ficha_del_record,
)

_FIXTURE = json.loads(
    (Path(__file__).parent / "datos" / "ocds_record_reducido.json").read_text(encoding="utf-8")
)
RECORD_VALOR = next(v for k, v in _FIXTURE.items() if k.startswith("RE-RA"))
RECORD_SUBASTA = next(v for k, v in _FIXTURE.items() if k.startswith("SIE"))
OCID = "ocds-5wno2w-RE-RA-HEEE-2026-002-52558"


def _con_documentos(record: dict[str, Any]) -> dict[str, Any]:
    copia = copy.deepcopy(record)
    publicacion = copia["releases"][0]
    base = "https://ejemplo.gob.ec/archivos"
    publicacion["tender"]["documents"] = [
        {
            "id": "1",
            "documentType": "biddingDocuments",
            "title": "Pliego del proceso",
            "url": f"{base}/pliego.pdf",
            "datePublished": "2026-06-01T10:00:00-05:00",
            "format": "application/pdf",
        },
        {
            "id": "2",
            "documentType": "technicalSpecifications",
            "title": "Términos de referencia",
            "url": f"{base}/tdr.pdf",
            "datePublished": "2026-06-01T10:00:00-05:00",
        },
        {
            "id": "3",
            "documentType": "clarifications",
            "title": "Acta de preguntas y respuestas",
            "url": f"{base}/acta-1.pdf",
            "datePublished": "2026-06-05T10:00:00-05:00",
        },
        {
            "id": "4",
            "documentType": "clarifications",
            "title": "Acta de aclaraciones",
            "url": f"{base}/acta-2.pdf",
            "datePublished": "2026-06-09T10:00:00-05:00",
        },
        # Una URL que no es http no se ofrece nunca.
        {"id": "5", "title": "Acta trucada", "url": "javascript:alert(1)"},
    ]
    publicacion["awards"][0]["documents"] = [
        {
            "id": "6",
            "documentType": "awardNotice",
            "title": "Acta de apertura",
            "url": f"{base}/acta-apertura.pdf",
            "datePublished": "2026-06-07T10:00:00-05:00",
        },
        # La misma URL en otra etapa se devuelve una sola vez.
        {"id": "7", "title": "Pliego del proceso", "url": f"{base}/pliego.pdf"},
    ]
    return copia


# --- Lectura del record ---------------------------------------------------- #


def test_el_monto_sale_de_tender_value_y_el_adjudicado_va_aparte() -> None:
    ficha = ficha_del_record(RECORD_VALOR)
    assert ficha is not None
    assert ficha["presupuesto"] == {
        "monto": 15600.0,
        "moneda": "USD",
        "fuente": "tender.value",
        "etiqueta_fuente": "Presupuesto referencial del proceso",
    }
    assert ficha["adjudicado"] == {"monto": 15600.0, "moneda": "USD"}
    assert ficha["codigo"] == "RE-RA-HEEE-2026-002-52558"
    # Comprobado contra la fuente: el SERCOP no publica documentos en OCDS.
    assert ficha["documentos"] == []


def test_la_subasta_sin_tender_value_usa_los_lotes() -> None:
    ficha = ficha_del_record(RECORD_SUBASTA)
    assert ficha is not None
    assert ficha["presupuesto"]["monto"] == 17375.0
    assert ficha["presupuesto"]["fuente"] == "tender.lots"
    assert ficha["adjudicado"] is None


def test_el_presupuesto_anidado_del_sercop_se_lee() -> None:
    record = copy.deepcopy(RECORD_VALOR)
    del record["releases"][0]["tender"]["value"]
    ficha = ficha_del_record(record)
    assert ficha is not None
    assert ficha["presupuesto"]["fuente"] == "planning.budget"
    assert ficha["presupuesto"]["monto"] == 15600.0


def test_un_budget_solo_con_partida_no_inventa_monto() -> None:
    record = copy.deepcopy(RECORD_SUBASTA)
    del record["releases"][0]["tender"]["lots"]
    ficha = ficha_del_record(record)
    assert ficha is not None
    assert ficha["presupuesto"] is None


def test_las_aclaraciones_salen_de_la_mas_reciente_a_la_mas_antigua() -> None:
    ficha = ficha_del_record(RECORD_SUBASTA)
    assert ficha is not None
    aclaraciones = ficha["aclaraciones"]
    assert len(aclaraciones) == 2
    assert all(a["pregunta"] and a["respuesta"] for a in aclaraciones)
    fechas = [str(a["fecha_respuesta"]) for a in aclaraciones]
    assert fechas == sorted(fechas, reverse=True)


def test_los_documentos_se_leen_de_todas_las_etapas_sin_repetir_ni_urls_raras() -> None:
    ficha = ficha_del_record(_con_documentos(RECORD_VALOR))
    assert ficha is not None
    enlaces = [d["enlace"] for d in ficha["documentos"]]
    assert len(enlaces) == len(set(enlaces)) == 5
    assert all(e.startswith("https://") for e in enlaces)
    pliego = ficha["documentos"][0]
    assert pliego["tipo_fuente"] == "biddingDocuments"
    assert pliego["fecha"] == "2026-06-01T10:00:00-05:00"
    assert pliego["formato"] == "application/pdf"


def test_un_record_sin_publicaciones_no_es_ficha() -> None:
    assert ficha_del_record({"releases": []}) is None


def test_la_compilada_estandar_tambien_se_entiende() -> None:
    publicacion = RECORD_VALOR["releases"][0]
    assert ficha_del_record({"records": [{"compiledRelease": publicacion}]}) is not None


def test_clarifications_cuenta_como_acta() -> None:
    assert clasificar("Documento 4", "clarifications") == ACTA


def test_la_descarga_masiva_ya_no_pierde_el_presupuesto_anidado() -> None:
    fila = traducir_publicacion(RECORD_VALOR["releases"][0])
    assert fila["budget"] == "15600.000000"


# --- Adaptador HTTP con transporte simulado -------------------------------- #


@pytest.fixture(autouse=True)
def _sin_memoria() -> None:
    modulo.olvidar_fichas()


def _fichas(respuesta: httpx.Response, llamadas: list[str] | None = None) -> FichasOcds:
    def responder(peticion: httpx.Request) -> httpx.Response:
        if llamadas is not None:
            llamadas.append(str(peticion.url))
        return respuesta

    return FichasOcds(transporte=httpx.MockTransport(responder))


def test_la_ficha_se_pide_una_vez_y_se_recuerda() -> None:
    llamadas: list[str] = []
    fichas = _fichas(httpx.Response(200, json=RECORD_VALOR), llamadas)
    primera = asyncio.run(fichas.leer(OCID))
    segunda = asyncio.run(fichas.leer(OCID))
    assert primera == segunda
    assert len(llamadas) == 1
    assert "record?ocid=" in llamadas[0]


def test_la_fuente_caida_es_estado_invalido() -> None:
    with pytest.raises(EstadoInvalido):
        asyncio.run(_fichas(httpx.Response(503)).leer(OCID))


def test_un_proceso_que_la_fuente_no_tiene_es_no_encontrado() -> None:
    with pytest.raises(NoEncontrado):
        asyncio.run(_fichas(httpx.Response(200, json={"releases": []})).leer(OCID))


# --- Caso de uso con dobles ------------------------------------------------ #


class _Registros:
    def __init__(self, fila: Mapping[str, Any] | None) -> None:
        self._fila = fila

    async def leer(self, registro_id: UUID) -> Mapping[str, Any] | None:
        return self._fila


class _Fichas:
    def __init__(self, ficha: Mapping[str, Any]) -> None:
        self._ficha = ficha
        self.pedidos: list[str] = []

    async def leer(self, ocid: str) -> Mapping[str, Any]:
        self.pedidos.append(ocid)
        return self._ficha


def _registro(fuente: str = "OCDS", **datos: Any) -> dict[str, Any]:
    return {
        "id": uuid4(),
        "fuente": fuente,
        "clave_natural": OCID,
        "datos": {"ocid": OCID, **datos},
    }


def _ejecutar(
    registro: Mapping[str, Any] | None,
    ficha: Mapping[str, Any],
    vistas: tuple[Vista, ...] = (Vista.OFERTAS,),
) -> dict[str, Any]:
    return asyncio.run(
        anexos_del_proceso(vistas, uuid4(), registros=_Registros(registro), fichas=_Fichas(ficha))
    )


def test_solo_queda_la_ultima_acta_y_el_orden_es_tdr_pliego_acta() -> None:
    ficha = ficha_del_record(_con_documentos(RECORD_VALOR))
    assert ficha is not None
    respuesta = _ejecutar(_registro(), ficha)
    tipos = [a["tipo"] for a in respuesta["anexos"]]
    assert tipos[:3] == [TDR, PLIEGO, ACTA]
    actas = [a for a in respuesta["anexos"] if a["tipo"] == ACTA]
    assert len(actas) == 1
    assert actas[0]["enlace"].endswith("acta-2.pdf")  # la de fecha más reciente
    assert respuesta["presupuesto"]["monto"] == 15600.0
    assert respuesta["moneda"] == "USD"
    assert respuesta["aviso"] is None


def test_sin_documentos_se_explica_y_se_manda_al_portal() -> None:
    ficha = ficha_del_record(RECORD_SUBASTA)
    assert ficha is not None
    respuesta = _ejecutar(_registro(), ficha)
    assert respuesta["anexos"] == []
    assert respuesta["aviso"] == AVISO_SIN_DOCUMENTOS
    assert respuesta["buscador_portal"].startswith("https://www.compraspublicas.gob.ec/")
    assert respuesta["codigo"] == "SIE-CCFFAA-2026-004-2539"
    assert len(respuesta["aclaraciones"]) == 2


def test_sin_monto_en_la_ficha_se_usa_el_dato_ingestado() -> None:
    ficha = {"documentos": [], "presupuesto": None, "aclaraciones": []}
    respuesta = _ejecutar(_registro(presupuesto="12500.000000"), ficha)
    assert respuesta["presupuesto"]["monto"] == 12500.0
    assert respuesta["presupuesto"]["fuente"] == "registro.presupuesto"


def test_una_infima_responde_que_sus_anexos_van_por_la_ficha() -> None:
    with pytest.raises(NoEsProcesoOcds, match="ínfimas"):
        _ejecutar(_registro(fuente="NCO"), {})


def test_sin_la_vista_de_ofertas_no_hay_anexos() -> None:
    with pytest.raises(SinPermiso):
        _ejecutar(_registro(), {}, vistas=(Vista.NECESIDADES,))


def test_un_registro_que_no_existe_es_no_encontrado() -> None:
    with pytest.raises(NoEncontrado):
        _ejecutar(None, {})
