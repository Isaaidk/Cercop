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

    def __init__(self, payload: dict[str, Any] | None, html: str | None = None) -> None:
        super().__init__()
        self._payload = payload
        self._html = html
        self.pedidas: list[dict[str, Any] | None] = []
        self.pedidas_texto: list[dict[str, Any] | None] = []

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

    async def solicitar_texto(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        *,
        etiqueta: str = "",
        tiempo_limite: float = 60.0,
    ) -> str | None:
        """Anota la ficha pedida en lugar de bajarla, para poder comprobar que no se pide de más."""
        del url, etiqueta, tiempo_limite
        self.pedidas_texto.append(params)
        return self._html


def _fuente(
    payload: dict[str, Any] | None, html: str | None = None
) -> tuple[FuenteNco, LimitadorDeMentira]:
    limitador = LimitadorDeMentira(payload, html)
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


HTML_FICHA = """
<table>
  <tr><th>Nro.</th><th>CPC</th><th>Nombre del CPC</th>
      <th>Descripción del producto</th><th>Unidad</th><th>Cantidad</th></tr>
  <tr><td>1</td><td>871410032</td><td>LAVADO Y ENGRASADO DE AUTOMOTORES</td>
      <td>Lavado y engrasado de la volqueta</td><td>Unidad</td><td>6.00</td></tr>
</table>
"""


async def test_con_token_se_lee_la_ficha_y_llegan_los_items() -> None:
    """El camino que hace que el CPC exista: el token sale del enlace y la ficha se analiza."""
    fuente, limitador = _fuente(_listado("1"), HTML_FICHA)

    items = await fuente.items(
        "../NCO/NCORegistroDetalle.cpe?&id=kgFtZf7MCICk,&op=0", Presupuesto(limite=10)
    )

    assert items is not None
    assert [item.codigo for item in items] == ["871410032"]
    assert limitador.pedidas_texto == [{"id": "kgFtZf7MCICk", "op": 0}]


async def test_un_enlace_sin_token_no_se_da_por_leido() -> None:
    """Un enlace del que no sale el token es «no se pudo», no «leída y sin detalle».

    Es la diferencia que separa reintentar de perder, y no es un caso teórico: el token del enlace
    **rota en cada listado**, así que el que hoy no se puede sacar puede llegar en la vuelta
    siguiente. Devolver la tupla vacía marcaría la necesidad como leída sin ítems y esa necesidad no
    volvería a pedirse nunca, sin ningún error que lo delatara.
    """
    fuente, limitador = _fuente(_listado("1"))

    sin_token = await fuente.items(
        "https://portal/NCO/NCORegistroDetalle.cpe", Presupuesto(limite=10)
    )
    assert sin_token is None
    assert await fuente.items(None, Presupuesto(limite=10)) is None
    # Y sin token no se gasta ninguna petición: el enlace no da con qué pedir la ficha.
    assert limitador.pedidas_texto == []


async def test_sin_presupuesto_la_ficha_queda_pendiente_y_no_se_pide() -> None:
    """El tope de peticiones se respeta antes de tocar la red, y no marca la ficha como leída."""
    fuente, limitador = _fuente(_listado("1"), HTML_FICHA)

    items = await fuente.items("../NCO/NCORegistroDetalle.cpe?&id=abc,&op=0", Presupuesto(limite=0))

    assert items is None
    assert limitador.pedidas_texto == []
