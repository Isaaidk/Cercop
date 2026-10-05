"""Pruebas del dominio de la ingesta y de la normalización de palabras.

Sin base de datos, sin red y sin caché: son las reglas que deciden qué se guarda y qué se descarta,
así que se prueban aisladas y rápido.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from contratacion.dominio.ingesta import (
    DIAS_VENTANA_INICIAL,
    Clasificacion,
    ContadoresCiclo,
    Presupuesto,
    clasificar,
    clave_natural,
    hash_contenido,
    ventana_de_cola,
    ventana_desde,
)
from contratacion.dominio.palabras import dividir_terminos, normalizar, normalizar_termino

# --------------------------------------------------------------------------- #
# Clave natural
# --------------------------------------------------------------------------- #


def test_clave_natural_usa_los_identificadores_de_la_fuente() -> None:
    assert clave_natural("OCDS", ["ocds-abc-1"]) == "ocds-abc-1"


def test_clave_natural_ignora_partes_vacias() -> None:
    assert clave_natural("NCO", ["", "  123  ", ""]) == "123"


def test_clave_natural_sin_identificador_falla() -> None:
    """Sin identificador no hay forma de no duplicar, así que es mejor fallar de forma visible."""
    with pytest.raises(ValueError, match="no aportó ningún identificador"):
        clave_natural("NCO", ["", None or ""])


# --------------------------------------------------------------------------- #
# Huella de contenido
# --------------------------------------------------------------------------- #


def test_la_huella_ignora_el_orden_de_las_claves() -> None:
    """La fuente puede reordenar los campos sin que eso sea un cambio real."""
    assert hash_contenido({"a": 1, "b": 2}) == hash_contenido({"b": 2, "a": 1})


def test_la_huella_cambia_si_cambia_un_valor() -> None:
    assert hash_contenido({"estado": "En Curso"}) != hash_contenido({"estado": "Finalizada"})


def test_la_huella_admite_valores_no_serializables() -> None:
    """Un `datetime` del payload no debe romper el cálculo."""
    assert hash_contenido({"fecha": datetime(2026, 9, 27, tzinfo=UTC)}) != ""


def test_la_huella_ignora_los_campos_que_la_fuente_regenera() -> None:
    """El token de la ficha cambia en cada respuesta y no significa que el dato haya cambiado.

    Sin excluirlo, cada ciclo clasificaba las 1.700 necesidades como «actualizadas»: las reescribía
    todas y les añadía una versión al histórico (9.536 versiones para 2.873 registros).
    """
    base = {"codigo": "NIC-1", "objeto_compra": "Obra", "enlace": "../NCO/Detalle.cpe?id=AAA"}

    assert hash_contenido(base) == hash_contenido({**base, "enlace": "../NCO/Detalle.cpe?id=BBB"})
    assert hash_contenido(base) != hash_contenido({**base, "objeto_compra": "Otra obra"})


# --------------------------------------------------------------------------- #
# Clasificación
# --------------------------------------------------------------------------- #


def test_sin_huella_previa_es_nuevo() -> None:
    assert clasificar(None, "abc") is Clasificacion.NUEVO


def test_misma_huella_es_igual() -> None:
    assert clasificar("abc", "abc") is Clasificacion.IGUAL


def test_huella_distinta_es_actualizado() -> None:
    assert clasificar("abc", "def") is Clasificacion.ACTUALIZADO


# --------------------------------------------------------------------------- #
# Ventana de solape
# --------------------------------------------------------------------------- #


def test_la_ventana_solapa_hacia_atras() -> None:
    """Con 15 minutos de intervalo y 2 ciclos de solape, se releen 30 minutos anteriores."""
    ahora = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
    ultima = ahora - timedelta(minutes=15)
    assert ventana_desde(ultima, 15, 2, ahora) == ultima - timedelta(minutes=30)


def test_sin_ejecucion_previa_la_ventana_es_amplia() -> None:
    """Tras un fallo o en el primer arranque no se debe dejar un hueco sin cubrir.

    La ventana inicial no es un detalle: es lo que decide si un cliente que agrega una palabra clave
    ve las contrataciones publicadas **antes** de suscribirse. Si aquí se devolviera solo el solape
    de dos ciclos, todo lo anterior a la suscripción sería irrecuperable para siempre.
    """
    ahora = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
    assert ventana_desde(None, 15, 2, ahora) == ahora - timedelta(days=DIAS_VENTANA_INICIAL)
    assert DIAS_VENTANA_INICIAL > 30, "la ventana inicial tiene que ser más amplia que un solape"


def test_la_ventana_inicial_se_puede_configurar() -> None:
    ahora = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
    assert ventana_desde(None, 15, 2, ahora, 7) == ahora - timedelta(days=7)


def test_la_ventana_del_lote_la_fija_el_termino_mas_nuevo() -> None:
    """Basta con que un término nunca se haya buscado para leer el lote desde la ventana amplia."""
    ahora = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
    reciente = ahora - timedelta(minutes=5)

    # Todos conocidos: manda el más antiguo de los dos, con su solape.
    conocido = ventana_de_cola([reciente, reciente], 15, 2, ahora)
    assert conocido == reciente - timedelta(minutes=30)

    # Uno sin buscar: el lote entero se lee desde la ventana inicial.
    con_nuevo = ventana_de_cola([reciente, None], 15, 2, ahora)
    assert con_nuevo == ahora - timedelta(days=DIAS_VENTANA_INICIAL)


def test_un_lote_vacio_se_trata_como_todo_nuevo() -> None:
    ahora = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
    assert ventana_de_cola([], 15, 2, ahora) == ahora - timedelta(days=DIAS_VENTANA_INICIAL)


def test_la_ventana_no_mira_al_futuro() -> None:
    """Si el reloj se adelantó en un ciclo anterior, no se debe pedir datos del futuro."""
    ahora = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
    futura = ahora + timedelta(hours=3)
    assert ventana_desde(futura, 15, 2, ahora) == ahora - timedelta(minutes=30)


# --------------------------------------------------------------------------- #
# Presupuesto
# --------------------------------------------------------------------------- #


def test_el_presupuesto_se_agota_y_lo_avisa() -> None:
    presupuesto = Presupuesto(limite=2)
    assert presupuesto.consumir() is True
    assert presupuesto.consumir() is True
    assert presupuesto.agotado() is True
    assert presupuesto.consumir() is False
    assert presupuesto.restantes == 0


def test_contadores_avisan_sin_repetir() -> None:
    contadores = ContadoresCiclo()
    contadores.avisar("algo")
    contadores.avisar("algo")
    contadores.avisar("otra cosa")
    assert contadores.avisos == ["algo", "otra cosa"]


# --------------------------------------------------------------------------- #
# Normalización de palabras
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("GESTIÓN", "gestion"),
        ("  Salud   Pública ", "salud publica"),
        ("ÑANDÚ", "nandu"),
        (None, ""),
        ("", ""),
    ],
)
def test_normalizar(entrada: str | None, esperado: str) -> None:
    assert normalizar(entrada) == esperado


def test_terminos_equivalentes_comparten_clave() -> None:
    """Es lo que permite ingestarlos una sola vez para todos los negocios."""
    assert normalizar_termino(" Gestión ") == normalizar_termino("GESTION")


def test_dividir_terminos_descarta_los_demasiado_cortos() -> None:
    """La fuente rechaza búsquedas de menos de tres caracteres y gastarían presupuesto."""
    assert dividir_terminos("salud, ab, vía; obras") == ["salud", "vía", "obras"]


def test_dividir_terminos_elimina_duplicados_sin_acentos() -> None:
    assert dividir_terminos("gestión, GESTION, Gestion") == ["gestión"]
