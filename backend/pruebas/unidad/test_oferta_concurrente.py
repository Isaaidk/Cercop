"""Lo que sostiene la oferta con cientos de personas: límites por usuario, hilos, caché y cola."""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi import HTTPException

from contratacion.aplicacion.casos_uso import atender_tdr
from contratacion.aplicacion.hilos import CacheLru, en_hilo
from contratacion.dominio.documentos import documentos_legibles, parece_enlace, resumir_ficha
from contratacion.infraestructura.adaptadores.entrada.http.limites import LimitePorUsuario
from contratacion.infraestructura.adaptadores.entrada.http.proteccion import _LIMITES


class _Actor:
    def __init__(self) -> None:
        self.usuario_id = uuid4()


def test_el_enlace_del_portal_no_se_enseña_como_nombre() -> None:
    enlace = "../GE/ExeGENBajarArchivoGeneral.cpe?Archivo=abc,&idPath=def,"
    assert parece_enlace(enlace)
    assert not parece_enlace("Pliego.pdf")
    lista = documentos_legibles(
        [{"nombre": enlace, "enlace": enlace}, {"nombre": "Pliego.pdf", "enlace": "x"}]
    )
    assert [fila["nombre"] for fila in lista] == ["Documento 1", "Pliego.pdf"]
    assert lista[1]["tipo"] == "PDF"
    assert lista[0]["tipo"] == ""


def test_el_resumen_de_ficha_ya_no_une_direcciones() -> None:
    enlace = "../GE/ExeGENBajarArchivoGeneral.cpe?Archivo=abc"
    resumen = resumir_ficha({"documentos": [{"nombre": enlace, "enlace": enlace}] * 3})
    assert resumen["documentos"] == "Documento 1, Documento 2, Documento 3"
    assert len(resumen["documentos_lista"]) == 3
    assert "ExeGEN" not in resumen["documentos"]


def test_las_rutas_de_la_oferta_no_comparten_tope_por_ip() -> None:
    # Una oficina entera sale por una IP: su tope no puede ser el de una sola persona.
    assert not [clave for clave in _LIMITES if clave[1].startswith("/v1/documentos")]


def test_el_tope_es_por_persona() -> None:
    limite = LimitePorUsuario("prueba", 3, 60)
    ana, luis = _Actor(), _Actor()

    async def pedir(actor: _Actor) -> None:
        await limite(actor)  # type: ignore[arg-type]

    async def escenario() -> None:
        for _ in range(3):
            await pedir(ana)
        with pytest.raises(HTTPException) as caso:
            await pedir(ana)
        assert caso.value.status_code == 429
        assert int((caso.value.headers or {})["Retry-After"]) >= 1
        # Luis, desde «la misma red», no paga lo que gastó Ana.
        for _ in range(3):
            await pedir(luis)

    asyncio.run(escenario())


def test_cache_lru_expulsa_lo_menos_usado() -> None:
    cache = CacheLru(2)
    cache.guardar("a", 1)
    cache.guardar("b", 2)
    assert cache.obtener("a") == 1
    cache.guardar("c", 3)
    assert cache.obtener("b") is None
    assert cache.obtener("a") == 1 and cache.obtener("c") == 3


def test_el_trabajo_pesado_no_bloquea_el_bucle() -> None:
    """Mientras un hilo trabaja, el bucle sigue atendiendo: el latido no se retrasa."""
    latidos: list[float] = []

    def pesado() -> str:
        time.sleep(0.4)
        return threading.current_thread().name

    async def latido() -> None:
        for _ in range(6):
            t = time.perf_counter()
            await asyncio.sleep(0.05)
            latidos.append(time.perf_counter() - t)

    async def escenario() -> str:
        trabajo = asyncio.create_task(en_hilo(pesado))
        await latido()
        return await trabajo

    hilo = asyncio.run(escenario())
    assert hilo != threading.main_thread().name
    assert max(latidos) < 0.2


class _Tdr:
    def __init__(self, pedidos: list[dict[str, Any]]) -> None:
        self.pedidos = pedidos
        self.listos: list[Any] = []
        self.errores: list[Any] = []

    async def tomar_pendientes(self, limite: int) -> list[dict[str, Any]]:
        return self.pedidos[:limite]

    async def marcar_error(self, documento_id: Any, mensaje: str) -> None:
        self.errores.append((documento_id, mensaje))

    async def marcar_listo(self, documento_id: Any, **datos: Any) -> None:
        self.listos.append(documento_id)


def test_la_cola_se_atiende_en_lote_y_sin_enlace_queda_en_error(tmp_path: Path) -> None:
    pedidos = [
        {"id": uuid4(), "registro_id": uuid4(), "nombre": f"{n}", "url_origen": ""}
        for n in range(5)
    ]
    repositorio = _Tdr(pedidos)

    hechos = asyncio.run(atender_tdr.atender_lote(repositorio, tmp_path, tamano=4))  # type: ignore[arg-type]
    assert hechos == 4
    assert len(repositorio.errores) == 4
    assert "enlace" in repositorio.errores[0][1]


def test_sin_pedidos_no_hay_trabajo(tmp_path: Path) -> None:
    assert asyncio.run(atender_tdr.atender_lote(_Tdr([]), tmp_path)) == 0  # type: ignore[arg-type]


def test_el_borrador_se_presenta_sin_volcados_de_diccionario() -> None:
    from contratacion.dominio.relleno import presentar_anexos

    secciones = presentar_anexos(
        {
            "oferente": {
                "razon_social": "Andinos S.A.",
                "ruc": "1792146739001",
                "representante": {
                    "tipo": "representante_legal",
                    "nombre": "Isaac",
                    "cargo": "Gerente",
                },
                "obligado_contabilidad": True,
            },
            "experiencia": [
                {"entidad": "GAD Quito", "objeto": "Suministros", "monto": 18400, "anio": 2025}
            ],
            "equipo": [{"nombre": "Furgoneta", "cantidad": 2}],
            "personal": [],
        }
    )
    escrito = " ".join(
        str(valor)
        for seccion in secciones
        for fila in seccion["filas"]
        for valor in (fila.values() if isinstance(fila, dict) else [fila])
    )
    assert "representante_legal" not in escrito and "{" not in escrito
    oferente = secciones[0]["filas"]
    assert {"etiqueta": "Representante legal", "valor": "Isaac · Gerente"} in oferente
    assert {"etiqueta": "Obligado a llevar contabilidad", "valor": "Sí"} in oferente
    assert secciones[1]["filas"] == ["GAD Quito · Suministros · USD 18,400.00 · 2025"]
    por_titulo = {seccion["titulo"]: seccion["filas"] for seccion in secciones}
    assert por_titulo["Equipo y recursos"] == ["Furgoneta x2"]
    assert por_titulo["Personal técnico"] == []
