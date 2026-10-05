"""Pruebas del adaptador de OCDS: qué páginas lee y qué términos da por completados.

Lo que se protege aquí es un fallo que no da la cara. La API pagina **de lo más antiguo a lo más
reciente**, así que leer las primeras páginas —que es lo que se hacía— trae lo de enero de 2026 y
nunca lo que se acaba de publicar: el ciclo se registraba como correcto, la tabla de ofertas se
quedaba meses atrás y nada en el sistema lo delataba.

La segunda decisión que se defiende es cuáles términos se dan por buscados. Marcarlos solo cuando el
ciclo entero sale bien condena la cola: con una fuente que responde 429 a menudo, los términos
—siempre los mismos— no se marcan nunca y los añadidos después no se buscan jamás.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from contratacion.dominio.ingesta import Presupuesto
from contratacion.infraestructura.adaptadores.salida.fuentes.limitador import LimitadorTasa
from contratacion.infraestructura.adaptadores.salida.fuentes.ocds import (
    PAGINAS_DEL_FINAL,
    FuenteOcds,
    FuenteOcdsGeneral,
)

AHORA = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
ANIO = 2026


class LimitadorDeMentira(LimitadorTasa):
    """Limitador sin red: devuelve las páginas que se le digan y anota cuáles se pidieron.

    Hereda de `LimitadorTasa` para que el tipo encaje sin cambiar el puerto por un protocolo: lo
    único que se sustituye es la petición.
    """

    def __init__(self, paginas: dict[tuple[str, int, int], dict[str, Any] | None]) -> None:
        super().__init__()
        self._paginas = paginas
        self.pedidas: list[tuple[str, int, int]] = []

    async def solicitar_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        *,
        etiqueta: str = "",
        tiempo_limite: float = 60.0,
    ) -> dict[str, Any] | None:
        del url, etiqueta, tiempo_limite  # No hay red: no se usan.
        assert params is not None
        clave = (str(params["search"]), int(params["year"]), int(params["page"]))
        self.pedidas.append(clave)
        return self._paginas.get(clave)


def _pagina(total: int, fechas: list[str]) -> dict[str, Any]:
    return {"pages": total, "data": [{"ocid": f"ocds-{fecha}", "date": fecha} for fecha in fechas]}


def _fuente(
    paginas: dict[tuple[str, int, int], dict[str, Any] | None], *terminos: str
) -> tuple[FuenteOcds, LimitadorDeMentira]:
    limitador = LimitadorDeMentira(paginas)
    return FuenteOcds(list(terminos), limitador=limitador, anios=[ANIO]), limitador


async def test_lee_la_primera_pagina_y_las_ultimas() -> None:
    """La primera dice cuántas páginas hay; el final es donde está lo recién publicado."""
    fuente, limitador = _fuente(
        {
            ("obras", ANIO, 1): _pagina(535, ["2026-01-05"]),
            ("obras", ANIO, 534): _pagina(535, ["2026-09-29"]),
            ("obras", ANIO, 535): _pagina(535, ["2026-09-30"]),
        },
        "obras",
    )

    resultado = await fuente.extraer(AHORA, Presupuesto(limite=10))

    assert limitador.pedidas == [
        ("obras", ANIO, 1),
        ("obras", ANIO, 534),
        ("obras", ANIO, 535),
    ]
    assert [registro["ocid"] for registro in resultado.registros] == [
        "ocds-2026-01-05",
        "ocds-2026-09-29",
        "ocds-2026-09-30",
    ]
    assert resultado.terminos_completos == ("obras",)


async def test_la_ultima_pagina_no_se_pide_dos_veces() -> None:
    # Con `PAGINAS_DEL_FINAL` mayor que el número de páginas, el rango incluiría la 1 otra vez.
    fuente, limitador = _fuente({("obras", ANIO, 1): _pagina(1, ["2026-01-05"])}, "obras")

    resultado = await fuente.extraer(AHORA, Presupuesto(limite=10))

    assert limitador.pedidas == [("obras", ANIO, 1)]
    assert len(resultado.registros) == 1


async def test_las_paginas_del_final_son_las_configuradas() -> None:
    paginas: dict[tuple[str, int, int], dict[str, Any] | None] = {
        ("obras", ANIO, 1): _pagina(10, ["2026-01-05"])
    }
    for pagina in range(10 - PAGINAS_DEL_FINAL + 1, 11):
        paginas[("obras", ANIO, pagina)] = _pagina(10, ["2026-09-30"])
    fuente, limitador = _fuente(paginas, "obras")

    await fuente.extraer(AHORA, Presupuesto(limite=10))

    assert [pagina for _, _, pagina in limitador.pedidas] == [1, 9, 10]


async def test_un_fallo_deja_el_termino_pendiente() -> None:
    """Un término al que le falló una página no puede darse por buscado: quedaría un hueco."""
    fuente, _ = _fuente(
        {
            ("obras", ANIO, 1): _pagina(535, ["2026-01-05"]),
            ("obras", ANIO, 534): None,
            ("obras", ANIO, 535): _pagina(535, ["2026-09-30"]),
        },
        "obras",
    )

    resultado = await fuente.extraer(AHORA, Presupuesto(limite=10))

    assert resultado.parcial is True
    assert resultado.terminos_completos == ()


async def test_un_termino_completo_se_marca_aunque_otro_falle() -> None:
    """Es lo que impide que un 429 congele la cola en los mismos veinte términos."""
    fuente, _ = _fuente(
        {
            ("obras", ANIO, 1): _pagina(2, ["2026-01-05"]),
            ("obras", ANIO, 2): _pagina(2, ["2026-09-30"]),
            ("cultura", ANIO, 1): None,
        },
        "obras",
        "cultura",
    )

    resultado = await fuente.extraer(AHORA, Presupuesto(limite=10))

    assert resultado.terminos_completos == ("obras",)
    assert resultado.parcial is True


async def test_el_presupuesto_agotado_no_marca_el_termino_a_medias() -> None:
    fuente, limitador = _fuente(
        {
            ("obras", ANIO, 1): _pagina(535, ["2026-01-05"]),
            ("obras", ANIO, 534): _pagina(535, ["2026-09-29"]),
            ("obras", ANIO, 535): _pagina(535, ["2026-09-30"]),
        },
        "obras",
    )

    resultado = await fuente.extraer(AHORA, Presupuesto(limite=2))

    assert resultado.agoto_presupuesto is True
    assert resultado.terminos_completos == ()
    assert len(limitador.pedidas) == 2


# --------------------------------------------------------------------------- #
# Modo general: el rabo del listado, sin palabras clave
#
# Es la forma de ingesta de OCDS desde el 2026-10-01: una petición para saber cuántas páginas hay
# más las que hayan crecido, en lugar de una por término, año y página. La búsqueda por término no
# desaparece: queda como **rescate** de una palabra que nunca se ha buscado.
# --------------------------------------------------------------------------- #


def _fuente_general(
    paginas: dict[tuple[str, int, int], dict[str, Any] | None],
    *terminos: str,
    paginas_por_ciclo: int = 40,
) -> tuple[FuenteOcdsGeneral, LimitadorDeMentira]:
    limitador = LimitadorDeMentira(paginas)
    fuente = FuenteOcdsGeneral(
        list(terminos),
        paginas_por_ciclo=paginas_por_ciclo,
        limitador=limitador,
        anios=[ANIO],
    )
    return fuente, limitador


async def test_el_modo_general_lee_el_rabo_del_listado() -> None:
    """Con la ventana al día basta la primera página —que dice cuántas hay— y la última.

    `datetime.now` como punto de partida deja el tope en su mínimo (dos páginas), que es el caso
    normal: entre dos ciclos de quince minutos el listado crece menos de media página.
    """
    fuente, limitador = _fuente_general(
        {
            ("", ANIO, 1): _pagina(3, ["2026-02-04"]),
            ("", ANIO, 3): _pagina(3, ["2026-09-30"]),
        }
    )

    resultado = await fuente.extraer(datetime.now(UTC), Presupuesto(limite=10))

    assert limitador.pedidas == [("", ANIO, 1), ("", ANIO, 3)]
    assert len(resultado.registros) == 2
    assert resultado.parcial is False


async def test_el_modo_general_acota_las_paginas_que_lee() -> None:
    """Un arranque en frío trae noventa días de ventana: el tope evita leer el año de una vez."""
    fuente, limitador = _fuente_general(
        {("", ANIO, pagina): _pagina(10, ["2026-09-30"]) for pagina in range(1, 11)},
        paginas_por_ciclo=3,
    )

    await fuente.extraer(datetime.now(UTC) - timedelta(days=90), Presupuesto(limite=10))

    assert [pagina for _, _, pagina in limitador.pedidas] == [1, 10, 9]


async def test_el_modo_general_no_declara_ningun_termino() -> None:
    """Lo que entra por el rabo no lo trajo ninguna palabra clave, y decirlo importa: si declarara
    un término, el ciclo lo daría por buscado sin haberlo buscado."""
    fuente, _ = _fuente_general({("", ANIO, 1): _pagina(1, ["2026-09-30"])})

    resultado = await fuente.extraer(datetime.now(UTC), Presupuesto(limite=10))

    assert resultado.terminos_completos == ()
    assert fuente.terminos({"ocid": "ocds-1"}) == []


async def test_el_modo_general_rescata_los_terminos_que_se_le_pasan() -> None:
    """El rabo no recupera lo anterior a esta fuente: eso es el rescate, y una vez por término."""
    fuente, limitador = _fuente_general(
        {
            ("", ANIO, 1): _pagina(1, ["2026-09-30"]),
            ("mantenimiento", ANIO, 1): _pagina(1, ["2026-09-30"]),
        },
        "mantenimiento",
    )

    resultado = await fuente.extraer(datetime.now(UTC), Presupuesto(limite=10))

    assert limitador.pedidas == [("", ANIO, 1), ("mantenimiento", ANIO, 1)]
    assert resultado.terminos_completos == ("mantenimiento",)
    assert len(resultado.registros) == 2
