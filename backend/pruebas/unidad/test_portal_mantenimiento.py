"""El portal en «Ventana de Mantenimiento» no puede pasar por una respuesta buena.

Caso real (2026-11-16): el portal redirigía todo a `app/webroot/compras/index.php`, que responde 200
con un aviso. El worker guardaba cada ficha como «leída sin ítems» (y no la volvía a pedir), seguía
pidiendo fichas a una por segundo desde la IP de Ecuador y guardaba el aviso como si fuera el TDR.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from contratacion.infraestructura.adaptadores.salida.archivos.tdr import (
    PortalEnMantenimiento,
    descargar_a,
)
from contratacion.infraestructura.adaptadores.salida.fuentes.limitador import LimitadorTasa
from contratacion.infraestructura.adaptadores.salida.fuentes.portal import (
    EstadoPortal,
    es_aviso_mantenimiento,
    es_ruta_mantenimiento,
)
from contratacion.infraestructura.adaptadores.salida.fuentes.salidas import PoolSalidas

BASE = "https://www.compraspublicas.gob.ec/ProcesoContratacion"
AVISO = BASE + "/app/webroot/compras/index.php"
FICHA = BASE + "/compras/NCO/NCORegistroDetalle.cpe"
HTML_AVISO = (
    "<html><head><title>Ventana de Mantenimiento</title></head><body><h1>VENTANA DE "
    "MANTENIMIENTO</h1><p>Estimados Entidades Contratantes...</p></body></html>"
)


def _portal_en_mantenimiento(peticion: httpx.Request) -> httpx.Response:
    if peticion.url.path.endswith("index.php"):
        return httpx.Response(200, text=HTML_AVISO, headers={"content-type": "text/html"})
    return httpx.Response(302, headers={"location": AVISO})


class LimitadorDePrueba(LimitadorTasa):
    def __init__(
        self, manejador: Callable[[httpx.Request], httpx.Response], portal: EstadoPortal
    ) -> None:
        super().__init__(
            max_concurrencia=1, intervalo_minimo=0.0, espera_base=0.001, reintentos=3, portal=portal
        )
        self._manejador = manejador
        self.llamadas = 0

    def _obtener_cliente(self, tiempo_limite: float) -> httpx.AsyncClient:
        if self._cliente is None or self._cliente.is_closed:
            self._cliente = httpx.AsyncClient(
                transport=httpx.MockTransport(self._contar),
                timeout=tiempo_limite,
                follow_redirects=True,
            )
        return self._cliente

    def _contar(self, peticion: httpx.Request) -> httpx.Response:
        self.llamadas += 1
        return self._manejador(peticion)


def test_reconoce_la_ruta_y_el_texto_del_aviso() -> None:
    assert es_ruta_mantenimiento(AVISO)
    assert not es_ruta_mantenimiento(FICHA)
    assert es_aviso_mantenimiento(HTML_AVISO)
    assert es_aviso_mantenimiento(HTML_AVISO.encode())
    assert not es_aviso_mantenimiento("<table><tr><th>CPC</th></tr></table>")


async def test_la_ficha_en_mantenimiento_no_es_una_ficha_vacia_y_pausa_el_portal() -> None:
    portal = EstadoPortal()
    limitador = LimitadorDePrueba(_portal_en_mantenimiento, portal)

    texto = await limitador.solicitar_texto(FICHA, {"id": "x"}, etiqueta="NCO detalle")

    # `None` = «no se pudo»: la ficha queda pendiente. Antes era el HTML del aviso → «sin ítems».
    assert texto is None
    assert portal.en_pausa()
    # Una sola petición (302 + aviso): ni reintentos contra el portal en mantenimiento.
    assert limitador.llamadas == 2


async def test_en_pausa_no_sale_ninguna_peticion() -> None:
    portal = EstadoPortal()
    portal.pausar("prueba")
    limitador = LimitadorDePrueba(_portal_en_mantenimiento, portal)

    for _ in range(50):
        assert await limitador.solicitar_texto(FICHA, etiqueta="NCO detalle") is None

    assert limitador.llamadas == 0


async def test_el_tope_por_hora_corta_aunque_el_portal_responda_bien() -> None:
    portal = EstadoPortal(max_por_hora=5)
    limitador = LimitadorDePrueba(lambda _p: httpx.Response(200, text="<table></table>"), portal)

    respuestas = [await limitador.solicitar_texto(FICHA) for _ in range(8)]

    assert sum(r is not None for r in respuestas) == 5
    assert limitador.llamadas == 5


async def test_la_pausa_no_enfria_ni_culpa_a_la_salida() -> None:
    portal = EstadoPortal()
    pool = PoolSalidas.desde_urls([], portal=portal)
    pool.salidas[0].limitador = LimitadorDePrueba(_portal_en_mantenimiento, portal)

    for _ in range(5):
        assert await pool.solicitar_texto(FICHA) is None

    assert pool.salidas[0].sana()
    assert pool.salidas[0].fallos == 0


async def test_un_tdr_en_mantenimiento_no_se_guarda_como_archivo(tmp_path: Path) -> None:
    cliente = httpx.AsyncClient(transport=httpx.MockTransport(_portal_en_mantenimiento))

    with pytest.raises(PortalEnMantenimiento):
        await descargar_a(cliente, BASE + "/compras/archivo.pdf", tmp_path)

    assert not any(tmp_path.iterdir())
    await cliente.aclose()


async def test_un_aviso_servido_sin_redireccion_tampoco_se_guarda(tmp_path: Path) -> None:
    def _aviso_directo(_p: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=HTML_AVISO, headers={"content-type": "text/html"})

    cliente = httpx.AsyncClient(transport=httpx.MockTransport(_aviso_directo))

    with pytest.raises(PortalEnMantenimiento):
        await descargar_a(cliente, BASE + "/compras/archivo.pdf", tmp_path)

    assert not any(tmp_path.iterdir())
    await cliente.aclose()
