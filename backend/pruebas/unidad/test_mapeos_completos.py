"""Toda clave que publica la API tiene que estar mapeada.

Existe por un fallo real: `seq_tipo_necesidad` (NCO) y cinco claves de OCDS (`id`, `year`,
`month`, `method`, `budget`) no estaban en el catálogo por defecto. Como la ingesta manda lo que
no reconoce a `campo_pendiente`, no se perdía nada de forma visible: esos datos **no llegaban
nunca a la tabla** y el panel los ignoraba. Un campo que falta no da error, y por eso hay que
afirmarlo explícitamente.

Las listas están medidas contra las dos APIs en vivo el 2026-09-28. Si la fuente añade una clave, la
prueba no se entera —no puede adivinar el futuro—, pero si alguien **quita** un mapeo o añade una
clave a la fuente sin mapearla, esto lo delata en cuanto se actualice la lista.
"""

from __future__ import annotations

from contratacion.infraestructura.adaptadores.salida.fuentes import nco_mapeos, ocds_mapeos

# `NCORetornaRegistros.cpe?lot=1` → 20 claves en las 1352 filas.
CLAVES_NCO = {
    "seq_tipo_necesidad",
    "fecha_limite_propuesta",
    "fecha_publicacion",
    "tcom_necesidad_contratacion_id",
    "provincia",
    "canton",
    "objeto_contratacion",
    "razon_social",
    "funcionario_encargado",
    "telefono_encargado",
    "email_encargado",
    "seq_estado",
    "direccion_entrega",
    "codigo_contratacion",
    "estado",
    "tipo_necesidad",
    "url",
    "contacto",
    "valor_unitario",
    "cantidad",
}

# `search_ocds` → 15 claves por resultado. `_termino_buscado` no cuenta: lo añade el adaptador para
# saber por qué término entró cada fila, no viene de la fuente.
CLAVES_OCDS = {
    "id",
    "ocid",
    "year",
    "month",
    "method",
    "internal_type",
    "locality",
    "region",
    "suppliers",
    "buyer",
    "amount",
    "date",
    "title",
    "description",
    "budget",
}

# El identificador del registro lo pone la base de datos. Si un mapeo lo reclamara, la API
# sobrescribiría el uuid del registro con el número de fila de la fuente.
CAMPOS_RESERVADOS = {
    "id",
    "fuente",
    "clave_natural",
    "primera_vez_visto",
    "ultima_vez_visto",
    "es_vigente",
}


def test_nco_mapea_todas_las_claves_de_la_api() -> None:
    mapeadas = {mapeo["clave_cruda"] for mapeo in nco_mapeos.MAPEOS_POR_DEFECTO}
    assert mapeadas == CLAVES_NCO


def test_ocds_mapea_todas_las_claves_de_la_api() -> None:
    mapeadas = {mapeo["clave_cruda"] for mapeo in ocds_mapeos.MAPEOS_POR_DEFECTO}
    assert mapeadas == CLAVES_OCDS


def test_ninguna_clave_canonica_pisa_un_campo_del_registro() -> None:
    for modulo in (nco_mapeos, ocds_mapeos):
        for mapeo in modulo.MAPEOS_POR_DEFECTO:
            assert mapeo["campo_canonico"] not in CAMPOS_RESERVADOS, mapeo["clave_cruda"]


def test_las_claves_crudas_no_se_repiten() -> None:
    for modulo in (nco_mapeos, ocds_mapeos):
        crudas = [mapeo["clave_cruda"] for mapeo in modulo.MAPEOS_POR_DEFECTO]
        assert len(crudas) == len(set(crudas))


def test_los_tipos_de_dato_son_los_que_admite_la_tabla() -> None:
    # La tabla tiene un CHECK con esta lista; un tipo que no esté aquí revienta la ingesta entera.
    admitidos = {"texto", "fecha", "fecha_hora", "numero", "entero", "booleano", "moneda"}
    for modulo in (nco_mapeos, ocds_mapeos):
        for mapeo in modulo.MAPEOS_POR_DEFECTO:
            assert mapeo["tipo_dato"] in admitidos, mapeo["clave_cruda"]
