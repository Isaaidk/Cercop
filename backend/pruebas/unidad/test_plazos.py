"""El semáforo de días para proforma.

Los tres umbrales los ven dos consumidores distintos —el panel y el archivo de Excel— y el riesgo no
es que estén mal, sino que uno aplique un `>` donde el otro usa un `>=`. Entonces un mismo registro
sale amarillo en pantalla y verde en el archivo, y nadie sabe cuál creer.

Por eso los casos de frontera se prueban explícitamente: 7 es verde y 6 es amarillo; 3 es amarillo y
2 es rojo. Son los cuatro números que de verdad hay que fijar."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from contratacion.dominio.plazos import (
    DIAS_AMARILLO,
    DIAS_VERDE,
    NIVEL_AMARILLO,
    NIVEL_ROJO,
    NIVEL_SIN_FECHA,
    NIVEL_VERDE,
    dias_para_proforma,
    nivel_de_plazo,
    texto_de_plazo,
)

AHORA = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("dias", "esperado"),
    [
        (30, NIVEL_VERDE),
        (7, NIVEL_VERDE),
        (6, NIVEL_AMARILLO),
        (3, NIVEL_AMARILLO),
        (2, NIVEL_ROJO),
        (0, NIVEL_ROJO),
        (-5, NIVEL_ROJO),
    ],
)
def test_los_umbrales_del_semaforo(dias: int, esperado: str) -> None:
    assert nivel_de_plazo(dias) == esperado


def test_los_umbrales_son_los_que_dice_la_regla() -> None:
    """7 días o más, verde; menos de 7, amarillo; menos de 3, rojo."""
    assert nivel_de_plazo(DIAS_VERDE) == NIVEL_VERDE
    assert nivel_de_plazo(DIAS_VERDE - 1) == NIVEL_AMARILLO
    assert nivel_de_plazo(DIAS_AMARILLO) == NIVEL_AMARILLO
    assert nivel_de_plazo(DIAS_AMARILLO - 1) == NIVEL_ROJO


def test_sin_fecha_no_hay_color() -> None:
    """Un dato que falta no se pinta: inventarle un color sería afirmar algo que no se sabe."""
    assert nivel_de_plazo(None) == NIVEL_SIN_FECHA
    assert texto_de_plazo(None) == "Sin fecha límite"
    assert dias_para_proforma(None, ahora=AHORA) is None
    assert dias_para_proforma("", ahora=AHORA) is None
    assert dias_para_proforma("no es una fecha", ahora=AHORA) is None


def test_la_fecha_se_lee_del_texto_que_guarda_la_ingesta() -> None:
    limite = (AHORA + timedelta(days=10)).isoformat()
    assert dias_para_proforma(limite, ahora=AHORA) == 10


def test_una_fecha_sin_zona_se_interpreta_en_utc() -> None:
    """La ingesta normaliza a UTC; un texto sin zona no puede reventar ni cambiar de día."""
    assert dias_para_proforma("2026-10-07T12:00:00", ahora=AHORA) == 10


def test_el_plazo_que_vence_hoy_cuenta_cero_dias() -> None:
    """Cuenta días **completos**, y no es un detalle.

    Si se redondeara hacia arriba, algo que vence hoy a las 23:00 daría 1 día y el semáforo lo
    pintaría de amarillo —«queda tiempo»— cuando en realidad es para hoy.
    """
    assert dias_para_proforma("2026-09-27T23:00:00", ahora=AHORA) == 0
    assert nivel_de_plazo(0) == NIVEL_ROJO
    assert texto_de_plazo(0) == "Vence hoy"


def test_una_fecha_vencida_conserva_cuantos_dias_pasaron() -> None:
    """No se recorta a cero: «vencida hace cuatro días» y «vence hoy» son cosas distintas."""
    assert dias_para_proforma("2026-09-23T12:00:00", ahora=AHORA) == -4
    assert texto_de_plazo(-4) == "Vencida hace 4 días"
    assert texto_de_plazo(-1) == "Vencida hace 1 día"


@pytest.mark.parametrize(
    ("dias", "esperado"),
    [(1, "1 día"), (2, "2 días"), (10, "10 días")],
)
def test_el_texto_concuerda_en_numero(dias: int, esperado: str) -> None:
    assert texto_de_plazo(dias) == esperado
