"""Pruebas de la vía masiva de OCDS: el mes en un fichero en lugar de diez mil peticiones.

Lo que se comprueba aquí no es que el código corra, sino las tres cosas que pueden romperse en
silencio al sustituir una vía por otra:

1. **El contrato con la tabla de mapeos.** La traducción tiene que entregar exactamente las claves
   que `ocds_mapeos.MAPEOS_POR_DEFECTO` sabe leer. Una clave de menos no falla: deja la columna
   vacía en toda la tabla.
2. **La equivalencia con el listado.** Los dos caminos publican lo mismo con formas distintas, y la
   equivalencia se midió poniendo las dos filas del mismo `ocid` una al lado de la otra contra los
   ficheros reales. Aquí se fija esa medida para que un cambio en la traducción se note.
3. **Los importes.** `mapeo._a_decimal` lee `999.999` como miles; por eso la traducción escribe seis
   decimales. Si alguien «simplifica» pasando el número tal cual, el importe sale mil veces mayor.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zipfile import ZipFile, ZipInfo

import pytest

from contratacion.aplicacion.mapeo import MapeoCampo, convertir
from contratacion.dominio.ingesta import Presupuesto
from contratacion.infraestructura.adaptadores.salida.fuentes import ocds_mapeos
from contratacion.infraestructura.adaptadores.salida.fuentes.ocds_masiva import (
    FuenteOcdsMasiva,
    _importe,
    combinar,
    leer_publicaciones,
    traducir_publicacion,
)

# Una publicación real de septiembre de 2026, recortada a lo que la traducción lee. El listado del
# mismo `ocid` está en LISTADO: es el par que se usó para medir cada equivalencia.
PUBLICACION: dict[str, Any] = {
    "id": "SIE-SNMLCF-2026-004-772102-2026-09-30T19:26:17.004Z-compiled",
    "ocid": "ocds-5wno2w-SIE-SNMLCF-2026-004-772102",
    "date": "2026-09-30T14:30:39-05:00",
    "tag": ["tender", "award"],
    "buyer": {
        "id": "EC-RUC-1760000310001-772102",
        "name": "SERVICIO NACIONAL DE MEDICINA LEGAL Y CIENCIAS FORENSES",
    },
    "parties": [
        {
            "id": "EC-RUC-1760000310001-772102",
            "name": "SERVICIO NACIONAL DE MEDICINA LEGAL Y CIENCIAS FORENSES",
            "roles": ["buyer"],
            "address": {"region": "PICHINCHA", "locality": "QUITO"},
        }
    ],
    "tender": {
        "id": "SIE-SNMLCF-2026-004-772102",
        "title": "SIE-SNMLCF-2026-004-772102",
        "description": "ADQUISICIÓN DE ESTÁNDARES DE CALIBRACIÓN CERTIFICADOS PARA EL LABORATORIO",
        "procurementMethod": "open",
        "procurementMethodDetails": "Subasta Inversa Electrónica",
        "value": {"amount": 13000.0, "currency": "USD"},
    },
    "awards": [
        {
            "id": "8998508-SIE-SNMLCF-2026-004",
            "value": {"amount": 12430.42, "currency": "USD"},
            "suppliers": [
                {
                    "id": "EC-RUC-0992852747001-549562",
                    "name": "JOSE JALIL & HIJOS REPRESENTACIONES Y COMERCIO CIA. LTDA.",
                }
            ],
        }
    ],
    "planning": {"budget": {"amount": 13000.0, "currency": "USD"}},
}

# La fila que el listado paginado publica para ese mismo procedimiento, tal como se midió.
LISTADO: dict[str, Any] = {
    "ocid": "ocds-5wno2w-SIE-SNMLCF-2026-004-772102",
    "date": "2026-09-30T14:30:39-05:00",
    "title": "SIE-SNMLCF-2026-004-772102",
    "internal_type": "Subasta Inversa Electrónica",
    "description": "ADQUISICIÓN DE ESTÁNDARES DE CALIBRACIÓN CERTIFICADOS PARA EL LABORATORIO",
    "buyer": "SERVICIO NACIONAL DE MEDICINA LEGAL Y CIENCIAS FORENSES",
    "region": "PICHINCHA",
    "locality": "QUITO",
    "suppliers": "JOSE JALIL & HIJOS REPRESENTACIONES Y COMERCIO CIA. LTDA.",
    "amount": "12430.420000",
    "method": "open",
    "year": 2026,
    "month": 9,
}


def _regla(canonico: str, tipo: str) -> MapeoCampo:
    return MapeoCampo(
        clave_cruda=canonico, campo_canonico=canonico, tipo_dato=tipo, transformacion={}
    )


def _zip_con(publicaciones: list[dict[str, Any]], destino: Path) -> Path:
    """Escribe un ZIP con la misma forma que sirve el portal: un JSON con una lista de paquetes."""
    ruta = destino / "releases_2026_septiembre.zip"
    with ZipFile(ruta, "w") as comprimido:
        comprimido.writestr(
            ZipInfo("releases_2026_septiembre.json"),
            json.dumps([{"releases": publicaciones}]),
        )
    return ruta


# --------------------------------------------------------------------------- #
# El contrato con la tabla de mapeos
# --------------------------------------------------------------------------- #


def test_la_traduccion_entrega_exactamente_las_claves_que_espera_el_mapeo() -> None:
    """Es la prueba que evita el fallo silencioso: una clave de menos deja una columna vacía.

    No falla nada, no avisa nadie: la tabla de mapeos busca `key` en el crudo, no la encuentra y
    deja el campo sin dato en **todas** las filas. Se comprueba el conjunto completo, no una lista
    de campos «importantes», porque el que se olvide será justo el que nadie mira.
    """
    esperadas = {mapeo["clave_cruda"] for mapeo in ocds_mapeos.MAPEOS_POR_DEFECTO}
    assert set(traducir_publicacion(PUBLICACION)) == esperadas


@pytest.mark.parametrize("clave", sorted(LISTADO))
def test_la_traduccion_da_lo_mismo_que_el_listado(clave: str) -> None:
    """La equivalencia medida contra los ficheros reales, campo a campo.

    `id` no está en la lista a propósito: el listado publica un número interno que el fichero masivo
    no trae, y se usa `tender.id` —el código del proceso—, que significa lo mismo que la etiqueta
    del mapeo. Es la única equivalencia que no es exacta, y por eso está documentada en el módulo.
    """
    assert traducir_publicacion(PUBLICACION)[clave] == LISTADO[clave]


def test_el_identificador_del_proceso_es_el_codigo_y_no_un_numero_interno() -> None:
    assert traducir_publicacion(PUBLICACION)["id"] == "SIE-SNMLCF-2026-004-772102"


def test_el_montos_es_el_adjudicado_y_no_el_presupuestado() -> None:
    """El listado trae como `amount` lo adjudicado; `tender.value` es la estimación previa.

    Confundirlos no rompe nada a la vista y cambia todas las cifras del panel: en el ejemplo son
    12.430,42 adjudicados frente a 13.000 de presupuesto.
    """
    traducido = traducir_publicacion(PUBLICACION)
    assert traducido["amount"] == "12430.420000"
    assert traducido["budget"] == "13000.000000"


# --------------------------------------------------------------------------- #
# Los importes
# --------------------------------------------------------------------------- #


def test_un_importe_se_escribe_con_seis_decimales() -> None:
    assert _importe(12430.42) == "12430.420000"
    assert _importe(0) == "0.000000"
    assert _importe(None) is None
    assert _importe("no es un número") is None


def test_los_seis_decimales_evitan_que_un_importe_se_lea_como_miles() -> None:
    """Aquí está el porqué del formato, y se deja escrito para que nadie lo «simplifique».

    `_a_decimal` tiene que decidir si el punto separa miles o decimales, y con tres dígitos exactos
    elige miles —es el formato ecuatoriano—. Un importe de 999,999 pesos enviado como número se
    guardaría como 999.999. Con seis decimales la ambigüedad desaparece.
    """
    regla = _regla("monto", "moneda")
    assert convertir(_importe(999.999), regla) == 999.999
    # Lo que pasaría si se pasara el número tal cual. No es un deseo: es el motivo del formato.
    assert convertir(999.999, regla) == 999999.0


def test_sin_adjudicacion_no_hay_proveedor_y_el_monto_es_cero() -> None:
    """El listado publica `0.000000` sin adjudicar; se copia para no mover la columna Monto."""
    sin_adjudicacion = {**PUBLICACION, "awards": []}

    traducido = traducir_publicacion(sin_adjudicacion)

    assert traducido["suppliers"] is None
    assert traducido["amount"] == "0.000000"


def test_se_suman_los_proveedores_de_todas_las_adjudicaciones() -> None:
    dos = {
        **PUBLICACION,
        "awards": [
            {"value": {"amount": 100.0}, "suppliers": [{"name": "UNO"}]},
            {"value": {"amount": 250.5}, "suppliers": [{"name": "DOS"}, {"name": "TRES"}]},
        ],
    }

    traducido = traducir_publicacion(dos)

    assert traducido["suppliers"] == "UNO, DOS, TRES"
    assert traducido["amount"] == "250.500000"


# --------------------------------------------------------------------------- #
# Provincia y cantón
# --------------------------------------------------------------------------- #


def test_sin_la_parte_compradora_se_usa_la_primera_direccion_que_haya() -> None:
    """Dejar la provincia vacía es peor que arriesgar la de la entidad que publica."""
    sin_comprador = {
        **PUBLICACION,
        "buyer": {"id": "EC-RUC-QUE-NO-ESTA", "name": "ENTIDAD"},
        "parties": [
            {"id": "OTRA", "name": "X", "address": {"region": "GUAYAS", "locality": "GUAYAQUIL"}}
        ],
    }

    traducido = traducir_publicacion(sin_comprador)

    assert traducido["region"] == "GUAYAS"
    assert traducido["locality"] == "GUAYAQUIL"


def test_el_tipo_de_proceso_no_arrastra_el_convenio() -> None:
    """El fichero publica el convenio entero en los catálogos; el listado, solo el tipo.

    Sin recortarlo, la columna «Tipo de Necesidad» del panel sale con un párrafo —y ese párrafo
    entra además en el texto de búsqueda, así que ensuciaría los resultados de los demás—.
    """
    catalogo = {
        **PUBLICACION,
        "tender": {
            **PUBLICACION["tender"],
            "procurementMethodDetails": (
                "Catálogo electrónico - Compra directa en el convenio CDI-SERCOP-001-2016, "
                "PROVISIÓN DE PRODUCTOS DE CONFECCIÓN TEXTIL"
            ),
        },
    }

    assert traducir_publicacion(catalogo)["internal_type"] == (
        "Catálogo electrónico - Compra directa"
    )


def test_sin_metodo_declarado_se_usa_el_codigo_del_metodo() -> None:
    sin_detalle = {**PUBLICACION, "tender": {k: v for k, v in PUBLICACION["tender"].items()}}
    sin_detalle["tender"].pop("procurementMethodDetails")

    assert traducir_publicacion(sin_detalle)["internal_type"] == "open"


# --------------------------------------------------------------------------- #
# La combinación: el fichero es un delta, no la foto del proceso
# --------------------------------------------------------------------------- #


def test_se_combinan_las_publicaciones_del_mismo_proceso() -> None:
    """Es lo que evita que una publicación borre lo que traía la otra.

    El fichero de cada mes trae las publicaciones de ese mes: la del anuncio lleva el título y la
    descripción, y la de adjudicación —meses después— el proveedor y el monto. Escribirlas seguidas
    tal cual haría que la última dejara el título en blanco, porque en esa publicación no está.
    """
    anuncio = {**PUBLICACION, "awards": []}
    adjudicacion = {
        **PUBLICACION,
        "date": "2026-11-15T09:00:00-05:00",
        "buyer": {"name": PUBLICACION["buyer"]["name"]},
        "parties": [],
        "tender": {},
        "planning": {},
    }

    # `combinar` trabaja sobre filas ya traducidas: es lo que hace el adaptador, y así el paso de
    # traducción sigue teniendo una sola responsabilidad.
    combinadas = combinar([traducir_publicacion(anuncio), traducir_publicacion(adjudicacion)])

    assert len(combinadas) == 1
    fila = combinadas[0]
    assert fila["description"] == PUBLICACION["tender"]["description"]
    assert fila["suppliers"] == "JOSE JALIL & HIJOS REPRESENTACIONES Y COMERCIO CIA. LTDA."
    assert fila["amount"] == "12430.420000"
    # La fecha es la del anuncio: es la de publicación del proceso, que es la que filtra el panel.
    assert fila["date"] == PUBLICACION["date"]


def test_una_publicacion_sin_ocid_se_descarta() -> None:
    """Sin clave natural no hay con qué escribirla; el ciclo la descartaría igual."""
    assert combinar([{"ocid": None, "title": "X"}]) == []


# --------------------------------------------------------------------------- #
# El adaptador
# --------------------------------------------------------------------------- #


async def test_lee_el_zip_y_se_declara_parcial(tmp_path: Path) -> None:
    """Parcial no es un detalle: es lo que impide que la marca de agua avance.

    El fichero es una foto del mes con horas de retraso. Si la vuelta se declarara completa, el
    ciclo siguiente creería estar al día y lo publicado desde la foto no entraría nunca.
    """
    ruta = _zip_con([PUBLICACION], tmp_path)
    fuente = FuenteOcdsMasiva(ruta)

    resultado = await fuente.extraer(datetime(2026, 9, 1, tzinfo=UTC), Presupuesto(limite=10))

    assert len(resultado.registros) == 1
    assert resultado.peticiones == 1
    assert resultado.parcial is True
    assert resultado.registros[0]["ocid"] == PUBLICACION["ocid"]
    # Sin términos: lo que entra por el fichero no lo trajo ninguna palabra clave.
    assert resultado.terminos_completos == ()


async def test_la_marca_de_agua_no_recorta_el_fichero(tmp_path: Path) -> None:
    """El `desde` del ciclo habla del final del listado, no de un fichero de hace meses.

    Aplicarlo aquí descartaría en silencio casi todo el fichero —la marca de agua suele ser de hace
    minutos y las publicaciones son de septiembre— y el ciclo se registraría en verde con cuatro
    filas. La ventana solo se aplica si quien importa la pide al construir la fuente.
    """
    ruta = _zip_con([PUBLICACION], tmp_path)
    fuente = FuenteOcdsMasiva(ruta)

    resultado = await fuente.extraer(
        datetime(2026, 10, 1, 18, 0, tzinfo=UTC), Presupuesto(limite=10)
    )

    assert len(resultado.registros) == 1


async def test_varios_ficheros_se_combinan_en_una_sola_fila(tmp_path: Path) -> None:
    anuncio = tmp_path / "agosto"
    adjudicacion = tmp_path / "septiembre"
    anuncio.mkdir()
    adjudicacion.mkdir()
    ruta_anuncio = _zip_con([{**PUBLICACION, "awards": []}], anuncio)
    ruta_adjudicacion = _zip_con(
        [{**PUBLICACION, "tender": {}, "planning": {}, "parties": []}], adjudicacion
    )
    fuente = FuenteOcdsMasiva([ruta_anuncio, ruta_adjudicacion])

    resultado = await fuente.extraer(datetime(2026, 9, 1, tzinfo=UTC), Presupuesto(limite=10))

    assert len(resultado.registros) == 1
    assert resultado.peticiones == 2
    assert resultado.registros[0]["description"] == PUBLICACION["tender"]["description"]
    assert resultado.registros[0]["suppliers"] is not None


async def test_solo_entra_lo_publicado_dentro_de_la_ventana(tmp_path: Path) -> None:
    """Cortar por la ventana permite reimportar un mes sin volver a escribir lo anterior."""
    antiguo = {**PUBLICACION, "ocid": "ocds-5wno2w-VIEJO", "date": "2026-08-31T10:00:00-05:00"}
    ruta = _zip_con([antiguo, PUBLICACION], tmp_path)
    fuente = FuenteOcdsMasiva(ruta, desde=datetime(2026, 9, 1, tzinfo=UTC))

    resultado = await fuente.extraer(datetime(2026, 8, 1, tzinfo=UTC), Presupuesto(limite=10))

    assert [registro["ocid"] for registro in resultado.registros] == [PUBLICACION["ocid"]]


async def test_sin_presupuesto_no_se_lee_nada(tmp_path: Path) -> None:
    ruta = _zip_con([PUBLICACION], tmp_path)

    resultado = await FuenteOcdsMasiva(ruta).extraer(
        datetime(2026, 9, 1, tzinfo=UTC), Presupuesto(limite=0)
    )

    assert resultado.registros == []
    assert resultado.agoto_presupuesto is True


async def test_una_fecha_ilegible_no_descarta_el_registro(tmp_path: Path) -> None:
    """Descartar por un formato raro perdería un registro; el mapeo ya decide si el dato sirve."""
    raro = {**PUBLICACION, "ocid": "ocds-5wno2w-RARO", "date": "sin fecha"}
    ruta = _zip_con([raro], tmp_path)
    fuente = FuenteOcdsMasiva(ruta, desde=datetime(2026, 9, 1, tzinfo=UTC))

    resultado = await fuente.extraer(datetime(2026, 9, 1, tzinfo=UTC), Presupuesto(limite=10))

    assert len(resultado.registros) == 1


def test_un_zip_sin_json_es_un_error_explicito(tmp_path: Path) -> None:
    """Mejor un error con nombre que un ciclo «correcto» con cero filas.

    Es el fallo que ya costó una vez una ingesta caída sin síntoma: el ciclo se registra en verde y
    la tabla se queda sin escribir. Aquí, si el fichero no trae lo que se espera, se levanta.
    """
    ruta = tmp_path / "vacio.zip"
    with ZipFile(ruta, "w"):
        pass

    with pytest.raises(ValueError, match="no trae ningún JSON"):
        leer_publicaciones(ruta)
