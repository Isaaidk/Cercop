"""Leer un proceso desde su código: se piden y se leen TDR, pliego y **solo la última acta**.

Los repositorios son dobles en memoria; los archivos son `.txt` en una carpeta temporal, que el caso
de uso lee igual que un PDF ya bajado.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.casos_uso import preparar_documentos as caso
from contratacion.dominio.acceso import Vista
from contratacion.dominio.errores import DatoInvalido

ACTOR = Actor(usuario_id=uuid4(), negocio_id=uuid4(), rol="super_admin")
VISTAS = frozenset({Vista.NECESIDADES})
REGISTRO = uuid4()

TDR = """OBJETO DE LA CONTRATACIÓN: Adquisición de sillas de oficina
PLAZO DE ENTREGA: 30 días calendario
FORMA DE PAGO: Contra entrega
PRESUPUESTO REFERENCIAL: USD 1.500,00 no incluye IVA
"""
ACTA_VIEJA = """ACTA DE PREGUNTAS
PLAZO DE ENTREGA: 20 días
PRESUPUESTO REFERENCIAL: USD 1.400,00
"""
ACTA_NUEVA = """ACTA DE ACLARACIONES
PLAZO DE ENTREGA: 15 días calendario
PRESUPUESTO REFERENCIAL: USD 1.350,00 sin IVA
"""


class _Documentos:
    def __init__(self, ficha: dict[str, Any]) -> None:
        self.ficha = ficha
        self.guardadas: list[dict[str, Any]] = []
        self.proformas: list[dict[str, Any]] = []
        self.datos_ficha: dict[str, Any] | None = None
        self.entidad_ficha: dict[str, Any] = {}
        self.guardada: dict[str, Any] | None = None

    async def ficha_publicada(self, *, fuentes: tuple[str, ...], codigo: str) -> dict[str, Any]:
        return dict(self.ficha)

    async def pedir_items(self, registro_id: UUID) -> None:
        return None

    async def guardar_lectura_con_requisitos(self, **campos: Any) -> dict[str, Any]:
        self.guardadas.append(campos)
        return {"id": uuid4()}

    async def datos_de_presupuesto(self, registro_id: UUID) -> dict[str, Any] | None:
        return self.datos_ficha

    async def guardar_proforma(self, *, negocio_id: UUID, campos: dict[str, Any]) -> dict[str, Any]:
        self.proformas.append(campos)
        return {"id": uuid4()}

    async def datos_de_entidad(self, *, negocio_id: UUID, registro_id: UUID) -> dict[str, Any]:
        return dict(self.entidad_ficha)

    async def proforma(self, *, negocio_id: UUID, proforma_id: UUID) -> dict[str, Any] | None:
        return dict(self.guardada) if self.guardada else None

    async def titulos_de_proformas(self, negocio_id: UUID) -> list[str]:
        return [str(campos.get("titulo") or "") for campos in self.proformas]


class _Tdr:
    """La cola de TDR: `archivos` son los que el worker ya dejó listos en disco."""

    def __init__(self, archivos: dict[str, Path], pendientes: set[str] | None = None) -> None:
        self.archivos = archivos
        self.pendientes = pendientes or set()
        self.filas: dict[str, dict[str, Any]] = {}
        self.pedidos: list[str] = []

    async def listar(self, registro_id: UUID) -> list[dict[str, Any]]:
        return list(self.filas.values())

    async def pedir(self, registro_id: UUID, documento: dict[str, Any]) -> str:
        nombre = str(documento.get("nombre") or "tdr")
        self.pedidos.append(nombre)
        listo = nombre in self.archivos and nombre not in self.pendientes
        self.filas[nombre] = {
            "id": uuid4(),
            "nombre": nombre,
            "estado": "listo" if listo else "pendiente",
            "ruta": str(self.archivos.get(nombre, "")),
            "sha256": None,
            "pedido_en": datetime.now(UTC),
        }
        return str(self.filas[nombre]["estado"])

    async def reabrir(self, documento_id: UUID) -> None:
        return None

    async def auditar(self, *args: Any) -> None:
        return None

    async def contar_pendientes(self) -> int:
        return sum(1 for fila in self.filas.values() if fila["estado"] == "pendiente")


def _escenario(tmp_path: Path, documentos: list[dict[str, Any]], textos: dict[str, str]) -> Path:
    for nombre, texto in textos.items():
        (tmp_path / nombre).write_text(texto, encoding="utf-8")
    return tmp_path


def _ficha(documentos: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {
        "id": REGISTRO,
        "codigo": "NIC-1790012345001-2026-00001",
        "objeto": "Sillas",
        "entidad": "GAD",
        "documentos": documentos,
        "items": [],
        "items_recogidos_en": datetime.now(UTC),
        **extra,
    }


DOCUMENTOS = [
    {"nombre": "acta_01-03-2026.txt", "enlace": "BajarArchivo?a1"},
    {"nombre": "TDR.txt", "enlace": "BajarArchivo?t"},
    {"nombre": "acta_10-03-2026.txt", "enlace": "BajarArchivo?a2"},
]


def _correr(documentos: _Documentos, tdr: _Tdr) -> dict[str, Any]:
    return asyncio.run(
        caso.preparar_desde_codigo(
            ACTOR,
            VISTAS,
            documentos=documentos,
            tdr=tdr,
            codigo="NIC-1",  # type: ignore[arg-type]
        )
    )


def test_pide_y_lee_solo_el_tdr_y_la_ultima_acta(tmp_path: Path) -> None:
    carpeta = _escenario(
        tmp_path,
        DOCUMENTOS,
        {"TDR.txt": TDR, "acta_01-03-2026.txt": ACTA_VIEJA, "acta_10-03-2026.txt": ACTA_NUEVA},
    )
    archivos = {
        nombre: carpeta / nombre for nombre in ("TDR.txt", *(d["nombre"] for d in DOCUMENTOS))
    }
    tdr = _Tdr(archivos)
    documentos = _Documentos(_ficha(DOCUMENTOS))

    resultado = _correr(documentos, tdr)

    assert resultado["estado"] == "listo"
    # El acta vieja ni se pide: es una petición menos al portal.
    assert sorted(tdr.pedidos) == ["TDR.txt", "acta_10-03-2026.txt"]
    assert [(a["tipo"], a["nombre"]) for a in resultado["anexos"]] == [
        ("tdr", "TDR.txt"),
        ("acta", "acta_10-03-2026.txt"),
    ]
    assert all(a["leido"] and a["documento_id"] for a in resultado["anexos"])
    # El acta corrige el plazo y el presupuesto, y se dice de dónde sale.
    secciones = resultado["secciones"]
    assert secciones["plazo_entrega"].startswith("Según acta del 10/03/2026")
    assert secciones["forma_pago"] == "Contra entrega"
    assert resultado["cambios_acta"]
    assert resultado["presupuesto"]["valor"] == 1350.0
    assert resultado["presupuesto"]["incluye_iva"] is False
    assert resultado["presupuesto_fuente"] == "acta más reciente"
    assert documentos.guardadas[0]["nombre"] == "TDR.txt"


def test_sin_acta_el_presupuesto_sale_de_la_ficha_antes_que_del_tdr(tmp_path: Path) -> None:
    carpeta = _escenario(tmp_path, [], {"TDR.txt": TDR})
    tdr = _Tdr({"TDR.txt": carpeta / "TDR.txt"})
    documentos = _Documentos(
        _ficha([{"nombre": "TDR.txt", "enlace": "BajarArchivo?t"}], presupuesto="1450.75")
    )

    resultado = _correr(documentos, tdr)

    assert resultado["presupuesto"]["valor"] == 1450.75
    assert resultado["presupuesto_fuente"] == "ficha del proceso"

    documentos.ficha = _ficha(
        [{"nombre": "TDR.txt", "enlace": "BajarArchivo?t"}], cantidad="0", valor_unitario="0"
    )
    resultado = _correr(documentos, _Tdr({"TDR.txt": carpeta / "TDR.txt"}))
    assert resultado["presupuesto"]["valor"] == 1500.0
    assert resultado["presupuesto_fuente"] == "TDR"


def test_espera_al_acta_reciente_que_sigue_en_la_cola(tmp_path: Path) -> None:
    carpeta = _escenario(tmp_path, DOCUMENTOS, {"TDR.txt": TDR})
    tdr = _Tdr({"TDR.txt": carpeta / "TDR.txt"}, pendientes={"acta_10-03-2026.txt"})
    documentos = _Documentos(_ficha(DOCUMENTOS))

    assert _correr(documentos, tdr)["estado"] == "preparando"
    estado = asyncio.run(
        caso.estado_desde_codigo(
            ACTOR,
            VISTAS,
            documentos=documentos,
            tdr=tdr,
            codigo="NIC-1",  # type: ignore[arg-type]
        )
    )
    assert estado["estado"] == "preparando"

    # Pasado el tope de espera se lee lo que hay: el TDR sin el acta.
    tdr.filas["acta_10-03-2026.txt"]["pedido_en"] = datetime.now(UTC) - timedelta(minutes=5)
    resultado = _correr(documentos, tdr)
    assert resultado["estado"] == "listo"
    assert resultado["presupuesto"]["valor"] == 1500.0


def test_la_proforma_que_supera_el_presupuesto_no_se_guarda() -> None:
    documentos = _Documentos(_ficha([]))
    campos = {
        "impuesto_porcentaje": 15,
        "lineas": [{"descripcion": "Silla", "cantidad": 10, "precio_unitario": 160}],
        "registro_id": str(REGISTRO),
        "extras": {"presupuesto": {"valor": 1500, "fuente": "tdr", "incluye_iva": False}},
    }
    with pytest.raises(DatoInvalido, match="supera el presupuesto"):
        asyncio.run(
            caso.crear_proforma(ACTOR, documentos=documentos, campos=campos, tipo="proforma")  # type: ignore[arg-type]
        )
    assert documentos.proformas == []

    campos["lineas"] = [{"descripcion": "Silla", "cantidad": 10, "precio_unitario": 140}]
    creada = asyncio.run(
        caso.crear_proforma(ACTOR, documentos=documentos, campos=campos, tipo="proforma")  # type: ignore[arg-type]
    )
    assert creada["uso_presupuesto"]["porcentaje"] == pytest.approx(93.3)
    assert documentos.proformas[0]["extras"]["presupuesto"]["valor"] == 1500.0


def test_la_ficha_guardada_manda_sobre_lo_que_envia_el_navegador() -> None:
    documentos = _Documentos(_ficha([]))
    documentos.datos_ficha = {"presupuesto": "1000"}
    campos = {
        "impuesto_porcentaje": 0,
        "lineas": [{"descripcion": "Silla", "cantidad": 10, "precio_unitario": 120}],
        "registro_id": str(REGISTRO),
        # El navegador dice que viene del TDR, pero la ficha publicada es más fiable.
        "extras": {"presupuesto": {"valor": 5000, "fuente": "tdr"}},
    }
    with pytest.raises(DatoInvalido, match="ficha del proceso"):
        asyncio.run(
            caso.crear_proforma(ACTOR, documentos=documentos, campos=campos, tipo="proforma")  # type: ignore[arg-type]
        )
