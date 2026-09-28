"""Pruebas del enlace al proceso original.

El caso que de verdad importa es el de la fuente NCO, porque es el único que publica un enlace y el
único que tiene datos en producción: 1.352 de 1.352 registros traen el suyo. Los demás casos fijan
las negativas, que es donde está el riesgo de esta función: componer una dirección con pinta de
buena para un dato que no la trae, o dejar pasar un esquema que no sea http.
"""

from __future__ import annotations

from contratacion.dominio.enlaces import enlace_publico

# Los valores reales: el `endpoint` de la fuente y un `url` tal y como lo publica el portal.
ENDPOINT_NCO = (
    "https://www.compraspublicas.gob.ec/ProcesoContratacion/compras/NCO/NCORetornaRegistros.cpe"
)
ENLACE_RELATIVO = (
    "../NCO/NCORegistroDetalle.cpe?&id=kLa0F1tC18GLM89aUAX9UAvV7k4MN4zqv5fPmkOXxNw,&op=0"
)
ESPERADO = (
    "https://www.compraspublicas.gob.ec/ProcesoContratacion/compras/NCO/"
    "NCORegistroDetalle.cpe?&id=kLa0F1tC18GLM89aUAX9UAvV7k4MN4zqv5fPmkOXxNw,&op=0"
)


def test_resuelve_el_enlace_real_de_la_fuente_nco() -> None:
    """La dirección que abre la ficha, con su consulta intacta.

    La consulta lleva un `&` suelto delante y una coma al final del identificador, tal y como los
    publica el portal. Recortarlos o reordenarlos cambiaría la petición que recibe el servidor, y el
    enlace dejaría de abrir la ficha concreta aunque la página cargara.
    """
    assert enlace_publico(ENLACE_RELATIVO, ENDPOINT_NCO) == ESPERADO


def test_sin_enlace_no_hay_direccion() -> None:
    """La fuente OCDS no publica ninguna. No se inventa: se devuelve nada."""
    assert enlace_publico(None, ENDPOINT_NCO) is None
    assert enlace_publico("", ENDPOINT_NCO) is None


def test_sin_base_no_hay_direccion() -> None:
    """Un enlace relativo sin saber de dónde es no se puede resolver."""
    assert enlace_publico(ENLACE_RELATIVO, None) is None
    assert enlace_publico(ENLACE_RELATIVO, "") is None


def test_una_direccion_ya_absoluta_se_respeta() -> None:
    absoluta = "https://www.compraspublicas.gob.ec/otra/ruta.cpe?id=1"
    assert enlace_publico(absoluta, ENDPOINT_NCO) == absoluta


def test_una_base_que_no_es_http_no_produce_enlace() -> None:
    assert enlace_publico("detalle.cpe?id=1", "ftp://archivos.example.com/x") is None


def test_rechaza_el_esquema_relativo_al_protocolo() -> None:
    """`//otro-sitio/x` se resolvería como absoluto y sacaría al usuario del portal oficial."""
    assert enlace_publico("//otro-sitio.example.com/detalle.cpe", ENDPOINT_NCO) is None


def test_rechaza_un_esquema_que_no_sea_http() -> None:
    """El valor viene de una página externa y el panel lo pinta en un `href`."""
    assert enlace_publico("javascript:alert(1)", ENDPOINT_NCO) is None
    assert enlace_publico("data:text/html,<h1>x</h1>", ENDPOINT_NCO) is None


def test_rechaza_un_fragmento_suelto() -> None:
    """Un `#` no lleva a ningún proceso: devolverlo daría un enlace que no sale de la página."""
    assert enlace_publico("#detalle", ENDPOINT_NCO) is None
