"""Reparto y enfriamiento de las salidas."""

import time

from contratacion.infraestructura.adaptadores.salida.fuentes.limitador import LimitadorTasa
from contratacion.infraestructura.adaptadores.salida.fuentes.salidas import (
    ENFRIAMIENTO_SEG,
    PoolSalidas,
    Salida,
)


def _salida(url: str) -> Salida:
    return Salida(url, LimitadorTasa(proxy_url=url))


def test_elige_la_salida_con_menos_carga() -> None:
    pool = PoolSalidas(salidas=[_salida("http://a"), _salida("http://b")], directo_si_vacio=False)
    pool.salidas[0].en_vuelo = 2
    assert pool.elegir() is pool.salidas[1]


def test_tres_fallos_enfrian_la_salida_y_el_reintento_usa_la_otra() -> None:
    pool = PoolSalidas(salidas=[_salida("http://a"), _salida("http://b")], directo_si_vacio=False)
    for _ in range(3):
        pool.salidas[0].anotar(False)
    assert not pool.salidas[0].sana()
    assert pool.elegir() is pool.salidas[1]
    assert pool.salidas[0].enfriamiento_hasta > time.monotonic()
    assert pool.salidas[0].enfriamiento_hasta <= time.monotonic() + ENFRIAMIENTO_SEG + 1


def test_sin_ninguna_sana_no_hay_salida_directa() -> None:
    pool = PoolSalidas(salidas=[_salida("http://a")], directo_si_vacio=False)
    pool.salidas[0].enfriamiento_hasta = time.monotonic() + 30
    assert pool.elegir() is None
