"""Pruebas del bloqueo de exclusión mutua de la ingesta.

Se comprueban dos cosas que no son la misma: que el bloqueo impide el trabajo simultáneo —para eso
existe— y que **soltarlo no puede tumbar el ciclo**.

Lo segundo salió de un ciclo real contra la fuente oficial. El bloqueo es de sesión, así que vive en
una conexión que queda ociosa durante minutos mientras el ciclo habla con el SERCOP; si el servidor
cierra esa conexión por inactividad, soltar el bloqueo lanza, y sin protección la excepción se lleva
por delante el resultado de un ciclo que había ido bien.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from contratacion.infraestructura.adaptadores.salida.bd.bloqueo import (
    bloqueo_de_ingesta,
    clave_de_bloqueo,
)

LOGGER = "contratacion.infraestructura.adaptadores.salida.bd.bloqueo"


class ResultadoFalso:
    """Resultado de una consulta: solo hace falta el escalar."""

    def __init__(self, valor: bool) -> None:
        self._valor = valor

    def scalar_one(self) -> bool:
        return self._valor


class ConexionFalsa:
    """Conexión que responde a las dos consultas del bloqueo, y puede fallar al soltarlo."""

    def __init__(self, *, obtenido: bool = True, soltado: bool = True, cae_al_soltar: bool = False):
        self.obtenido = obtenido
        self.soltado = soltado
        self.cae_al_soltar = cae_al_soltar
        self.consultas: list[str] = []

    async def execute(self, sentencia: Any, parametros: dict[str, Any]) -> ResultadoFalso:
        texto = str(sentencia)
        self.consultas.append(texto)
        if "try_advisory_lock" in texto:
            return ResultadoFalso(self.obtenido)
        if self.cae_al_soltar:
            raise RuntimeError("connection was closed in the middle of operation")
        return ResultadoFalso(self.soltado)


class MotorFalso:
    """Motor que entrega siempre la misma conexión, sin abrir ninguna de verdad."""

    def __init__(self, conexion: ConexionFalsa) -> None:
        self._conexion = conexion

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[ConexionFalsa]:
        yield self._conexion


def _motor(conexion: ConexionFalsa) -> AsyncEngine:
    """El adaptador espera un motor; el doble se disfraza para no arrastrar una base de datos."""
    return cast(AsyncEngine, MotorFalso(conexion))


# --------------------------------------------------------------------------- #
# La clave
# --------------------------------------------------------------------------- #


def test_cada_fuente_tiene_su_clave() -> None:
    assert clave_de_bloqueo("NCO") != clave_de_bloqueo("OCDS")


def test_la_clave_de_una_fuente_no_cambia() -> None:
    """Tiene que ser estable entre procesos: si cambiara, dos réplicas no se verían."""
    assert clave_de_bloqueo("NCO") == clave_de_bloqueo("NCO")


# --------------------------------------------------------------------------- #
# El bloqueo hace su trabajo
# --------------------------------------------------------------------------- #


async def test_sin_el_bloqueo_no_se_cede_ninguna_conexion() -> None:
    """Otra réplica ya está ingestando: quien lo intenta no recibe nada y se retira."""
    conexion = ConexionFalsa(obtenido=False)

    async with bloqueo_de_ingesta("NCO", _motor(conexion)) as cedida:
        assert cedida is None


async def test_con_el_bloqueo_se_cede_la_conexion() -> None:
    conexion = ConexionFalsa()

    async with bloqueo_de_ingesta("NCO", _motor(conexion)) as cedida:
        # El `cast` es para poder comparar la identidad: `cedida` está anotada como la conexión de
        # SQLAlchemy, y el doble no lo es. Lo que importa es que sea **la misma** que entregó el
        # motor, y eso se comprueba con `is`.
        assert cast(object, cedida) is conexion

    assert any("pg_advisory_unlock" in consulta for consulta in conexion.consultas)


# --------------------------------------------------------------------------- #
# Soltarlo no puede tumbar el ciclo
# --------------------------------------------------------------------------- #


async def test_si_la_conexion_murio_al_soltar_el_ciclo_no_se_cae() -> None:
    """El caso real: la conexión quedó ociosa minutos y el servidor la cerró."""
    conexion = ConexionFalsa(cae_al_soltar=True)

    async with bloqueo_de_ingesta("NCO", _motor(conexion)) as cedida:
        assert cast(object, cedida) is conexion


async def test_un_fallo_al_soltar_deja_aviso(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger=LOGGER)
    conexion = ConexionFalsa(cae_al_soltar=True)

    async with bloqueo_de_ingesta("NCO", _motor(conexion)):
        pass

    assert "No se pudo soltar el bloqueo" in caplog.text


async def test_avisa_si_el_bloqueo_dejo_de_ser_nuestro(caplog: pytest.LogCaptureFixture) -> None:
    """`pg_advisory_unlock` devuelve si lo teníamos: es la única señal barata de que se perdió."""
    caplog.set_level(logging.WARNING, logger=LOGGER)
    conexion = ConexionFalsa(soltado=False)

    async with bloqueo_de_ingesta("NCO", _motor(conexion)):
        pass

    assert "ya no era nuestro" in caplog.text
