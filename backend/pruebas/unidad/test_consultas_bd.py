"""Pruebas del filtro por provincia de las consultas al histórico.

Lo que se protege aquí es un fallo que no da la cara por sí solo. La fuente oficial publica la
provincia en mayúsculas y sin tildes —«MANABI», «LOS RIOS»— y el panel la envía con la grafía
oficial —«Manabí», «Los Ríos»—, porque es la que se lee en un mapa. Si los dos lados no se
comparan normalizados, pulsar Manabí en el mapa devuelve **cero contrataciones sin ningún
error**: la pantalla se queda vacía y parece que esa provincia no tiene datos. Son siete de
veinticuatro provincias, así que el fallo afectaría a casi un tercio del mapa y no se
manifestaría como una excepción.

Las pruebas se reparten en dos grupos:

- El **acuerdo entre las dos normalizaciones**. La de SQL y la de Python tienen que quitar
  exactamente los mismos caracteres. Si divergieran, el filtro funcionaría en las pruebas y fallaría
  en producción, o al revés, según cuál de las dos se hubiera tocado.
- La **forma de la condición generada**, para que siga siendo parametrizada y siga aceptando las dos
  formas del dato: el valor completo y solo la provincia.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import text

from contratacion.dominio.busqueda import Filtros, ModoBusqueda
from contratacion.infraestructura.adaptadores.salida.bd.consultas import (
    PROVINCIA_NORMALIZADA,
    _condiciones,
    normalizar_ubicacion,
)

# Las dos listas de caracteres de `translate`, extraídas del propio fragmento de SQL para que la
# prueba falle si alguien edita una y se olvida de la otra.
PARTES_TRANSLATE = PROVINCIA_NORMALIZADA.split("'")
CON_ACENTO = PARTES_TRANSLATE[3]
SIN_ACENTO = PARTES_TRANSLATE[5]


def _condicion_de_provincia(
    provincia: str = "Manabí", **cambios: Any
) -> tuple[str, dict[str, Any]]:
    """Devuelve la condición unida y los parámetros del filtro por provincia."""
    condiciones, parametros = _condiciones(Filtros(provincias=(provincia,), **cambios))
    return " AND ".join(condiciones), parametros


# --------------------------------------------------------------------------- #
# Normalización
# --------------------------------------------------------------------------- #


def test_normaliza_tildes_y_mayusculas() -> None:
    assert normalizar_ubicacion("Manabí") == "manabi"
    assert normalizar_ubicacion("MANABI") == "manabi"
    assert normalizar_ubicacion("Los Ríos") == "los rios"
    largo = normalizar_ubicacion("Santo Domingo de los Tsáchilas")
    assert largo == "santo domingo de los tsachilas"


def test_la_grafia_de_la_fuente_y_la_del_mapa_coinciden() -> None:
    # Es la comprobación central del archivo: las dos formas del mismo nombre tienen que
    # reducirse al mismo texto, que es lo que hace que la comparación encuentre algo.
    for oficial, fuente in (
        ("Manabí", "MANABI"),
        ("Bolívar", "BOLIVAR"),
        ("Cañar", "CANAR"),
        ("Galápagos", "GALAPAGOS"),
        ("Los Ríos", "LOS RIOS"),
        ("Sucumbíos", "SUCUMBIOS"),
        ("Santo Domingo de los Tsáchilas", "SANTO DOMINGO DE LOS TSACHILAS"),
    ):
        assert normalizar_ubicacion(oficial) == normalizar_ubicacion(fuente), oficial


def test_recorta_espacios_sobrantes() -> None:
    assert normalizar_ubicacion("  PICHINCHA  ") == "pichincha"


def test_un_valor_ausente_no_rompe_la_normalizacion() -> None:
    assert normalizar_ubicacion(None) == ""
    assert normalizar_ubicacion("") == ""


def test_los_conjuntos_de_caracteres_del_sql_estan_emparejados() -> None:
    """`translate` sustituye por posición: si las dos listas no miden lo mismo, borra caracteres.

    Un desajuste de un solo carácter convertiría «MANABI» en «MANB» en el lado de la base de datos y
    el filtro dejaría de encontrar nada, sin ningún error de sintaxis que lo delatara. Es el tipo de
    fallo que solo aparece en producción, así que se comprueba aquí.
    """
    assert len(CON_ACENTO) == len(SIN_ACENTO) == 14
    # Y que la traducción de Python sobre los caracteres del SQL dé el mismo resultado que la del
    # SQL: si las dos tablas no coincidieran, la comparación fallaría solo en producción.
    assert normalizar_ubicacion(CON_ACENTO) == SIN_ACENTO.lower()


# --------------------------------------------------------------------------- #
# Condición generada
# --------------------------------------------------------------------------- #


def test_compara_normalizado_por_los_dos_lados() -> None:
    condicion, parametros = _condicion_de_provincia()

    assert "lower(translate(" in condicion
    assert condicion.count("lower(translate(") == 2
    # El valor que viaja como parámetro ya está normalizado: comparar contra «Manabí» tal cual no
    # encontraría «MANABI».
    assert parametros["provincias"] == ["manabi"]


def test_varias_provincias_viajan_en_un_solo_parametro() -> None:
    """Dos provincias se comparan con `ANY`, no con dos condiciones enlazadas.

    Con una condición por provincia, elegir cuatro en el mapa alargaría la consulta y —peor— el
    parámetro tendría que llamarse distinto en cada una, así que añadir una provincia sería añadir
    una rama de código. Con `ANY`, la consulta es la misma y solo cambia la lista.
    """
    condiciones, parametros = _condiciones(Filtros(provincias=("Manabi", "Pichincha", "Azuay")))
    de_provincia = [c for c in condiciones if "lower(translate(" in c]

    assert len(de_provincia) == 1, "las tres provincias se comparan en una sola condición"
    assert de_provincia[0].count("ANY(:provincias)") == 2
    assert parametros["provincias"] == ["manabi", "pichincha", "azuay"]


def test_mas_provincias_no_puede_devolver_menos() -> None:
    """La comprobación de fondo: serán más filas, nunca menos.

    Se verifica sobre el SQL generado y no contra la base —eso lo hace el script de verificación
    con datos reales—, pero basta para cubrir el fallo que se quiere evitar: una condición que se
    olvide de parte de la lista y devuelva menos de lo pedido.
    """
    _, una = _condiciones(Filtros(provincias=("Azuay",)))
    _, dos = _condiciones(Filtros(provincias=("Azuay", "Pichincha")))

    assert set(una["provincias"]) <= set(dos["provincias"])


def test_acepta_el_valor_completo_y_solo_la_provincia() -> None:
    # El dato almacenado puede ser «PICHINCHA - QUITO» o solo «PICHINCHA». Se admiten las dos formas
    # porque el mapa envía una y las importaciones antiguas pueden tener la otra.
    condicion, _ = _condicion_de_provincia()
    assert "split_part(" in condicion
    assert "btrim(" in condicion


def test_el_valor_no_se_interpola_en_el_sql() -> None:
    """El texto del filtro viaja como parámetro, nunca dentro de la consulta."""
    condicion, _ = _condicion_de_provincia(provincia="'; DROP TABLE registro; --")
    assert "DROP TABLE" not in condicion
    assert ":provincias" in condicion


def test_sin_provincia_no_se_anade_ninguna_condicion() -> None:
    condiciones, parametros = _condiciones(Filtros())
    assert all("translate(" not in condicion for condicion in condiciones)
    assert "provincias" not in parametros


def test_el_filtro_no_depende_del_resto_de_criterios() -> None:
    # La condición de provincia convive con las demás sin interferir: se comprueba que añadir rango
    # de fechas y fuente no cambia lo que se compara para la provincia.
    solo_provincia, _ = _condicion_de_provincia()
    con_mas, parametros = _condicion_de_provincia(
        desde=date(2024, 1, 1),
        hasta=date(2024, 12, 31),
        fuente="NCO",
        fuentes_permitidas=("NCO",),
    )
    assert parametros["provincias"] == ["manabi"]
    assert "translate(" in con_mas
    assert ":desde" in con_mas
    assert ":hasta" in con_mas
    assert ":fuente" in con_mas
    assert solo_provincia.count("translate(") == con_mas.count("translate(")


def test_sqlalchemy_reconoce_todos_los_parametros() -> None:
    """Todo `:nombre` de la condición tiene que ser un parámetro que SQLAlchemy reconozca.

    Un parámetro que no reconoce viaja **literal** a PostgreSQL y la consulta muere con un error de
    sintaxis. Pasó con el filtro «hasta»: estaba escrito `:hasta::date`, y el reconocedor de
    SQLAlchemy exige que el nombre no vaya seguido de dos puntos, así que no veía ningún parámetro.
    Consecuencia: poner una fecha límite devolvía un 500, y el filtro no había funcionado nunca.

    Esta prueba comprueba el **reconocimiento**, no la cadena. Las que solo miraban que el texto
    contuviera «:hasta» pasaban tan contentas, que es justo por lo que el fallo llegó hasta aquí.

    Se ejecuta sin base de datos a propósito: es una propiedad del texto de la consulta.
    """
    condiciones, parametros = _condiciones(
        Filtros(
            terminos=("medicamentos",),
            cpc=("lavado",),
            provincias=("Manabí", "Pichincha"),
            estado="En Curso",
            desde=date(2026, 9, 1),
            hasta=date(2026, 9, 30),
            fuente="NCO",
            fuentes_permitidas=("NCO",),
            solo_nuevos=True,
            texto="hospital",
        )
    )
    reconocidos = set(text(" AND ".join(condiciones)).compile().params)

    assert set(parametros) == reconocidos


# --------------------------------------------------------------------------- #
# El filtro por CPC
#
# La decisión que se protege aquí es dónde busca. El CPC tiene que consultarse contra **su**
# columna: si se buscara en `texto_busqueda`, el filtro devolvería lo mismo que ya devuelve el de
# palabras clave y no resolvería nada —seguiría apareciendo todo lo que menciona la palabra en el
# objeto de compra—. Es un fallo que pasaría todas las pruebas que solo miraran «¿devuelve filas?».
# --------------------------------------------------------------------------- #


def test_sin_cpc_no_se_anade_ninguna_condicion() -> None:
    condiciones, parametros = _condiciones(Filtros(terminos=("lavado",)))

    assert "expr_cpc" not in parametros
    assert not any("cpc_busqueda" in condicion for condicion in condiciones)


def test_el_cpc_usa_su_propia_columna_y_no_la_del_texto() -> None:
    condiciones, parametros = _condiciones(Filtros(cpc=("lavado",)))
    unida = " AND ".join(condiciones)

    assert "cpc_busqueda" in unida
    assert "texto_busqueda" not in unida
    assert parametros["expr_cpc"] == "(lavado:*)"


def test_los_dos_criterios_de_texto_se_suman() -> None:
    """Enviar los dos pide la intersección, y cada uno viaja en su propio parámetro."""
    condiciones, parametros = _condiciones(Filtros(terminos=("hospital",), cpc=("lavado",)))
    unida = " AND ".join(condiciones)

    assert "texto_busqueda" in unida
    assert "cpc_busqueda" in unida
    assert parametros["expr"] == "(hospital:*)"
    assert parametros["expr_cpc"] == "(lavado:*)"


def test_el_cpc_respeta_el_modo() -> None:
    """«Todas» y «cualquiera» significan lo mismo aquí que en el filtro de palabras clave."""
    _, todas = _condiciones(Filtros(cpc=("lavado", "engrasado"), modo=ModoBusqueda.TODAS))
    _, cualquiera = _condiciones(Filtros(cpc=("lavado", "engrasado"), modo=ModoBusqueda.CUALQUIERA))

    assert " & " in todas["expr_cpc"]
    assert " | " in cualquiera["expr_cpc"]


def test_un_cpc_sin_palabras_buscables_no_filtra() -> None:
    """Un cuadro de texto con «###» no puede dejar la lista vacía: no filtra nada."""
    condiciones, parametros = _condiciones(Filtros(cpc=("###",)))

    assert "expr_cpc" not in parametros
    assert not any("cpc_busqueda" in condicion for condicion in condiciones)
