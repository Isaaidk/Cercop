"""Pruebas de la configuración.

Verifican que la aplicación falla rápido y que rechaza configuraciones inseguras: son las
salvaguardas que impiden arrancar en producción con valores por defecto (vulnerabilidades V1 y V7
del ADR-000).
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from contratacion.infraestructura.config.ajustes import Ajustes

BASE: dict[str, Any] = {
    "database_url": "postgresql+asyncpg://u:c@127.0.0.1:5432/p",
    "redis_url": "redis://127.0.0.1:6379/0",
    "jwt_secreto": "s" * 48,
    "clave_cifrado_datos": "c" * 44,
    "clave_pepper_hmac": "p" * 44,
}


def _ajustes(**extra: Any) -> Ajustes:
    """Construye ajustes sin leer `.env`, para aislar la prueba de la máquina."""
    return Ajustes(_env_file=None, **{**BASE, **extra})


def test_carga_configuracion_valida() -> None:
    configuracion = _ajustes()
    assert configuracion.entorno == "dev"
    assert configuracion.max_sesiones_usuario == 2
    assert configuracion.ventana_solape_min == 30


def test_ventana_solape_derivada_del_intervalo() -> None:
    configuracion = _ajustes(intervalo_ingesta_min=15, ventana_solape_ciclos=2)
    assert configuracion.ventana_solape_min == 30


def test_el_cache_es_opcional() -> None:
    """Sin `REDIS_URL` el sistema funciona sin caché: es un modo válido, no un error."""
    assert _ajustes(redis_url="").cache_habilitada is False
    assert _ajustes(redis_url="   ").cache_habilitada is False
    assert _ajustes(redis_url="rediss://host:6379").cache_habilitada is True


def test_la_ventana_de_gracia_de_la_rotacion_no_baja_de_minutos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El valor por defecto importa, y por eso se fija aquí.

    Bajarlo otra vez no rompe ninguna prueba y sí cierra sesiones de verdad: la respuesta perdida
    —el portátil que se suspende, el proxy que corta la conexión— se reintenta **minutos** después,
    y con una ventana de treinta segundos ese reintento se lee como «hay dos copias en circulación».
    El servidor entonces cierra todas las sesiones de la cuenta y la persona aparece en el acceso
    sin haber hecho nada.
    """
    monkeypatch.delenv("REFRESH_GRACIA_SEG", raising=False)
    assert _ajustes().refresh_gracia_seg == 300


def test_la_ventana_de_gracia_se_puede_desactivar() -> None:
    """Ponerla a cero deja el comportamiento estricto, y es una configuración válida."""
    assert _ajustes(refresh_gracia_seg=0).refresh_gracia_seg == 0


def test_la_retencion_del_historico_esta_encendida_con_siete_dias() -> None:
    """El valor por defecto se fija aquí porque es una decisión de negocio, no técnica.

    Borrar una ínfima deja de permitir consultarla al día siguiente, así que el número tiene que
    estar escrito y no depender de lo que alguien ponga en su `.env`. Y "cero desactiva" tiene que
    seguir siendo posible: es la forma de conservar el histórico entero sin tocar el código.
    """
    configuracion = _ajustes()
    assert configuracion.purga_plazo_dias == 7
    assert configuracion.purga_max_filas_por_vuelta == 500
    assert configuracion.intervalo_mantenimiento_seg == 300


def test_la_retencion_se_puede_desactivar_y_rechaza_lo_imposible() -> None:
    assert _ajustes(purga_max_filas_por_vuelta=0).purga_max_filas_por_vuelta == 0
    assert _ajustes(purga_plazo_dias=0).purga_plazo_dias == 0
    with pytest.raises(ValidationError):
        _ajustes(purga_plazo_dias=-1)
    with pytest.raises(ValidationError):
        _ajustes(purga_max_filas_por_vuelta=-5)
    with pytest.raises(ValidationError):
        _ajustes(intervalo_mantenimiento_seg=29)


def test_la_ventana_de_gracia_no_admite_una_hora() -> None:
    """Más allá de cinco minutos, un token robado tendría una ventana de uso demasiado ancha."""
    with pytest.raises(ValidationError):
        _ajustes(refresh_gracia_seg=3_600)


@pytest.mark.parametrize("obligatorio", ["database_url", "jwt_secreto"])
def test_falta_variable_obligatoria_falla(
    obligatorio: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sin las variables obligatorias la configuración no se puede construir.

    Se elimina también la variable de entorno: `conftest` define valores válidos para el resto de
    la suite, y aquí lo que se prueba es justamente su ausencia.
    """
    monkeypatch.delenv(obligatorio.upper(), raising=False)
    incompleto = {clave: valor for clave, valor in BASE.items() if clave != obligatorio}
    with pytest.raises(ValidationError):
        Ajustes(_env_file=None, **incompleto)


def test_cors_comodin_rechazado() -> None:
    """`*` permitiría credenciales desde cualquier origen (vulnerabilidad V1)."""
    with pytest.raises(ValidationError):
        _ajustes(cors_origins="*")


def test_cors_separado_por_comas() -> None:
    configuracion = _ajustes(cors_origins="http://a.test, http://b.test")
    assert configuracion.cors_origins == ["http://a.test", "http://b.test"]


def test_algoritmo_de_firma_no_permitido() -> None:
    with pytest.raises(ValidationError):
        _ajustes(jwt_algoritmo="none")


def test_produccion_exige_secretos_largos() -> None:
    with pytest.raises(ValidationError):
        _ajustes(entorno="prod", jwt_secreto="corto")
