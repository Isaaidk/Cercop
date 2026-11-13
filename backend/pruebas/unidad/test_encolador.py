"""Encolador: turnos, fila acotada, espera máxima, reparto entre empresas y liberación segura."""

from __future__ import annotations

import asyncio

import pytest

from contratacion.aplicacion.encolador import Encolador
from contratacion.dominio.errores import Saturado, ServicioNoDisponible


def _encolador(**cambios: float) -> Encolador:
    datos: dict[str, float] = {
        "en_paralelo": 2,
        "en_espera": 2,
        "espera_max_seg": 1.0,
        "por_empresa": 2,
    }
    datos.update(cambios)
    return Encolador(
        "prueba",
        en_paralelo=int(datos["en_paralelo"]),
        en_espera=int(datos["en_espera"]),
        espera_max_seg=datos["espera_max_seg"],
        por_empresa=int(datos["por_empresa"]),
    )


def test_nunca_corren_mas_que_los_turnos() -> None:
    async def caso() -> int:
        encolador = _encolador(en_paralelo=2, en_espera=10, espera_max_seg=5, por_empresa=10)
        maximo = 0
        activos = 0

        async def trabajo() -> None:
            nonlocal maximo, activos
            async with encolador.turno("a"):
                activos += 1
                maximo = max(maximo, activos)
                await asyncio.sleep(0.02)
                activos -= 1

        await asyncio.gather(*(trabajo() for _ in range(8)))
        return maximo

    assert asyncio.run(caso()) == 2


def test_con_la_fila_llena_rechaza_enseguida_con_503() -> None:
    async def caso() -> None:
        encolador = _encolador(en_paralelo=1, en_espera=1, espera_max_seg=5, por_empresa=5)
        soltar = asyncio.Event()

        async def ocupar() -> None:
            async with encolador.turno("a"):
                await soltar.wait()

        primero = asyncio.create_task(ocupar())
        await asyncio.sleep(0)
        segundo = asyncio.create_task(ocupar())  # espera en la fila
        await asyncio.sleep(0)
        with pytest.raises(Saturado) as error:
            async with encolador.turno("a"):
                pass
        assert error.value.reintentar_en >= 5
        assert isinstance(error.value, ServicioNoDisponible)  # se traduce a 503
        soltar.set()
        await asyncio.gather(primero, segundo)

    asyncio.run(caso())


def test_no_se_espera_mas_del_maximo() -> None:
    async def caso() -> None:
        encolador = _encolador(en_paralelo=1, en_espera=5, espera_max_seg=0.05, por_empresa=5)
        soltar = asyncio.Event()

        async def ocupar() -> None:
            async with encolador.turno("a"):
                await soltar.wait()

        tarea = asyncio.create_task(ocupar())
        await asyncio.sleep(0)
        with pytest.raises(Saturado):
            async with encolador.turno("a"):
                pass
        assert encolador.estado()["esperando"] == 0
        soltar.set()
        await tarea

    asyncio.run(caso())


def test_una_empresa_no_acapara_los_turnos() -> None:
    async def caso() -> list[str]:
        encolador = _encolador(en_paralelo=3, en_espera=20, espera_max_seg=5, por_empresa=1)
        orden: list[str] = []
        soltar_a = asyncio.Event()

        async def de_a() -> None:
            async with encolador.turno("empresa-a"):
                orden.append("a")
                await soltar_a.wait()

        async def de_b() -> None:
            async with encolador.turno("empresa-b"):
                orden.append("b")

        # La empresa A lanza cinco trabajos: solo uno entra; B entra aunque A siga esperando.
        tareas_a = [asyncio.create_task(de_a()) for _ in range(5)]
        await asyncio.sleep(0.01)
        await asyncio.wait_for(de_b(), timeout=1)
        soltar_a.set()
        await asyncio.gather(*tareas_a)
        return orden

    orden = asyncio.run(caso())
    assert orden[:2] == ["a", "b"]
    assert orden.count("a") == 5


def test_el_turno_se_suelta_aunque_el_trabajo_falle() -> None:
    async def caso() -> dict[str, int | str]:
        encolador = _encolador(en_paralelo=1)
        with pytest.raises(ValueError):
            async with encolador.turno("a"):
                raise ValueError("falló")
        async with encolador.turno("a"):
            pass
        return encolador.estado()

    estado = asyncio.run(caso())
    assert estado["activos"] == 0 and estado["esperando"] == 0
