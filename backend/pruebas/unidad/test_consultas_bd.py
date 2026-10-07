"""Pruebas del filtro por provincia de las consultas al histórico.

Lo que se protege aquí es un fallo que no da la cara por sí solo. La fuente oficial publica la
provincia en mayúsculas y sin tildes —«MANABI», «LOS RIOS»— y el panel la envía con la grafía
oficial —«Manabí», «Los Ríos»—, porque es la que se lee en un mapa. Si los dos lados no se
comparan normalizados, pulsar Manabí en el mapa devuelve **cero contrataciones sin ningún
error**: la pantalla se queda vacía y parece que esa provincia no tiene datos. Son siete de
veinticuatro provincias, así que el fallo afectaría a casi un tercio del mapa y no se
manifestaría como una excepción.

Las pruebas se reparten en cuatro grupos:

- El **acuerdo entre las dos normalizaciones**. La que se escribe en SQL —el relleno de la
  migración— y la que se escribe en Python —la ingesta y el filtro— tienen que quitar exactamente
  los mismos caracteres. Si divergieran, unas filas tendrían una clave que el filtro ya no pide y
  desaparecerían de las búsquedas sin ningún error.
- La **forma de la condición generada**: parametrizada, contra la columna `provincia` y sin tocar
  `datos`. Es la diferencia entre poder usar un índice y recorrer 110.000 filas descomprimiendo un
  `jsonb` de 2 KB en cada una.
- El **acuerdo entre el SQL y el índice** del orden por defecto, que tiene que coincidir con la
  definición que crea la migración 0015. Si divergen, el índice deja de usarse y **no falla nada**:
  cada página vuelve a ordenar 110.000 filas y el único síntoma es que va lenta.
- El **acuerdo entre lo que se escribe y lo que se compara**: la clave que la ingesta guarda en la
  columna tiene que ser la que el filtro pide, y la que devuelve un reparto tiene que poder volver
  al filtro y encontrar sus filas.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import text

from contratacion.dominio.busqueda import Filtros, ModoBusqueda, OrdenBusqueda
from contratacion.dominio.plazos import PATRON_FECHA_ISO
from contratacion.infraestructura.adaptadores.salida.bd.claves import (
    PROVINCIA_NORMALIZADA,
    SIN_CLASIFICAR,
    SIN_PROVINCIA,
    clave_provincia,
    clave_tipo_proceso,
    normalizar_ubicacion,
)
from contratacion.infraestructura.adaptadores.salida.bd.consultas import (
    INDICE_OBJETO,
    ORDENES,
    _condiciones,
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


def test_compara_contra_la_columna_y_no_contra_el_jsonb() -> None:
    """La condición es una igualdad contra `r.provincia`, sin tocar `datos`.

    Es la diferencia entre 8,7 s y unos cientos de milisegundos al pulsar una provincia, y también
    entre poder usar un índice y no poder: una expresión sobre `datos` obliga a leer y descomprimir
    un `jsonb` de 2 KB en cada una de las 110.000 filas del histórico, porque `datos` no está en
    ningún índice y la expresión tampoco sirve como índice de un recuento.

    El valor que viaja como parámetro es la **clave**, la misma que la ingesta escribió en la
    columna al guardar la fila.
    """
    condicion, parametros = _condicion_de_provincia()

    assert "r.provincia = ANY(:provincias)" in condicion
    assert "datos" not in condicion
    assert "translate(" not in condicion
    assert parametros["provincias"] == [clave_provincia("Manabí")] == ["manabi"]


def test_varias_provincias_viajan_en_un_solo_parametro() -> None:
    """Dos provincias se comparan con `ANY`, no con dos condiciones enlazadas.

    Con una condición por provincia, elegir cuatro en el mapa alargaría la consulta y —peor— el
    parámetro tendría que llamarse distinto en cada una, así que añadir una provincia sería añadir
    una rama de código. Con `ANY`, la consulta es la misma y solo cambia la lista.
    """
    condiciones, parametros = _condiciones(Filtros(provincias=("Manabi", "Pichincha", "Azuay")))
    de_provincia = [c for c in condiciones if "r.provincia" in c]

    assert len(de_provincia) == 1, "las tres provincias se comparan en una sola condición"
    assert de_provincia[0].count("ANY(:provincias)") == 1
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
    """«PICHINCHA - QUITO», «Pichincha» y «PICHINCHA» son la misma clave.

    La fuente publica el valor completo y el mapa manda solo la provincia. La tolerancia ya no vive
    en la consulta —que compara una igualdad contra una columna— sino en `clave_provincia`, la
    **misma función** que escribió la columna: es lo que garantiza que las dos formas coincidan, en
    lugar de dos normalizaciones parecidas que se separan en el primer arreglo.
    """
    assert clave_provincia("PICHINCHA - QUITO") == "pichincha"
    assert clave_provincia("Pichincha") == "pichincha"
    assert clave_provincia("  pichincha  ") == "pichincha"
    assert clave_provincia("Pichincha-Cayambe") == "pichincha"
    assert clave_provincia("Manabí") == clave_provincia("MANABI")


def test_el_valor_no_se_interpola_en_el_sql() -> None:
    """El texto del filtro viaja como parámetro, nunca dentro de la consulta."""
    condicion, _ = _condicion_de_provincia(provincia="'; DROP TABLE registro; --")
    assert "DROP TABLE" not in condicion
    assert ":provincias" in condicion


def test_sin_provincia_no_se_anade_ninguna_condicion() -> None:
    condiciones, parametros = _condiciones(Filtros())
    assert all("r.provincia" not in condicion for condicion in condiciones)
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
    assert "r.provincia = ANY(:provincias)" in con_mas
    assert ":desde" in con_mas
    assert ":hasta" in con_mas
    assert ":fuente" in con_mas
    assert solo_provincia.count("r.provincia") == con_mas.count("r.provincia")


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


# --------------------------------------------------------------------------- #
# El filtro por **código** de CPC
#
# Aquí está el defecto que se reportó: «al ingresar un código CPC no salen todos los resultados con
# ese código». La causa principal era de datos —fichas sin leer, con `cpc_busqueda` vacío—, pero
# además un código se comparaba como texto. Ahora un código es un valor y se compara por igualdad
# contra la columna de códigos, que tiene su propio índice.
# --------------------------------------------------------------------------- #


def test_un_codigo_de_cpc_usa_la_columna_de_codigos() -> None:
    """Un código es un valor, no texto: se compara por igualdad contra `cpc_codigos`."""
    condiciones, parametros = _condiciones(Filtros(cpc=("871410032",)))
    unida = " AND ".join(condiciones)

    assert "cpc_codigos @>" in unida
    assert parametros["cpc_codigos"] == ["871410032"]
    assert "expr_cpc" not in parametros


def test_con_cualquiera_los_codigos_se_solapan() -> None:
    """«Cualquiera» con dos códigos es «alguna de las dos clasificaciones», no «las dos»."""
    condiciones, parametros = _condiciones(
        Filtros(cpc=("871410032", "431510128"), modo=ModoBusqueda.CUALQUIERA)
    )

    assert "cpc_codigos &&" in " AND ".join(condiciones)
    assert parametros["cpc_codigos"] == ["871410032", "431510128"]


def test_un_codigo_y_una_descripcion_se_combinan() -> None:
    """Los dos tipos de término conviven: cada uno por su índice y los dos se exigen."""
    condiciones, parametros = _condiciones(Filtros(cpc=("871410032", "lavado")))
    unida = " AND ".join(condiciones)

    assert "cpc_codigos @>" in unida
    assert "cpc_busqueda" in unida
    assert parametros["cpc_codigos"] == ["871410032"]
    assert parametros["expr_cpc"] == "(lavado:*)"


def test_solo_cpc_no_exige_las_palabras_clave() -> None:
    """El interruptor existe para esto: buscar por clasificación sin que las palabras recorten."""
    condiciones, parametros = _condiciones(
        Filtros(terminos=("hospital",), cpc=("871410032",), solo_cpc=True)
    )
    unida = " AND ".join(condiciones)

    assert "cpc_codigos @>" in unida
    assert "texto_busqueda" not in unida
    assert "expr" not in parametros


def test_sin_solo_cpc_las_palabras_clave_siguen_exigiendose() -> None:
    """El interruptor cambia algo: apagado, los dos criterios se suman como siempre."""
    condiciones, _ = _condiciones(Filtros(terminos=("hospital",), cpc=("871410032",)))

    assert "texto_busqueda" in " AND ".join(condiciones)


# --------------------------------------------------------------------------- #
# El código del proceso se busca por **fragmento**
#
# Esta prueba existe para que una optimización futura no rompa el filtro sin querer. Se intentó
# indexarlo con un btree de prefijo y hubo que dar marcha atrás: un btree solo resuelve «empieza
# por», y con «26-00053» —los últimos dígitos de un NIC, que es como lo recuerda la gente— no
# encontraría nada, porque los códigos empiezan por `NIC-`. El fragmento acota mejor y se paga con
# un recorrido completo, que es una decisión deliberada y no un descuido.
# --------------------------------------------------------------------------- #


def test_el_codigo_se_busca_por_fragmento() -> None:
    """Un fragmento del código —no solo su principio— tiene que encontrar la fila."""
    condiciones, parametros = _condiciones(Filtros(codigo="26-00053"))
    unida = " AND ".join(condiciones)

    assert "ILIKE :codigo" in unida
    assert parametros["codigo"] == "%26-00053%"


def test_los_comodines_del_codigo_van_escapados() -> None:
    """Un `%` escrito por el usuario no puede convertirse en «cualquier cosa»."""
    _, parametros = _condiciones(Filtros(codigo="NIC%2026"))

    assert parametros["codigo"] == "%NIC\\%2026%"


# --------------------------------------------------------------------------- #
# El filtro por descripción del producto
#
# Busca en el objeto de compra **y solo ahí**. Lo que se protege es dónde busca: si fuera contra
# `texto_busqueda` devolvería lo mismo que las palabras clave —todo lo que menciona la palabra,
# incluida la entidad o el código— y el filtro no serviría para lo que se le pide.
# --------------------------------------------------------------------------- #


def test_la_descripcion_busca_solo_en_el_objeto_de_compra() -> None:
    condiciones, parametros = _condiciones(Filtros(descripcion=("equipo de computo",)))
    unida = " AND ".join(condiciones)

    assert INDICE_OBJETO in unida
    assert "objeto_compra" in unida
    assert "texto_busqueda" not in unida
    # Un término con espacios sigue siendo **un** término: sus palabras se exigen todas.
    assert parametros["expr_descripcion"] == "(equipo:* & de:* & computo:*)"


def test_la_descripcion_respeta_el_modo() -> None:
    """«Todas» exige cada término y «cualquiera» basta con uno, igual que en las palabras clave."""
    _, todas = _condiciones(Filtros(descripcion=("mesas", "sillas")))
    _, cualquiera = _condiciones(
        Filtros(descripcion=("mesas", "sillas"), modo=ModoBusqueda.CUALQUIERA)
    )

    assert todas["expr_descripcion"] == "(mesas:*) & (sillas:*)"
    assert cualquiera["expr_descripcion"] == "(mesas:*) | (sillas:*)"


def test_sin_descripcion_no_se_anade_ninguna_condicion() -> None:
    condiciones, parametros = _condiciones(Filtros(terminos=("obras",)))

    assert all("objeto_compra" not in condicion for condicion in condiciones)
    assert "expr_descripcion" not in parametros


def test_la_descripcion_no_la_silencia_solo_cpc() -> None:
    """«Solo CPC» deja de exigir las **palabras clave**, no una descripción escrita a mano.

    Son cosas distintas: las palabras clave son una suscripción de fondo que se mantiene puesta
    durante meses, y la descripción es una pregunta que se hace en ese momento. Callarla al buscar
    por clasificación devolvería filas que nadie pidió.
    """
    condiciones, _ = _condiciones(
        Filtros(cpc=("871410032",), solo_cpc=True, descripcion=("computo",), terminos=("obras",))
    )
    unida = " AND ".join(condiciones)

    assert "objeto_compra" in unida
    assert "texto_busqueda" not in unida
    assert "cpc_codigos" in unida


def test_el_indice_de_la_descripcion_es_el_de_la_consulta() -> None:
    """El texto del índice y el de la condición tienen que ser el mismo, o el índice no se usa.

    Sin la coincidencia exacta no hay ningún error: la búsqueda pasa de milisegundos a recorrer el
    histórico entero calculando un `tsvector` por fila —unos 10 s— y el único síntoma es que va
    lenta. Esta prueba es lo único que avisa.
    """
    migracion = _sin_huecos(
        RUTA_MIGRACION_DESCRIPCION.read_text(encoding="utf-8").replace("{TILDES}", TILDES_SQL)
    )

    # El índice nombra la columna sin el alias de la tabla: `datos`, no `r.datos`.
    assert _sin_huecos(INDICE_OBJETO).replace("r.", "") in migracion


# --------------------------------------------------------------------------- #
# El SQL y los índices tienen que decir lo mismo
#
# Estas pruebas no comprueban un resultado: comprueban que dos textos siguen coincidiendo. Es lo
# único que hay entre un índice que se usa y uno que ya no, porque cuando dejan de coincidir no hay
# error, ni aviso, ni fila de más: solo una consulta que vuelve a recorrer 110.000 filas.
# --------------------------------------------------------------------------- #

RUTA_MIGRACION_ORDEN = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0015_indices_agregados.py"
)


# --------------------------------------------------------------------------- #
# El plazo de proformas: de texto dentro del JSON a columna con índice parcial
# --------------------------------------------------------------------------- #


def test_el_plazo_se_filtra_por_la_columna_y_no_por_el_texto() -> None:
    """Un `CAST` sobre `datos` no lo resuelve ningún índice: recorre y descomprime las 111.000.

    No falla nada al hacerlo mal —devuelve el resultado correcto—, así que lo único que lo detecta
    es esta comprobación.
    """
    condiciones, parametros = _condiciones(Filtros(solo_con_plazo=True))
    unida = " AND ".join(condiciones)

    assert "plazo_proformas_en" in unida
    assert "fecha_limite_proformas" not in unida
    assert parametros == {}


def test_sin_plazo_no_se_anade_ninguna_condicion() -> None:
    condiciones, _ = _condiciones(Filtros())
    assert not any("plazo_proformas_en" in condicion for condicion in condiciones)


def test_el_patron_de_la_migracion_es_el_del_dominio() -> None:
    """El relleno de la migración y la escritura de la ingesta tienen que aceptar lo mismo.

    Si el de la migración fuera más estrecho, las filas que ya estaban se quedarían sin plazo y
    desaparecerían del filtro «solo con plazo»; si fuera más ancho, entraría en la columna un texto
    del que dependen un filtro y un borrado. Ninguna de las dos cosas da un error.
    """
    migracion = _migracion_de_la_retencion()
    encontrado = re.search(r'^PATRON = r"(.*)"$', migracion, re.MULTILINE)

    assert encontrado is not None, "la migración declara el patrón como constante"
    assert encontrado.group(1) == PATRON_FECHA_ISO


def test_el_indice_del_plazo_es_parcial_sobre_la_columna() -> None:
    """Sin el `WHERE`, el índice cargaría las 104.000 filas de OCDS que nunca tienen plazo."""
    migracion = _sin_huecos(_migracion_de_la_retencion())

    assert "ix_registro_plazo_proformas ON registro (plazo_proformas_en)" in migracion
    assert "WHERE plazo_proformas_en IS NOT NULL" in migracion


def _migracion_de_la_retencion() -> str:
    """El texto de la migración que añade la columna del plazo."""
    ruta = Path(__file__).resolve().parents[2] / "alembic" / "versions"
    return (ruta / "0021_plazo_proformas.py").read_text(encoding="utf-8")


def _sin_huecos(texto: str) -> str:
    """Compara dos SQL escritos con saltos de línea distintos, sin tocar los espacios que cuentan.

    Solo se quitan los huecos que existían por partir la línea —los de junto a un paréntesis—, que
    es la única diferencia que puede haber entre la expresión de una constante de Python y la misma
    escrita a mano en el SQL de una migración. Los espacios de dentro de los literales se respetan.
    """
    texto = re.sub(r"\s+", " ", texto)
    texto = re.sub(r"\(\s+", "(", texto)
    return re.sub(r"\s+\)", ")", texto)


def _marcha_atras(clausula: str) -> str:
    """La cláusula de orden que recorre el mismo índice al revés.

    Un índice de varias columnas se puede leer en los dos sentidos, pero el segundo sentido no es
    «lo mismo con el signo cambiado»: al invertir el recorrido se invierte el sentido de **todas**
    las columnas, y los nulos pasan de ir al final a ir al principio. Por eso el desempate lleva
    `DESC` cuando la fecha lleva `ASC`.
    """
    piezas: list[str] = []
    for trozo in clausula.split(", "):
        if " DESC" in trozo:
            trozo = trozo.replace(" DESC", " ASC")
        elif " ASC" in trozo:
            trozo = trozo.replace(" ASC", " DESC")
        else:
            trozo = f"{trozo} DESC"
        if "NULLS LAST" in trozo:
            trozo = trozo.replace("NULLS LAST", "NULLS FIRST")
        elif "NULLS FIRST" in trozo:
            trozo = trozo.replace("NULLS FIRST", "NULLS LAST")
        elif trozo.endswith(" ASC"):
            # `ASC` es lo que ya dice una columna sin sentido declarado, así que la forma canónica
            # no lo escribe: `r.id` y `r.id ASC` son la misma cláusula.
            trozo = trozo[: -len(" ASC")]
        piezas.append(trozo)
    return ", ".join(piezas)


def test_el_orden_mas_antiguo_es_la_marcha_atras_del_mas_reciente() -> None:
    """Los dos órdenes por fecha caben en un solo índice, y eso exige que sean reversos exactos.

    Si el desempate de «más antiguos» volviera a ser `r.id` —una corrección que parece inofensiva—
    el índice dejaría de servir para ese orden y cada página volvería a ordenar el histórico
    entero. Medido: 10,4 s por página.
    """
    recientes = ORDENES[OrdenBusqueda.RECIENTES]
    antiguos = ORDENES[OrdenBusqueda.ANTIGUOS]

    assert _marcha_atras(recientes) == antiguos
    assert _marcha_atras(antiguos) == recientes


def test_el_orden_por_defecto_declara_los_nulos_como_el_indice() -> None:
    """`NULLS LAST` no es un adorno: es la diferencia entre usar el índice y ordenar 110.000 filas.

    En PostgreSQL `DESC` implica `NULLS FIRST`, así que un índice `(fecha_publicacion DESC, id)` no
    sirve para `ORDER BY fecha_publicacion DESC NULLS LAST`. Aquí se comprueba que la cláusula
    declara el sentido de los nulos y que la migración que construye el índice lo declara igual.
    """
    migracion = _sin_huecos(RUTA_MIGRACION_ORDEN.read_text(encoding="utf-8"))

    assert "DESC NULLS LAST" in ORDENES[OrdenBusqueda.RECIENTES]
    assert "fecha_publicacion DESC NULLS LAST, id" in migracion


# --------------------------------------------------------------------------- #
# La clave que se escribe y la que se compara tienen que ser la misma
#
# La clave vive ahora en una columna: la escribe la ingesta al guardar cada fila y la comparan las
# consultas al filtrar. Si las dos reglas se separaran, unas filas se encontrarían y otras no, y el
# reparto dibujaría barras que al pulsarlas no traen nada, sin ningún error que lo delate.
# --------------------------------------------------------------------------- #

RUTA_MIGRACION_CLAVES = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "0017_provincia_y_tipo_proceso.py"
)

RUTA_MIGRACION_DESCRIPCION = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0020_indice_descripcion.py"
)

# La migración escribe la tabla de tildes como un marcador (`{TILDES}`) para no repetirla dentro del
# mismo archivo, así que aquí se sustituye por la que usa Python. La sustitución es, de paso, una
# comprobación: si la migración cambiara de tabla de tildes, el texto dejaría de encontrarse.
TILDES_SQL = f"'{CON_ACENTO}', '{SIN_ACENTO}'"


def test_las_claves_del_relleno_son_las_de_la_ingesta() -> None:
    """El relleno de la migración y la ingesta tienen que escribir exactamente la misma clave.

    La migración rellena 110.000 filas con SQL escrito a mano y la ingesta escribe con Python. Si
    las dos formas se separan —una tilde que una quita y la otra no, un `btrim` que falta—, la mitad
    del histórico quedaría con una clave que el filtro ya no pide y esas filas desaparecerían de las
    búsquedas por provincia **sin ningún error**. Esta prueba es lo único que avisa.
    """
    migracion = _sin_huecos(
        RUTA_MIGRACION_CLAVES.read_text(encoding="utf-8").replace("{TILDES}", TILDES_SQL)
    )
    provincia_esperada = _sin_huecos(
        "COALESCE(NULLIF("
        + PROVINCIA_NORMALIZADA.format(columna="btrim(split_part(datos ->> 'provincia', '-', 1))")
        + ", ''), 'sin provincia')"
    )

    assert provincia_esperada in migracion
    assert (
        _sin_huecos("COALESCE(NULLIF(btrim(datos ->> 'tipo_proceso'), ''), 'sin clasificar')")
        in migracion
    )


def test_la_clave_que_pide_el_filtro_es_la_que_escribe_la_ingesta() -> None:
    """El mismo valor, dicho por la fuente y por el panel, da la misma clave en los dos lados."""
    _, del_filtro = _condiciones(Filtros(provincias=("Manabí",)))

    assert del_filtro["provincias"] == [clave_provincia("MANABI")]


def test_la_barra_sin_clasificar_encuentra_sus_filas() -> None:
    """Pulsar «sin clasificar» en el reparto tiene que traer esas filas, no cero.

    El reparto siempre las contó —son las ínfimas, que no publican el tipo de proceso—, pero el
    filtro comparaba contra el texto crudo de `datos`, que en ellas está vacío: la barra se podía
    pulsar y la tabla se quedaba vacía. Un gráfico que dice «10.110 sin clasificar» y no puede
    enseñarlas es peor que no ofrecerlas.
    """
    _, parametros = _condiciones(Filtros(tipo_proceso="sin clasificar"))

    assert parametros["tipo_proceso"] == SIN_CLASIFICAR
    assert parametros["tipo_proceso"] == clave_tipo_proceso(None)
    assert parametros["tipo_proceso"] == clave_tipo_proceso("   ")


def test_la_barra_del_reparto_vuelve_al_filtro_y_encuentra_sus_filas() -> None:
    """La clave de un reparto, devuelta al filtro, tiene que encontrar esas mismas filas."""
    barra = "Subasta Inversa Electrónica"
    _, parametros = _condiciones(Filtros(tipo_proceso=barra))

    # No se normalizan mayúsculas ni tildes a propósito: la barra y el filtro coinciden carácter a
    # carácter, que es lo que hace que pulsarla devuelva exactamente esa fila.
    assert parametros["tipo_proceso"] == clave_tipo_proceso(barra)
    assert parametros["tipo_proceso"] == barra


def test_un_valor_ausente_tiene_su_clave_y_no_deja_la_columna_vacia() -> None:
    """Las dos claves existen aunque la fuente no publique el dato.

    Es lo que permite que las columnas sean `NOT NULL` —y por tanto que ninguna fila se quede fuera
    de un filtro por olvidarse alguien de escribirla— y que el reparto tenga su barra para lo que no
    se sabe ubicar.
    """
    assert clave_provincia(None) == SIN_PROVINCIA
    assert clave_provincia("") == SIN_PROVINCIA
    assert clave_provincia("   ") == SIN_PROVINCIA
    assert clave_tipo_proceso(None) == SIN_CLASIFICAR
    assert clave_tipo_proceso("") == SIN_CLASIFICAR
    assert clave_tipo_proceso("  En Curso  ") == "En Curso"
