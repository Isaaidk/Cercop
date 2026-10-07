"""Pruebas de la ventana de descarga: qué se puede exportar y desde cuándo.

La regla es un **rechazo**, no un recorte, y eso es lo que se defiende aquí: un archivo al que le
faltan filas sin decirlo deja de coincidir con lo que hay en pantalla, y quien lo recibe no tiene
forma de saberlo. Las pruebas fijan las tres fronteras —sin fecha, fecha por dentro y fecha por
fuera— y el ajuste de los meses de calendario, que es donde está el error fácil: tres meses atrás
desde el 31 de mayo no es el 31 de febrero.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

from contratacion.aplicacion.casos_uso.exportar_registros import exportar
from contratacion.dominio.busqueda import Filtros
from contratacion.dominio.errores import DatoInvalido
from contratacion.dominio.exportacion import (
    MESES_EXPORTABLES,
    inicio_exportable,
    revisar_ventana,
)

# Un instante cualquiera, en horario de Ecuador (UTC-5): las 10:00 del 6 de octubre son las 15:00
# UTC.
AHORA = datetime(2026, 10, 6, 15, 0, tzinfo=UTC)


def test_la_ventana_son_tres_meses_de_calendario() -> None:
    assert MESES_EXPORTABLES == 3
    assert inicio_exportable(AHORA) == date(2026, 7, 6)


@pytest.mark.parametrize(
    ("momento", "esperado"),
    [
        # El 31 de mayo: tres meses atrás no es el 31 de febrero, que no existe.
        (datetime(2026, 5, 31, 15, 0, tzinfo=UTC), date(2026, 2, 28)),
        # Año bisiesto: el 31 de mayo de 2028 sí cae en un febrero de 29.
        (datetime(2028, 5, 31, 15, 0, tzinfo=UTC), date(2028, 2, 29)),
        # Cambio de año hacia atrás.
        (datetime(2026, 1, 15, 15, 0, tzinfo=UTC), date(2025, 10, 15)),
    ],
)
def test_el_dia_se_ajusta_al_ultimo_del_mes_de_destino(momento: datetime, esperado: date) -> None:
    assert inicio_exportable(momento) == esperado


def test_el_limite_se_calcula_en_la_zona_del_negocio() -> None:
    """Con UTC, a las 23:00 de Ecuador el límite se iría un día hacia adelante.

    El panel filtra por días naturales de Ecuador, así que un límite calculado en UTC dejaría fuera
    el primer día de la ventana a quien pidiera la descarga de noche.
    """
    # 02:00 UTC del 7 de octubre = 21:00 del 6 en Ecuador.
    madrugada = datetime(2026, 10, 7, 2, 0, tzinfo=UTC)

    assert inicio_exportable(madrugada) == date(2026, 7, 6)


def test_una_descarga_sin_fecha_inicial_se_rechaza() -> None:
    """Sin fecha, la consulta abarcaría el histórico entero: 110.000 registros sin paginar."""
    with pytest.raises(DatoInvalido) as fallo:
        revisar_ventana(None, momento=AHORA)

    # El mensaje tiene que decir qué hacer, con la fecha exacta que se puede escribir.
    assert "2026-07-06" in str(fallo.value)


def test_una_descarga_mas_antigua_que_la_ventana_se_rechaza() -> None:
    with pytest.raises(DatoInvalido) as fallo:
        revisar_ventana(date(2026, 1, 1), momento=AHORA)

    assert "2026-07-06" in str(fallo.value)


def test_la_descarga_exactamente_en_el_limite_se_acepta() -> None:
    """El borde entra: la ventana es «desde el límite», no «después del límite»."""
    assert revisar_ventana(date(2026, 7, 6), momento=AHORA) == date(2026, 7, 6)


def test_una_descarga_dentro_de_la_ventana_se_acepta() -> None:
    assert revisar_ventana(date(2026, 9, 1), momento=AHORA) == date(2026, 7, 6)


async def test_el_caso_de_uso_rechaza_antes_de_consultar() -> None:
    """El rechazo va antes de tocar la base.

    Importa por lo que se está protegiendo: si la consulta cara se lanzara primero y el rechazo
    llegara después, la ventana no ahorraría nada de lo que viene a ahorrar.
    """

    class RepositorioQueNoSeDebeUsar:
        llamadas = 0

        async def todos(self, *_: Any, **__: Any) -> tuple[Any, ...]:
            self.llamadas += 1
            return ()

    repositorio = RepositorioQueNoSeDebeUsar()
    with pytest.raises(DatoInvalido):
        await exportar(
            Filtros(desde=date(2026, 1, 1)),
            repositorio=repositorio,  # type: ignore[arg-type]
            limite=100,
            momento=AHORA,
        )

    assert repositorio.llamadas == 0
