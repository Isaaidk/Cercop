"""Importación de contratos por RUC desde el registro de Open Contracting."""

from __future__ import annotations

import io
import tarfile
from datetime import UTC, datetime, timedelta
from typing import Any

from contratacion.dominio.historial import resumen_importado
from contratacion.infraestructura.adaptadores.salida.fuentes.contratos_ocp import (
    Acumulado,
    leer_anio,
)
from contratacion.infraestructura.adaptadores.salida.historial import HistorialImportado
from contratacion.tareas.importar_contratos import toca

RUC_A = "1790012345001"
RUC_B = "0990012345001"

ARCHIVOS = {
    # El orden del tar real: awards, awards_items, awards_suppliers, main.
    "awards.csv": (
        "id,date,description,value_amount,value_currency,main_ocid,main_id,status\n"
        "a1,2026-03-02T10:00:00-05:00,x,1000,USD,o1,m1,\n"
        "a2,2025-05-01T10:00:00-05:00,x,500,USD,o2,m2,\n"
        "a3,,x,300,USD,o3,m3,\n"
        "a4,2026-01-01T10:00:00-05:00,x,999,USD,o4,m4,cancelled\n"
    ),
    "awards_items.csv": (
        "id,description,classification_id,classification_scheme,classification_description,"
        "main_ocid,main_id,awards_id\n"
        'i1,"RESMAS DE PAPEL, A4",321290418,CPC,PAPEL BOND,o1,m1,a1\n'
        "i2,SERVICIO,871410011,CPC,MANTENIMIENTO DE VEHICULOS,o2,m2,a2\n"
        "i3,PAPEL,321290418,CPC,PAPEL BOND,o3,m3,a3\n"
    ),
    "awards_suppliers.csv": (
        "id,name,main_ocid,main_id,awards_id\n"
        f"EC-RUC-{RUC_A}-1,A SA,o1,m1,a1\n"
        f"EC-RUC-{RUC_A}-1,A SA,o2,m2,a2\n"
        f"EC-RUC-{RUC_A}-1,A SA,o3,m3,a3\n"
        f"EC-RUC-{RUC_B}-2,B SA,o3,m3,a3\n"
        f"EC-RUC-{RUC_B}-2,B SA,o4,m4,a4\n"
    ),
    "main.csv": (
        "id,ocid,buyer_name,tender_title,tender_description,tender_mainProcurementCategory\n"
        "m1,o1,MUNICIPIO DE QUITO,Papel,Orden de compra de papel,goods\n"
        "m2,o2,MUNICIPIO DE AMBATO,Mantenimiento,Mantenimiento de la flota,services\n"
        "m3,o3,MUNICIPIO DE QUITO,Papel 2,Compra de papel,goods\n"
        "m4,o4,OTRA,Cancelado,Cancelado,goods\n"
    ),
}


def _tar() -> io.BytesIO:
    salida = io.BytesIO()
    with tarfile.open(fileobj=salida, mode="w:gz") as tar:
        for nombre, contenido in ARCHIVOS.items():
            datos = contenido.encode("utf-8")
            info = tarfile.TarInfo(f"2026/{nombre}")
            info.size = len(datos)
            tar.addfile(info, io.BytesIO(datos))
    salida.seek(0)
    return salida


def test_resume_por_ruc_y_descarta_las_adjudicaciones_canceladas() -> None:
    acumulado = Acumulado()
    assert leer_anio(_tar(), acumulado, 2026) == 4  # 3 de A + 1 de B (el consorcio)

    a = acumulado.proveedores[RUC_A].resumen()
    assert a["contratos"] == 3
    assert a["monto"] == 1650  # 1000 + 500 + la mitad de 300 (consorcio con B)
    assert (a["desde"], a["hasta"]) == (2025, 2026)  # el que no tiene fecha cuenta en 2026
    assert a["cpc"][0] == ["321290418", 2]
    quito = acumulado.entidades["MUNICIPIO DE QUITO"]
    assert a["entidades"][0] == [quito, 2]
    # La más reciente primero; «Orden de compra…» no dice nada y se usa el producto.
    assert a["experiencia"][0][:2] == [quito, 2026]
    assert a["experiencia"][0][5] == "RESMAS DE PAPEL, A4"

    b = acumulado.proveedores[RUC_B].resumen()
    assert b["contratos"] == 1  # la cancelada no cuenta
    assert acumulado.cpc["871410011"] == "MANTENIMIENTO DE VEHICULOS"


def test_el_resumen_importado_tiene_la_forma_del_perfil() -> None:
    datos = {
        "contratos": 2,
        "monto": 1500,
        "desde": 2025,
        "hasta": 2026,
        "cpc": [["321290418", 2]],
        "entidades": [[1, 2]],
        "experiencia": [[1, 2026, 1000, "321290418", "bienes", "Papel"]],
    }
    r = resumen_importado(RUC_A, datos, {"321290418": "PAPEL BOND"}, {1: "MUNICIPIO"})
    assert r["verificados"] == 2 and r["monto_revisado"] == 1500
    assert r["cpc"] == [{"codigo": "321290418", "descripcion": "PAPEL BOND", "veces": 2}]
    assert r["experiencia"][0]["entidad"] == "MUNICIPIO"
    assert r["experiencia"][0]["tipo_contratacion"] == "bienes"
    assert r["entidades"] == [{"nombre": "MUNICIPIO", "veces": 2}]
    vacio = resumen_importado(RUC_B, None, {}, {})
    assert vacio["verificados"] == 0 and vacio["cpc"] == [] and vacio["experiencia"] == []


class RepoFalso:
    def __init__(self, filas: dict[str, Any], importado: bool) -> None:
        self.filas = filas
        self.importado = importado

    async def resumen(self, ruc: str) -> Any:
        return self.filas.get(ruc)

    async def ultima_importacion(self) -> datetime | None:
        return datetime.now(UTC) if self.importado else None


class RespaldoFalso:
    def __init__(self) -> None:
        self.llamadas = 0

    async def consultar(self, ruc: str, razon_social: str) -> dict[str, Any]:
        self.llamadas += 1
        return {"ruc": ruc, "verificados": 0, "de": "api"}


async def test_sin_importacion_usa_la_api_y_con_importacion_no_sale_a_internet() -> None:
    respaldo = RespaldoFalso()
    sin = HistorialImportado(RepoFalso({}, importado=False), respaldo)
    assert (await sin.consultar("1700000000001", "EMPRESA"))["de"] == "api"

    con = HistorialImportado(RepoFalso({}, importado=True), respaldo)
    vacio = await con.consultar("1700000000002", "EMPRESA")
    assert vacio["verificados"] == 0 and respaldo.llamadas == 1

    fila = ({"contratos": 1, "cpc": [["1", 1]]}, {"1": "UNO"}, {})
    historial = HistorialImportado(RepoFalso({"1700000000003": fila}, True), respaldo)
    hallado = await historial.consultar("1700000000003", "EMPRESA")
    assert hallado["cpc"][0]["descripcion"] == "UNO"


def test_la_importacion_toca_cada_30_dias() -> None:
    ahora = datetime(2026, 11, 17, tzinfo=UTC)
    assert toca(None, ahora)
    assert not toca(ahora - timedelta(days=29), ahora)
    assert toca(ahora - timedelta(days=30), ahora)
