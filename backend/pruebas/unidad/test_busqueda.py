"""Pruebas de las reglas de búsqueda.

Lo que se comprueba aquí no es la consulta SQL, sino las decisiones que la gobiernan: qué significa
«todas», cuándo dos búsquedas son la misma, qué términos son aceptables y qué páginas se admiten.

Dos pruebas merecen atención especial porque protegen fallos que no dan la cara solos:

- `test_un_termino_con_operadores_no_puede_alterar_la_consulta` — los símbolos `&`, `|` y `*`
  tienen significado en el motor de búsqueda. Si un término pudiera colarlos, dejaría de ser una
  búsqueda y pasaría a ser otra consulta.
- `test_coincide_por_prefijo_de_palabra` — la coincidencia en memoria debe decir lo mismo que la
  base de datos. Si divergieran, la misma consulta devolvería resultados distintos según tuviera el
  caché delante o no, que es el peor fallo posible en este diseño.
"""

from __future__ import annotations

from datetime import date

import pytest

from contratacion.dominio.busqueda import (
    Categoria,
    Filtros,
    ModoBusqueda,
    OrdenBusqueda,
    PaginaResultados,
    clave_generacion,
    clave_resultados,
    codigo_cercoapp,
    coincide,
    es_codigo_cpc,
    es_identificador,
    expresion_busqueda,
    expresion_de_termino,
    huella_filtros,
    limitar_elementos,
    normalizar_provincias,
    normalizar_terminos,
    palabras_de,
)
from contratacion.dominio.errores import DatoInvalido

# --------------------------------------------------------------------------- #
# Normalización de términos
# --------------------------------------------------------------------------- #


def test_normaliza_acentos_mayusculas_y_espacios() -> None:
    assert normalizar_terminos(["  GESTIÓN   de Obras "]) == ("de gestion obras",)


def test_el_orden_de_las_palabras_no_crea_dos_consultas() -> None:
    # El término se evalúa como una conjunción, así que el orden no cambia lo que busca.
    assert normalizar_terminos(["obras viales"]) == normalizar_terminos(["viales obras"])


def test_descarta_terminos_demasiado_cortos() -> None:
    assert normalizar_terminos(["ab", "obras"]) == ("obras",)


def test_descarta_terminos_sin_palabras_buscables() -> None:
    # Sin esto, el término llegaría al motor como una expresión vacía.
    assert normalizar_terminos(["###", "---"]) == ()


def test_separa_listas_pegadas_por_el_usuario() -> None:
    assert normalizar_terminos(["obras, viales; puentes"]) == ("obras", "puentes", "viales")


def test_palabras_de_quita_los_operadores_de_busqueda() -> None:
    assert palabras_de("obras & viales | puentes:*") == ("obras", "viales", "puentes")


# --------------------------------------------------------------------------- #
# Expresión de búsqueda
# --------------------------------------------------------------------------- #


def test_un_termino_con_operadores_no_puede_alterar_la_consulta() -> None:
    """Un término con símbolos del motor no debe cambiar el significado de la consulta.

    «obras|viales» es, para una persona, un texto raro; para el motor de búsqueda sería una
    disyunción. Al limpiar las palabras, se convierte en la conjunción que se pretendía.
    """
    expresion = expresion_busqueda(["obras|viales"], ModoBusqueda.TODAS)
    assert expresion == "(obras:* & viales:*)"


def test_expresion_usa_prefijos_para_que_vial_encuentre_viales() -> None:
    assert expresion_busqueda(["vial"], ModoBusqueda.TODAS) == "(vial:*)"


def test_expresion_combina_con_y_en_modo_todas() -> None:
    assert expresion_busqueda(["obras", "puentes"], ModoBusqueda.TODAS) == "(obras:*) & (puentes:*)"


def test_expresion_combina_con_o_en_modo_cualquiera() -> None:
    expresion = expresion_busqueda(["obras", "puentes"], ModoBusqueda.CUALQUIERA)
    assert expresion == "(obras:*) | (puentes:*)"


def test_expresion_es_nula_sin_terminos() -> None:
    assert expresion_busqueda([], ModoBusqueda.TODAS) is None


def test_expresion_de_un_termino_es_la_pieza_suelta() -> None:
    """La pieza de un término tiene que ser exactamente la que arma la expresión completa.

    Es lo que impide que las dos versiones se separen: la búsqueda que trata los términos uno a uno
    —la de los códigos de proceso— compone con esta función, y la de siempre une las mismas piezas.
    """
    assert expresion_de_termino("obras viales") == "(obras:* & viales:*)"
    assert expresion_de_termino("###") is None
    assert expresion_busqueda(["obras viales", "puentes"], ModoBusqueda.TODAS) == (
        "(obras:* & viales:*) & (puentes:*)"
    )


# --------------------------------------------------------------------------- #
# Códigos de proceso
#
# Un término con esta forma se busca también contra el campo del código, porque el analizador de
# PostgreSQL guarda el guion dentro del número (`-0038`) y la búsqueda por prefijos no alcanza ese
# token. Reconocerlo es lo que hace que pegar un código encuentre la fila.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "termino",
    [
        "SIE-UTA-2026-0038-3205",
        "SIE-UTA-2026-0038",
        "NIC-1768120280001-2022-00003",
        "sie-uta-2026-0038-3205",
    ],
)
def test_un_codigo_de_proceso_se_reconoce(termino: str) -> None:
    assert es_identificador(termino)


@pytest.mark.parametrize(
    "termino",
    [
        "medicamentos",
        "obra-2026",
        "SIE-UTA",
        "2026-0038",
        "",
    ],
)
def test_una_palabra_o_un_termino_corto_no_es_un_codigo(termino: str) -> None:
    """El reconocimiento se pide estrecho a propósito: solo **añade** una vía de coincidencia."""
    assert not es_identificador(termino)


# --------------------------------------------------------------------------- #
# El código sin el prefijo del portal y sin el consecutivo interno
#
# Es lo que se muestra como «Código CercoApp» y lo que se copia para volver a buscar el proceso. Lo
# que se protege es que la limpieza no toque lo que no debe: 81.688 códigos de oferta son texto con
# un solo guion («Orden de compra CE-20260003118811»), 101.799 filas ya vienen sin prefijo, y en las
# ínfimas el último grupo es el secuencial de la contratación y no un sobrante.
# --------------------------------------------------------------------------- #


def test_en_las_ofertas_quita_el_consecutivo_del_portal() -> None:
    """El caso que se pidió: el portal añade un grupo detrás y el buscador no lo necesita."""
    assert codigo_cercoapp("SIE-UNESUM-2026-0025-136003", categoria=Categoria.OFERTAS) == (
        "SIE-UNESUM-2026-0025"
    )


def test_quita_el_prefijo_y_el_consecutivo_a_la_vez() -> None:
    assert codigo_cercoapp(
        "ocds-5wno2w-LICO-EPMMOP-2026-036-741823", categoria=Categoria.OFERTAS
    ) == ("LICO-EPMMOP-2026-036")


def test_en_las_infimas_el_nic_se_queda_entero() -> None:
    """El NIC no lleva consecutivo sobrante: su último grupo es el secuencial de la contratación.

    Recortarlo daría `NIC-0660821210001-2026`, que no identifica una contratación sino todas las de
    esa entidad ese año.
    """
    nic = "NIC-0660821210001-2026-00062"

    assert codigo_cercoapp(nic, categoria=Categoria.INFIMAS) == nic


def test_un_codigo_con_texto_no_se_toca() -> None:
    """En la columna hay valores que no son códigos, y recortarlos sería inventar el dato."""
    texto = "Orden de compra CE-20260003118811"

    assert codigo_cercoapp(texto, categoria=Categoria.OFERTAS) == texto


def test_un_grupo_con_letras_no_se_recorta() -> None:
    """Solo se quita el último grupo si es numérico: `ABC` forma parte del código."""
    assert codigo_cercoapp("SIE-UTA-2026-ABC", categoria=Categoria.OFERTAS) == "SIE-UTA-2026-ABC"


def test_un_codigo_de_tres_grupos_no_se_recorta() -> None:
    """Solo se recorta cuando el código tiene un grupo **de más**.

    `RE-PUHAIAM2026-002` son tres grupos —`RE`, `PUHAIAM2026` y el secuencial— y quitarle el último
    daría `RE-PUHAIAM2026`, que ya no dice qué contratación es.
    """
    assert codigo_cercoapp("RE-PUHAIAM2026-002", categoria=Categoria.OFERTAS) == (
        "RE-PUHAIAM2026-002"
    )


def test_sin_categoria_solo_quita_el_prefijo() -> None:
    """La categoría es la que autoriza el recorte; sin ella, el código se respeta."""
    assert codigo_cercoapp("SIE-UTA-2026-0038-3205") == "SIE-UTA-2026-0038-3205"
    assert codigo_cercoapp("ocds-5wno2w-SIE-UTA-2026-0038-3205") == "SIE-UTA-2026-0038-3205"


@pytest.mark.parametrize("valor", [None, "", "   "])
def test_sin_codigo_no_hay_codigo(valor: str | None) -> None:
    assert codigo_cercoapp(valor, categoria=Categoria.OFERTAS) is None


def test_un_ocds_sin_el_tercer_grupo_no_se_recorta() -> None:
    """El prefijo son dos grupos; `ocds-a` a secas es el código entero y no se le quita nada."""
    assert codigo_cercoapp("ocds-5wno2w") == "ocds-5wno2w"


def test_lo_que_devuelve_es_buscable() -> None:
    """El valor que se muestra tiene que ser el que se puede pegar, y las dos formas lo son."""
    recortado = codigo_cercoapp("ocds-5wno2w-SIE-UTA-2026-0038-3205", categoria=Categoria.OFERTAS)

    assert recortado == "SIE-UTA-2026-0038"
    assert es_identificador(recortado or "")


# --------------------------------------------------------------------------- #
# Coincidencia en memoria
# --------------------------------------------------------------------------- #


def test_coincide_en_modo_todas_exige_todos_los_terminos() -> None:
    texto = "construccion de obras viales en azuay"
    assert coincide(texto, ["obras", "viales"], ModoBusqueda.TODAS)
    assert not coincide(texto, ["obras", "puentes"], ModoBusqueda.TODAS)


def test_coincide_en_modo_cualquiera_basta_con_uno() -> None:
    texto = "construccion de obras viales"
    assert coincide(texto, ["puentes", "viales"], ModoBusqueda.CUALQUIERA)


def test_coincide_por_prefijo_de_palabra() -> None:
    """«vial» encuentra «viales», pero «oral» no encuentra «moral».

    Es la diferencia entre comparar por prefijo de palabra y comparar por subcadena. Sin esta
    distinción, buscar «oral» devolvería expedientes de «moral» y el usuario perdería la confianza
    en los resultados.
    """
    assert coincide("obras viales", ["vial"], ModoBusqueda.TODAS)
    assert not coincide("garantia moral", ["oral"], ModoBusqueda.TODAS)


def test_coincide_sin_terminos_acepta_cualquier_texto() -> None:
    assert coincide("lo que sea", [], ModoBusqueda.TODAS)


# --------------------------------------------------------------------------- #
# Filtros: validación y huella
# --------------------------------------------------------------------------- #


def test_rechaza_pagina_menor_que_uno() -> None:
    with pytest.raises(DatoInvalido):
        Filtros(pagina=0).validado()


def test_rechaza_pagina_demasiado_profunda() -> None:
    with pytest.raises(DatoInvalido):
        Filtros(pagina=10_000).validado()


def test_rechaza_tamano_de_pagina_excesivo() -> None:
    with pytest.raises(DatoInvalido):
        Filtros(tamano=5_000).validado()


def test_rechaza_rango_de_fechas_invertido() -> None:
    with pytest.raises(DatoInvalido):
        Filtros(desde=date(2026, 12, 1), hasta=date(2026, 1, 1)).validado()


def test_calcula_el_desplazamiento_de_la_pagina() -> None:
    assert Filtros(pagina=3, tamano=25).desplazamiento == 50


def test_la_huella_ignora_el_orden_de_los_terminos() -> None:
    uno = Filtros(terminos=normalizar_terminos(["obras", "viales"]))
    otro = Filtros(terminos=normalizar_terminos(["viales", "obras"]))
    assert huella_filtros(uno) == huella_filtros(otro)


def test_la_huella_cambia_al_cambiar_un_filtro() -> None:
    base = Filtros(terminos=("obras",))
    con_provincia = Filtros(terminos=("obras",), provincias=("Azuay",))
    assert huella_filtros(base) != huella_filtros(con_provincia)


def test_la_huella_distingue_la_descripcion_de_los_terminos() -> None:
    """Buscar «obras» en toda la convocatoria no es buscarlo en la descripción del producto.

    Comparten la forma —una lista de términos y el mismo modo— y por eso es fácil confundirlos: si
    los dos acabaran en la misma clave de la huella, dos consultas distintas devolverían el
    resultado de la primera, sin ningún error que lo delate.
    """
    como_termino = Filtros(terminos=("obras",))
    como_descripcion = Filtros(descripcion=("obras",))

    assert huella_filtros(como_termino) != huella_filtros(como_descripcion)


def test_la_huella_ignora_el_orden_de_la_descripcion() -> None:
    uno = Filtros(descripcion=normalizar_terminos(["pantallas", "teclados"]))
    otro = Filtros(descripcion=normalizar_terminos(["teclados", "pantallas"]))

    assert huella_filtros(uno) == huella_filtros(otro)


def test_la_descripcion_si_se_cachea() -> None:
    """Es deliberada y se repite, como el CPC: no es una caja de búsqueda «mientras se escribe».

    `texto` y `codigo` quedan fuera del caché porque su espacio de combinaciones es ilimitado. La
    descripción del producto no: describe lo que esa empresa compra siempre, así que dos personas
    que buscan lo mismo comparten entrada. Si algún día se consultara al teclear, habría que
    sacarla, y por eso queda escrito.
    """
    assert Filtros(descripcion=("equipo de computo",)).cacheable


def test_el_resumen_menciona_la_descripcion() -> None:
    assert "descripcion=equipos" in Filtros(descripcion=("equipos",)).resumen()


def test_la_huella_ignora_el_orden_de_las_provincias() -> None:
    """El mapa se pulsa en el orden que sea, y el resultado no depende de él.

    Sin esto, «Azuay y Pichincha» y «Pichincha y Azuay» ocuparían dos entradas de caché para
    devolver exactamente la misma página, y el acierto se perdería justo cuando más se usa.
    """
    una = Filtros(provincias=normalizar_provincias(["Azuay", "Pichincha"]))
    otra = Filtros(provincias=normalizar_provincias(["Pichincha", "Azuay"]))
    assert huella_filtros(una) == huella_filtros(otra)


def test_dos_provincias_no_comparten_huella_con_una() -> None:
    """El fallo de caché más caro aquí: servir la página de una provincia al que pidió dos."""
    una = Filtros(provincias=("Azuay",))
    dos = Filtros(provincias=normalizar_provincias(["Azuay", "Pichincha"]))
    assert huella_filtros(una) != huella_filtros(dos)


def test_la_huella_incluye_la_pagina() -> None:
    assert huella_filtros(Filtros(pagina=1)) != huella_filtros(Filtros(pagina=2))


def test_la_huella_cambia_al_ocultar_o_no_lo_vencido() -> None:
    """`solo_con_plazo` faltaba en la huella, y el fallo era invisible.

    Dos peticiones que solo se diferenciaran en ese interruptor compartían entrada de caché: la
    primera en llegar decidía lo que veía la segunda durante todo un TTL. Marcar «ocultar lo ya
    vencido» no hacía nada si antes alguien había consultado sin marcarlo, y al revés. Es el peor
    tipo de fallo de caché, porque el resultado es correcto para *otra* consulta y no hay ningún
    error que lo delate. Esta prueba es la que impide que vuelva a colarse.
    """
    sin_filtro = Filtros(terminos=("obras",), solo_con_plazo=False)
    con_filtro = Filtros(terminos=("obras",), solo_con_plazo=True)
    assert huella_filtros(sin_filtro) != huella_filtros(con_filtro)


def test_la_huella_no_cambia_cuando_nada_cambia() -> None:
    """La otra mitad de lo anterior: incluir un campo no puede volver inestable la huella."""
    uno = Filtros(terminos=("obras",), solo_con_plazo=True)
    otro = Filtros(terminos=("obras",), solo_con_plazo=True)
    assert huella_filtros(uno) == huella_filtros(otro)


def test_la_huella_cambia_con_los_filtros_del_listado_de_ofertas() -> None:
    """Los cuatro criterios del listado de ofertas tienen que entrar en la huella.

    Es la misma trampa que `solo_con_plazo`, repetida cuatro veces: el listado de ofertas se sirve
    por el mismo endpoint que la tabla, así que dos pantallas que solo se diferenciaran en la
    entidad o en el código compartirían entrada de caché. La primera en consultar decidiría lo que
    ve la otra durante todo un TTL, y ninguna de las dos tendría un error que mirar.
    """
    base = huella_filtros(Filtros(terminos=("obras",)))
    variantes = (
        Filtros(terminos=("obras",), entidad="Municipio"),
        Filtros(terminos=("obras",), tipo_proceso="Subasta"),
        Filtros(terminos=("obras",), tipo_necesidad="Bien"),
        Filtros(terminos=("obras",), codigo="NIC-1768"),
    )
    for variante in variantes:
        assert huella_filtros(variante) != base


def test_la_huella_ignora_las_mayusculas_del_codigo() -> None:
    """Un código en mayúsculas o en minúsculas es la misma búsqueda, y no debe ocupar dos fichas.

    La comparación contra la base es `ILIKE`, así que las dos formas devuelven lo mismo. Si la
    huella las tratara como distintas, la misma consulta llenaría la caché con dos copias iguales.
    """
    uno = Filtros(codigo="NIC-1768")
    otro = Filtros(codigo="nic-1768")
    assert huella_filtros(uno) == huella_filtros(otro)


# --------------------------------------------------------------------------- #
# Claves de caché
# --------------------------------------------------------------------------- #


def test_la_clave_cambia_con_la_generacion() -> None:
    """Al subir la generación, la clave antigua deja de hallarse: así invalida el caché."""
    filtros = Filtros(terminos=("obras",))
    assert clave_resultados(filtros, 1) != clave_resultados(filtros, 2)


def test_la_clave_es_igual_para_los_mismos_filtros() -> None:
    uno = Filtros(terminos=normalizar_terminos(["Obras"]))
    otro = Filtros(terminos=normalizar_terminos(["obras"]))
    assert clave_resultados(uno, 7) == clave_resultados(otro, 7)


def test_la_clave_de_generacion_identifica_la_fuente() -> None:
    assert clave_generacion("NCO") == "generacion:NCO"


# --------------------------------------------------------------------------- #
# Paginación
# --------------------------------------------------------------------------- #


def test_calcula_el_numero_de_paginas() -> None:
    pagina = PaginaResultados(elementos=(), total=51, pagina=1, tamano=25, generacion=0)
    assert pagina.paginas == 3


def test_una_sola_pagina_no_tiene_siguiente() -> None:
    pagina = PaginaResultados(elementos=(), total=10, pagina=1, tamano=25, generacion=0)
    assert not pagina.hay_siguiente
    assert not pagina.hay_anterior


def test_en_la_ultima_pagina_no_hay_siguiente() -> None:
    pagina = PaginaResultados(elementos=(), total=51, pagina=3, tamano=25, generacion=0)
    assert pagina.hay_anterior
    assert not pagina.hay_siguiente


def test_sin_resultados_no_hay_paginas() -> None:
    pagina = PaginaResultados(elementos=(), total=0, pagina=1, tamano=25, generacion=0)
    assert pagina.paginas == 0


def test_limitar_elementos_devuelve_solo_la_pagina_pedida() -> None:
    elementos = [{"i": i} for i in range(60)]
    recortados = limitar_elementos(elementos, Filtros(pagina=2, tamano=25))
    assert len(recortados) == 25
    assert recortados[0] == {"i": 25}


def test_el_criterio_de_orden_forma_parte_de_la_huella() -> None:
    """Si no formara parte, dos órdenes compartirían entrada y uno devolvería el del otro."""
    recientes = Filtros(orden=OrdenBusqueda.RECIENTES)
    antiguos = Filtros(orden=OrdenBusqueda.ANTIGUOS)
    assert huella_filtros(recientes) != huella_filtros(antiguos)


# --------------------------------------------------------------------------- #
# Qué consultas se guardan en el caché y cuáles no
#
# La regla no es de corrección —la respuesta sería la misma— sino de coste: el caché solo sirve
# para lo que se repite. El texto libre lo teclea cada persona, así que su espacio de claves es
# ilimitado y cada entrada que se guardara ocuparía sitio hasta caducar sin acertar nunca.
# --------------------------------------------------------------------------- #


def test_una_consulta_con_desplegables_y_terminos_se_cachea() -> None:
    """Los términos son un catálogo compartido y los desplegables se repiten entre usuarios."""
    assert Filtros(terminos=("obras",), provincias=("Pichincha",), estado="En Curso").cacheable


def test_una_busqueda_por_codigo_no_se_cachea() -> None:
    assert not Filtros(codigo="NCORegistro-2026-001").cacheable


def test_una_busqueda_libre_no_se_cachea() -> None:
    assert not Filtros(texto="lo que se me ocurra").cacheable


# --------------------------------------------------------------------------- #
# El filtro por CPC
#
# Es un criterio propio y no una variante de `terminos`, y las pruebas de aquí protegen las dos
# consecuencias de que lo sea: que la huella lo distinga —o dos vigilancias distintas compartirían
# entrada de caché y una vería los resultados de la otra— y que se pueda buscar **solo** por
# clasificación, que es lo que evita traer todo lo que menciona la palabra en el texto libre.
# --------------------------------------------------------------------------- #


def test_la_huella_distingue_los_terminos_de_los_criterios_de_cpc() -> None:
    """«lavado» en el objeto y «lavado» en el CPC son dos consultas distintas. No pueden compartir
    entrada de caché: devuelven conjuntos distintos y la primera en preguntar decidiría lo que ve
    la otra durante todo un TTL, sin ningún error que mirar."""
    por_texto = Filtros(terminos=("lavado",))
    por_cpc = Filtros(cpc=("lavado",))

    assert huella_filtros(por_texto) != huella_filtros(por_cpc)
    assert huella_filtros(Filtros(cpc=("lavado",))) != huella_filtros(Filtros(cpc=("aseo",)))


def test_la_huella_ignora_el_orden_de_los_criterios_de_cpc() -> None:
    uno = Filtros(cpc=normalizar_terminos(["lavado", "engrasado"]))
    otro = Filtros(cpc=normalizar_terminos(["engrasado", "lavado"]))
    assert huella_filtros(uno) == huella_filtros(otro)


def test_los_operadores_de_busqueda_no_llegan_al_cpc() -> None:
    """El cuadro de texto es del usuario: un `|` o un `&` cambiarían la consulta si pasaran."""
    filtros = Filtros(cpc=normalizar_terminos(["lavado|engrasado", "a & b"]))
    for termino in filtros.cpc:
        assert "|" not in termino
        assert "&" not in termino


def test_filtrar_por_cpc_se_cachea() -> None:
    """Los términos de CPC llegan normalizados, así que se repiten entre personas."""
    assert Filtros(cpc=("lavado",), provincias=("Pichincha",)).cacheable


def test_sin_cpc_la_huella_no_cambia() -> None:
    """Incluir un campo nuevo no puede volver inestable la huella de las consultas de siempre."""
    assert huella_filtros(Filtros(terminos=("obras",))) == huella_filtros(
        Filtros(terminos=("obras",), cpc=())
    )


def test_un_espacio_suelto_no_desactiva_la_cache() -> None:
    """Un espacio no es un filtro: si contara, escribir y borrar dejaría la caché apagada."""
    assert Filtros(codigo="   ", texto="  ").cacheable


def test_la_regla_no_depende_de_otros_filtros() -> None:
    """Un rango de fechas o una palabra clave no cambian la decisión: la decide el texto libre."""
    assert Filtros(desde=date(2026, 1, 1), hasta=date(2026, 6, 30), terminos=("obras",)).cacheable
    assert not Filtros(desde=date(2026, 1, 1), terminos=("obras",), texto="viales").cacheable


# --------------------------------------------------------------------------- #
# Qué es un código de CPC y el interruptor «solo CPC»
#
# La distinción decide **por qué índice** se busca, y de ella depende que un código encuentre todas
# las filas clasificadas así. El interruptor decide si las palabras clave se exigen además, y por
# eso tiene que estar en la huella: fuera de ella, dos consultas distintas compartirían página.
# --------------------------------------------------------------------------- #


def test_un_codigo_de_cpc_se_reconoce_por_su_forma() -> None:
    """El CPC es una nomenclatura numérica: el código se pega tal cual."""
    assert es_codigo_cpc("871410032")
    assert es_codigo_cpc("002110011")


def test_una_descripcion_no_es_un_codigo() -> None:
    """Confundirlos no da un error: da menos filas de las que hay."""
    assert not es_codigo_cpc("lavado")
    assert not es_codigo_cpc("87141")
    assert not es_codigo_cpc("87141003A")


def test_la_huella_distingue_solo_cpc_de_cpc_mas_palabras() -> None:
    """Faltando en la huella, «solo CPC» recibiría la página de «CPC + palabras».

    Es la trampa que ya apareció con `solo_con_plazo` y con la categoría: el resultado es correcto
    para *otra* consulta y no hay ningún error que lo delate.
    """
    con_palabras = Filtros(cpc=("871410032",), terminos=("hospital",))
    solo_cpc = Filtros(cpc=("871410032",), terminos=("hospital",), solo_cpc=True)

    assert huella_filtros(con_palabras) != huella_filtros(solo_cpc)
