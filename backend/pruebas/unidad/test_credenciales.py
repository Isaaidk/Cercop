"""Pruebas de las reglas de credenciales y del bloqueo por intentos.

La política de contraseñas es el único sitio donde se decide qué es aceptable, así que se prueba
aislada, sin derivar ninguna huella. Y el bloqueo merece dos pruebas que parecen contradictorias
pero no lo son: que no bloquea al primer fallo (un error de tecleo no es un ataque) y que sí bloquea
al alcanzar el umbral.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from contratacion.dominio.credenciales import (
    INTENTOS_ANTES_DE_BLOQUEO,
    MINUTOS_DE_BLOQUEO,
    esta_bloqueada,
    intentos_tras_fallo,
    siguiente_bloqueo,
    validar_contrasena,
)
from contratacion.dominio.errores import DatoInvalido

AHORA = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)


def test_acepta_una_contrasena_larga_y_variada() -> None:
    validar_contrasena("correcto-caballo-bateria-grapa")


def test_rechaza_una_contrasena_demasiado_corta() -> None:
    with pytest.raises(DatoInvalido) as fallo:
        validar_contrasena("corta12")
    assert "12 caracteres" in str(fallo.value)


def test_rechaza_una_contrasena_demasiado_larga() -> None:
    with pytest.raises(DatoInvalido):
        validar_contrasena("a1b2" * 40)


def test_rechaza_pocos_caracteres_distintos() -> None:
    with pytest.raises(DatoInvalido):
        validar_contrasena("aaaaaaaaaaaa")


def test_rechaza_las_contrasenas_mas_usadas() -> None:
    with pytest.raises(DatoInvalido) as fallo:
        validar_contrasena("contrasenasegura")
    assert "más usadas" in str(fallo.value)


def test_rechaza_una_contrasena_que_contiene_el_correo() -> None:
    with pytest.raises(DatoInvalido) as fallo:
        validar_contrasena("maria.fernandez-2026", email="maria.fernandez@constructora.ec")
    assert "correo" in str(fallo.value)


def test_acepta_una_contrasena_larga_que_no_contiene_el_correo() -> None:
    validar_contrasena("viento-del-sur-2026", email="maria.fernandez@constructora.ec")


def test_un_correo_con_usuario_muy_corto_no_bloquea_contrasenas_razonables() -> None:
    """Comparar contra «ana» daría falsos positivos: aparece dentro de muchas palabras."""
    validar_contrasena("ana-banana-larga-2026", email="ana@constructora.ec")


def test_no_bloquea_al_primer_fallo() -> None:
    """Bloquear al primer error de tecleo sería convertir una errata en un cierre de sesión."""
    assert siguiente_bloqueo(1, AHORA) is None


def test_bloquea_al_alcanzar_el_umbral() -> None:
    assert siguiente_bloqueo(INTENTOS_ANTES_DE_BLOQUEO, AHORA) == AHORA + timedelta(
        minutes=MINUTOS_DE_BLOQUEO
    )


def test_el_bloqueo_caduca() -> None:
    hasta = AHORA + timedelta(minutes=MINUTOS_DE_BLOQUEO)
    assert esta_bloqueada(hasta, AHORA)
    assert not esta_bloqueada(hasta, hasta + timedelta(seconds=1))


def test_sin_bloqueo_no_esta_bloqueada() -> None:
    assert not esta_bloqueada(None, AHORA)


def test_los_intentos_nunca_bajan_de_cero() -> None:
    assert intentos_tras_fallo(0) == 1
    assert intentos_tras_fallo(-5) == 1
