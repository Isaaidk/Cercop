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
    Filtros,
    ModoBusqueda,
    OrdenBusqueda,
    PaginaResultados,
    clave_generacion,
    clave_resultados,
    coincide,
    expresion_busqueda,
    huella_filtros,
    limitar_elementos,
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
    con_provincia = Filtros(terminos=("obras",), provincia="Azuay")
    assert huella_filtros(base) != huella_filtros(con_provincia)


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
