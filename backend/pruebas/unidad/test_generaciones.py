"""Pruebas del memo en proceso de la generación del caché.

El memo existe para gastar menos comandos, y ese ahorro es justo su parte peligrosa: un memo mal
hecho deja de enterarse de los cambios y sirve datos viejos sin que nada falle. Así que aquí se
comprueban las dos mitades —que ahorra y que sigue viendo los cambios— además del caso que más
importa: que un almacén caído **no** se memorice, porque hacerlo convertiría un fallo de un segundo
en un fallo que dura todo el memo.

Las pruebas vacían el memo antes de empezar. Es estado del proceso y todas comparten proceso: sin
vaciarlo, una prueba vería lo que dejó la anterior y el fallo aparecería en la prueba equivocada.
"""

from __future__ import annotations

import pytest

from contratacion.aplicacion import generaciones
from contratacion.dominio.busqueda import GENERACION_GLOBAL, clave_generacion


class CacheContador:
    """Caché en memoria que cuenta las lecturas y puede fallar a voluntad.

    Implementa el protocolo completo aunque esta prueba no use todo: un doble al que le falten
    métodos no falla al escribirlo, falla el día que alguien usa el que falta.
    """

    def __init__(self, *, generacion: str | None = "7", falla: bool = False) -> None:
        self.guardadas: dict[str, str] = {}
        if generacion is not None:
            self.guardadas[clave_generacion(GENERACION_GLOBAL)] = generacion
        self.lecturas = 0
        self.falla = falla

    async def obtener(self, clave: str) -> str | None:
        self.lecturas += 1
        if self.falla:
            raise RuntimeError("el almacén no responde")
        return self.guardadas.get(clave)

    @property
    def habilitada(self) -> bool:
        return True

    async def obtener_renovando(self, clave: str, ttl_seg: int) -> str | None:
        return await self.obtener(clave)

    async def guardar(self, clave: str, valor: str, ttl_seg: int) -> None:
        self.guardadas[clave] = valor

    async def eliminar(self, clave: str) -> None:
        self.guardadas.pop(clave, None)

    async def incrementar(self, clave: str) -> int:
        resultado = int(self.guardadas.get(clave, "0")) + 1
        self.guardadas[clave] = str(resultado)
        return resultado

    async def ping(self) -> bool:
        return not self.falla

    async def cerrar(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _memo_limpio() -> None:
    """Arranca cada prueba con el memo vacío, venga de donde venga el estado anterior."""
    generaciones.limpiar_memo()


# --------------------------------------------------------------------------- #
# Ahorro de comandos
# --------------------------------------------------------------------------- #


async def test_sin_memo_cada_lectura_va_al_almacen() -> None:
    cache = CacheContador()

    assert await generaciones.leer_generacion(cache) == 7
    assert await generaciones.leer_generacion(cache) == 7

    assert cache.lecturas == 2


async def test_con_memo_la_segunda_lectura_no_va_al_almacen() -> None:
    cache = CacheContador()

    assert await generaciones.leer_generacion(cache, ttl_memo_seg=30) == 7
    assert await generaciones.leer_generacion(cache, ttl_memo_seg=30) == 7

    assert cache.lecturas == 1


async def test_la_fuente_forma_parte_del_memo() -> None:
    """Dos fuentes tienen contadores distintos: compartir uno daría la generación de la otra."""
    cache = CacheContador()
    cache.guardadas[clave_generacion("NCO")] = "3"

    assert await generaciones.leer_generacion(cache, "NCO", ttl_memo_seg=30) == 3
    assert await generaciones.leer_generacion(cache, ttl_memo_seg=30) == 7


# --------------------------------------------------------------------------- #
# El memo caduca
# --------------------------------------------------------------------------- #


async def test_el_memo_caduca_y_vuelve_a_preguntar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ahora: dict[str, float] = {"t": 1.0}
    monkeypatch.setattr(generaciones, "monotonic", lambda: ahora["t"])
    cache = CacheContador()

    assert await generaciones.leer_generacion(cache, ttl_memo_seg=5) == 7
    assert await generaciones.leer_generacion(cache, ttl_memo_seg=5) == 7
    assert cache.lecturas == 1

    ahora["t"] = 100.0

    assert await generaciones.leer_generacion(cache, ttl_memo_seg=5) == 7
    assert cache.lecturas == 2


async def test_el_memo_tiene_tope_aunque_pidan_mas(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un memo de horas dejaría de enterarse de los ciclos de ingesta sin que nada lo delatara."""
    ahora: dict[str, float] = {"t": 1.0}
    monkeypatch.setattr(generaciones, "monotonic", lambda: ahora["t"])
    cache = CacheContador()

    assert await generaciones.leer_generacion(cache, ttl_memo_seg=86_400) == 7

    ahora["t"] = float(generaciones.MEMO_MAXIMO_SEG + 2)

    assert await generaciones.leer_generacion(cache, ttl_memo_seg=86_400) == 7
    assert cache.lecturas == 2


async def test_limpiar_el_memo_vuelve_a_preguntar() -> None:
    cache = CacheContador()

    assert await generaciones.leer_generacion(cache, ttl_memo_seg=30) == 7
    generaciones.limpiar_memo()
    assert await generaciones.leer_generacion(cache, ttl_memo_seg=30) == 7

    assert cache.lecturas == 2


# --------------------------------------------------------------------------- #
# Un fallo no se memoriza
# --------------------------------------------------------------------------- #


async def test_un_almacen_caido_no_se_memoriza() -> None:
    """Memorizar el cero de un fallo alargaría el fallo todo lo que dure el memo."""
    cache = CacheContador(falla=True)

    assert await generaciones.leer_generacion(cache, ttl_memo_seg=30) == 0
    assert await generaciones.leer_generacion(cache, ttl_memo_seg=30) == 0

    assert cache.lecturas == 2


async def test_sin_contador_la_generacion_es_cero_y_se_puede_memorizar() -> None:
    """Cero es «todavía no hubo cambios», no un fallo: ese sí se recuerda."""
    cache = CacheContador(generacion=None)

    assert await generaciones.leer_generacion(cache, ttl_memo_seg=30) == 0
    assert await generaciones.leer_generacion(cache, ttl_memo_seg=30) == 0

    assert cache.lecturas == 1


async def test_una_generacion_ilegible_no_tumba_la_lectura() -> None:
    cache = CacheContador(generacion="no es un entero")

    assert await generaciones.leer_generacion(cache, ttl_memo_seg=30) == 0
    assert cache.lecturas == 1


# --------------------------------------------------------------------------- #
# Subir el contador olvida lo memorizado
# --------------------------------------------------------------------------- #


async def test_subir_la_generacion_olvida_lo_memorizado() -> None:
    """Quien sube el contador es el que menos puede seguir sirviendo el valor anterior."""
    cache = CacheContador()

    assert await generaciones.leer_generacion(cache, ttl_memo_seg=30) == 7

    await generaciones.subir_generacion(cache)

    assert await generaciones.leer_generacion(cache, ttl_memo_seg=30) == 8
    assert cache.lecturas == 2


async def test_subir_una_fuente_no_olvida_las_demas() -> None:
    """Invalidar de más no rompe nada, pero cuesta comandos: cada fuente tiene su contador."""
    cache = CacheContador()
    cache.guardadas[clave_generacion("NCO")] = "3"

    assert await generaciones.leer_generacion(cache, "NCO", ttl_memo_seg=30) == 3
    assert await generaciones.leer_generacion(cache, ttl_memo_seg=30) == 7

    await generaciones.subir_generacion(cache, "NCO")

    assert await generaciones.leer_generacion(cache, ttl_memo_seg=30) == 7
    assert cache.lecturas == 2
