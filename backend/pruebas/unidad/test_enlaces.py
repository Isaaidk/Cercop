"""Pruebas del enlace al proceso original.

Hay dos caminos y los dos tienen que estar cubiertos. El primero es el de la fuente NCO, que publica
un enlace relativo y del que dependen todas las ínfimas. El segundo es el de OCDS, que **no**
publica ninguna dirección pero sí el `ocid` con el que el portal abre el proceso: componerla es lo
que arregla las «urls que no sirven» que traía el sistema anterior, que usaba otra ruta
—`.../datos-abiertos/proceso/<ocid>`— y esa devuelve 404.

Los demás casos fijan las negativas, que es donde está el riesgo de estas funciones: componer una
dirección con pinta de buena para un dato que no la admite, o dejar pasar un esquema que no sea
http.
"""

from __future__ import annotations

from contratacion.dominio.enlaces import (
    PORTAL_OCDS,
    enlace_del_registro,
    enlace_ocds,
    enlace_publico,
)

# Los valores reales: el `endpoint` de la fuente y un `url` tal y como lo publica el portal.
ENDPOINT_NCO = (
    "https://www.compraspublicas.gob.ec/ProcesoContratacion/compras/NCO/NCORetornaRegistros.cpe"
)
ENDPOINT_OCDS = "https://datosabiertos.compraspublicas.gob.ec/PLATAFORMA/api/search_ocds"
OCID = "ocds-5wno2w-SIE-UTSC-2026-00004-457832"
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


def test_el_ocid_da_la_direccion_del_proceso_en_el_portal() -> None:
    """La ruta del buscador de procedimientos, con el identificador que emite el propio portal.

    Comprobada contra el portal con este `ocid`: abre la ficha con el objeto, la entidad, las etapas
    y el presupuesto. La del sistema anterior —`.../datos-abiertos/proceso/<ocid>`— devuelve 404.
    """
    assert enlace_ocds(OCID) == f"{PORTAL_OCDS}{OCID}"


def test_sin_ocid_no_hay_direccion() -> None:
    assert enlace_ocds(None) is None
    assert enlace_ocds("") is None
    assert enlace_ocds("   ") is None


def test_un_ocid_que_no_es_un_identificador_no_produce_enlace() -> None:
    """Un dato con barra o interrogante compondría una dirección que apunta a otro sitio.

    Es la diferencia entre ofrecer un enlace roto —que quien lo pulsa lee como «este proceso no
    existe»— y no ofrecer ninguno.
    """
    assert enlace_ocds("../../otra/ruta") is None
    assert enlace_ocds("ocds-x?y=1") is None
    assert enlace_ocds("ocds-x#fragmento") is None
    assert enlace_ocds("//otro-sitio.example.com") is None
    assert enlace_ocds("ocds x") is None


def test_lo_que_publica_la_fuente_manda_sobre_lo_compuesto() -> None:
    """Si la fuente publica enlace, se usa el suyo: es el que ella eligió, y seguirá valiendo."""
    elemento = {"enlace": ENLACE_RELATIVO, "ocid": OCID}
    assert enlace_del_registro(elemento, ENDPOINT_NCO) == ESPERADO


def test_el_ocid_rellena_el_hueco_de_la_fuente_que_no_publica_enlace() -> None:
    """OCDS no trae ninguna dirección; trae el identificador con el que el portal la abre."""
    elemento = {"enlace": None, "ocid": OCID}
    assert enlace_del_registro(elemento, ENDPOINT_OCDS) == f"{PORTAL_OCDS}{OCID}"


def test_un_registro_sin_enlace_ni_ocid_se_queda_sin_direccion() -> None:
    """Lo que no se hace nunca es inventar una dirección para un dato que no la admite."""
    assert enlace_del_registro({}, ENDPOINT_NCO) is None
    assert enlace_del_registro({"enlace": None, "ocid": None}, ENDPOINT_NCO) is None
    assert enlace_del_registro({"enlace": "", "ocid": ""}, ENDPOINT_NCO) is None
