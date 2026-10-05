"""Pruebas del adaptador de NCO: el listado completo y el contrato que lee el ciclo.

Lo que se protege aquí es un fallo que no se anunció, sino que se cobró los datos en silencio. El
ciclo de ingesta lee `terminos_completos` del resultado de **cualquier** fuente, pero el campo solo
lo escribía OCDS —el contrato nunca lo declaró—. Con NCO, que es la fuente principal, esa lectura
levantaba `AttributeError`; el ciclo lo registraba como «fallo inesperado durante la ingesta» y el
resultado era **cero registros en cada ciclo**: el listado entero se descargaba, se descartaba, y
ningún aviso llegaba a la pantalla. La prueba de OCDS no podía verlo, porque probaba justamente la
fuente que sí escribe el campo.

De ahí las dos cosas que se defienden: que NCO no completa ningún término (no busca por término, se
ingesta completo) y que el campo está **declarado en el contrato**, que es lo que hace que ninguna
otra fuente pueda olvidarlo.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from contratacion.aplicacion.puertos.fuente import ResultadoExtraccion
from contratacion.dominio.ingesta import Presupuesto
from contratacion.infraestructura.adaptadores.salida.fuentes.limitador import LimitadorTasa
from contratacion.infraestructura.adaptadores.salida.fuentes.nco import (
    AVISO_SIN_RESPUESTA,
    FuenteNco,
)

AHORA = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


class LimitadorDeMentira(LimitadorTasa):
    """Limitador sin red: devuelve un payload fijo y anota qué se le pidió.

    Hereda de `LimitadorTasa` para que el tipo encaje sin cambiar el puerto por un protocolo: lo
    único que se sustituye es la petición.
    """

    def __init__(self, payload: dict[str, Any] | None) -> None:
        super().__init__()
        self._payload = payload
        self.pedidas: list[dict[str, Any] | None] = []

    async def solicitar_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        *,
        etiqueta: str = "",
        tiempo_limite: float = 60.0,
    ) -> dict[str, Any] | None:
        del url, etiqueta, tiempo_limite  # No hay red: no se usan.
        self.pedidas.append(params)
        return self._payload


def _fuente(payload: dict[str, Any] | None) -> tuple[FuenteNco, LimitadorDeMentira]:
    limitador = LimitadorDeMentira(payload)
    return FuenteNco(limitador=limitador), limitador


def _listado(*codigos: str) -> dict[str, Any]:
    return {
        "data": [
            {"tcom_necesidad_contratacion_id": codigo, "codigo_contratacion": f"NIC-{codigo}"}
            for codigo in codigos
        ]
    }


async def test_el_listado_llega_completo_en_una_sola_peticion() -> None:
    """NCO no pagina: una petición devuelve todo lo vigente."""
    fuente, limitador = _fuente(_listado("1", "2", "3"))

    resultado = await fuente.extraer(AHORA, Presupuesto(limite=10))

    assert limitador.pedidas == [{"lot": 1}]
    assert resultado.peticiones == 1
    assert [registro["codigo_contratacion"] for registro in resultado.registros] == [
        "NIC-1",
        "NIC-2",
        "NIC-3",
    ]


async def test_nco_no_da_por_completado_ningun_termino() -> None:
    """NCO se ingesta completo, sin términos: la tupla vacía es la verdad, no un olvido."""
    fuente, _ = _fuente(_listado("1"))

    resultado = await fuente.extraer(AHORA, Presupuesto(limite=10))

    assert resultado.terminos_completos == ()


async def test_el_contrato_declara_los_terminos_para_todas_las_fuentes() -> None:
    """El campo lo lee el ciclo en cualquier fuente, así que no puede faltar en ninguna.

    Esta es la prueba que habría evitado el fallo: comprueba el contrato directamente, sin depender
    de qué fuente lo escriba. Antes de que el campo se declarara, el propio ciclo levantaba
    `AttributeError` y una fuente que no lo tocaba —NCO— se quedaba sin ingestar.
    """
    assert ResultadoExtraccion().terminos_completos == ()


async def test_sin_respuesta_el_ciclo_queda_parcial_y_lo_dice() -> None:
    """Un listado que no llega no puede pasar por «todo igual»: hay que marcarlo como parcial."""
    fuente, _ = _fuente(None)

    resultado = await fuente.extraer(AHORA, Presupuesto(limite=10))

    assert resultado.parcial is True
    assert resultado.avisos == [AVISO_SIN_RESPUESTA]
    # Las salidas tempranas son el otro sitio donde el campo se puede olvidar.
    assert resultado.terminos_completos == ()


async def test_un_payload_inesperado_no_se_toma_por_listado_vacio() -> None:
    """`data` sin ser lista es un fallo de la fuente; darlo por vacío cerraría registros vivos."""
    fuente, _ = _fuente({"data": "vaya"})

    resultado = await fuente.extraer(AHORA, Presupuesto(limite=10))

    assert resultado.registros == []
    assert resultado.parcial is True
    assert resultado.avisos == [AVISO_SIN_RESPUESTA]


async def test_sin_presupuesto_no_se_toca_la_red() -> None:
    """El presupuesto se respeta antes de pedir nada."""
    fuente, limitador = _fuente(_listado("1"))

    resultado = await fuente.extraer(AHORA, Presupuesto(limite=0))

    assert limitador.pedidas == []
    assert resultado.agoto_presupuesto is True
    assert resultado.parcial is True
