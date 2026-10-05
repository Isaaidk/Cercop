"""Pruebas del paso de la petición a los criterios: el filtro por CPC llega y se normaliza.

Lo que se comprueba aquí es la costura entre la URL y el dominio, que es donde un filtro nuevo se
pierde sin ruido: si el parámetro no se recoge, la consulta sale sin él y el panel devuelve **todo**
como si el criterio no existiera. No hay error, no hay aviso, y en pantalla parece que la búsqueda
no encontró nada relevante.

Se llama a la función que usan los tres endpoints de datos —tabla, gráficas y exportación— y no a
uno concreto, porque es la misma para los tres: comprobarla una vez es comprobar que los tres
filtran igual, que es justamente el motivo de que exista.
"""

from __future__ import annotations

from contratacion.dominio.acceso import Vista
from contratacion.dominio.busqueda import Filtros, ModoBusqueda, normalizar_terminos
from contratacion.infraestructura.adaptadores.entrada.http.routers.busqueda import (
    _filtros_compartidos,
)

# Una vista que concede la fuente de las ínfimas (NCO), que es la única que publica CPC.
VISTAS = frozenset({Vista.NECESIDADES})


def _filtros(
    *,
    termino: list[str] | None = None,
    cpc: list[str] | None = None,
    codigo: str | None = None,
) -> Filtros:
    """Los criterios de una petición, con lo mínimo que exige la función."""
    return _filtros_compartidos(
        termino=termino,
        cpc=cpc,
        modo=ModoBusqueda.TODAS,
        fuente=None,
        categoria=None,
        provincia=None,
        estado=None,
        entidad=None,
        tipo_proceso=None,
        tipo_necesidad=None,
        codigo=codigo,
        desde=None,
        hasta=None,
        solo_nuevos=False,
        solo_con_plazo=False,
        vistas=VISTAS,
        intervalo_ingesta_min=15,
    )


def test_el_cpc_de_la_peticion_llega_a_los_criterios() -> None:
    assert _filtros(cpc=["lavado"]).cpc == ("lavado",)


def test_sin_el_parametro_no_hay_criterio_de_cpc() -> None:
    """Ausente no es lo mismo que vacío: sin él no se añade ninguna condición."""
    assert _filtros().cpc == ()
    assert _filtros(cpc=[]).cpc == ()


def test_los_terminos_de_cpc_se_normalizan_como_los_demas() -> None:
    """Mayúsculas y acentos no pueden crear dos búsquedas distintas del mismo código."""
    assert _filtros(cpc=["LAVADO", "lavado"]).cpc == ("lavado",)
    assert _filtros(cpc=["Engrasado", "ASEO"]).cpc == ("aseo", "engrasado")


def test_los_terminos_de_cpc_se_ordenan() -> None:
    """El orden en que se escriben no cambia el resultado ni la entrada de caché."""
    assert _filtros(cpc=["lavado", "aseo"]).cpc == _filtros(cpc=["aseo", "lavado"]).cpc


def test_un_codigo_de_cpc_sirve_como_termino() -> None:
    """El cuadro de texto acepta el código, y un código es un término más."""
    assert _filtros(cpc=["871410032"]).cpc == ("871410032",)


def test_un_termino_demasiado_corto_se_descarta() -> None:
    """La fuente rechaza las búsquedas de menos de tres caracteres: no se llega a enviar."""
    assert _filtros(cpc=["la"]).cpc == ()


def test_el_nic_de_la_peticion_llega_a_los_criterios() -> None:
    """El NIC viaja como `codigo`, que es el criterio que el panel de ínfimas reutiliza.

    Se comprueba aquí —y no solo contra la base— porque es la costura donde un filtro nuevo se
    pierde sin ruido: si el parámetro no se recogiera, la tabla devolvería **todo** como si no
    hubiera criterio, y en pantalla parecería que el NIC buscado no existe.
    """
    nic = "NIC-1768120280001-2022-00003"
    assert _filtros(codigo=nic).codigo == nic


def test_sin_el_parametro_no_hay_criterio_de_nic() -> None:
    """Ausente no es lo mismo que vacío: sin NIC no se añade ninguna condición."""
    assert _filtros().codigo is None


def test_el_cpc_no_toca_los_terminos_de_palabras_clave() -> None:
    """Son dos listas independientes: se pueden usar por separado o las dos a la vez."""
    filtros = _filtros(termino=["hospital"], cpc=["lavado"])

    assert filtros.terminos == normalizar_terminos(["hospital"])
    assert filtros.cpc == ("lavado",)
