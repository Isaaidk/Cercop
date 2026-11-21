"""Cobertura de las palabras clave y jerarquía del CPC (QA del cliente, ciclo 3).

Nueve palabras clave que el cliente vigila no daban resultados en CercoApp mientras el portal sí
tenía procesos. Causas reproducidas con el histórico local y fijadas aquí:

- **Plurales**: «servicios» o «mantenimientos» no encontraban «servicio de…» ni «mantenimiento
  preventivo» (la búsqueda es por prefijo, y el plural es más largo que el singular).
- **Palabras pegadas por un signo**: «llantas/neumaticos» o «equipos.computo» eran un solo token
  para PostgreSQL (se arregla en el índice, migración 0049; aquí, la regla de partir).
- **Solo en el CPC del ítem**: la palabra estaba en el nombre estándar del CPC y no en el objeto.
- **CPC padre**: elegir «8714» no traía «871410032».
"""

from __future__ import annotations

import pytest

from contratacion.dominio.busqueda import (
    ModoBusqueda,
    coincide,
    es_codigo_cpc,
    expresion_busqueda,
    normalizar_terminos,
)
from contratacion.dominio.palabras import raices, texto_indexable
from contratacion.dominio.propuestas import filtros_sugeridos
from contratacion.dominio.radar import CriteriosComerciales, coincide_cpc, coincide_texto
from contratacion.infraestructura.adaptadores.salida.bd.radar import patrones_de_palabras


@pytest.mark.parametrize(
    ("palabra", "esperadas"),
    [
        ("servicios", ("servicio",)),
        ("mantenimientos", ("mantenimiento",)),
        ("reparaciones", ("reparacion",)),
        ("motores", ("motor",)),
        ("lapices", ("lapiz", "lapices")),
        ("lapiz", ("lapiz", "lapices")),
        ("limpieza", ("limpieza",)),
        ("mes", ("mes",)),  # demasiado corta para recortarla
        ("2026", ("2026",)),
    ],
)
def test_raices_del_plural(palabra: str, esperadas: tuple[str, ...]) -> None:
    assert raices(palabra) == esperadas


def test_el_plural_encuentra_el_singular_y_al_reves() -> None:
    texto = texto_indexable("Servicio de mantenimiento preventivo de vehículos")
    assert coincide(texto, normalizar_terminos(["servicios"]), ModoBusqueda.TODAS)
    assert coincide(texto, normalizar_terminos(["mantenimientos"]), ModoBusqueda.TODAS)
    assert coincide(texto, normalizar_terminos(["vehiculo"]), ModoBusqueda.TODAS)
    assert expresion_busqueda(normalizar_terminos(["Servicios"]), ModoBusqueda.TODAS) == (
        "(servicio:*)"
    )


def test_las_palabras_pegadas_por_un_signo_se_separan() -> None:
    texto = texto_indexable("Adquisición de llantas/neumáticos y “equipos.computo”")
    assert texto == "adquisicion de llantas neumaticos y equipos computo"
    assert coincide(texto, normalizar_terminos(["neumaticos"]), ModoBusqueda.TODAS)
    assert coincide(texto, normalizar_terminos(["computo"]), ModoBusqueda.TODAS)


def test_codigos_padre_de_cpc() -> None:
    assert es_codigo_cpc("87")
    assert not es_codigo_cpc("8")
    assert normalizar_terminos(["87", "73210.00.1"]) == ("73210001", "87")


def test_las_alertas_comparan_el_cpc_por_el_inicio() -> None:
    criterios = CriteriosComerciales(cpc=("8714",))
    assert coincide_cpc(criterios, ["871410032"])
    # Antes se aceptaba por subcadena en cualquier posición: «8714» dentro de «98714…».
    assert not coincide_cpc(criterios, ["987140001"])
    # Una ínfima con un código demasiado corto no encaja «al revés».
    assert not coincide_cpc(CriteriosComerciales(cpc=("871410032",)), ["87"])
    assert coincide_cpc(CriteriosComerciales(cpc=("871410032",)), ["8714"])


def test_las_alertas_reconocen_el_plural() -> None:
    criterios = CriteriosComerciales(palabras=("Mantenimientos", "servicios de limpieza"))
    texto = "MANTENIMIENTO PREVENTIVO Y SERVICIO DE LIMPIEZA DE OFICINAS"
    assert coincide_texto(criterios, texto) == ["Mantenimientos", "servicios de limpieza"]


def test_la_criba_sql_de_propuestas_no_es_mas_estrecha_que_la_regla() -> None:
    patrones = patrones_de_palabras(("servicios de limpieza",))
    assert "%servicios de limpieza%" in patrones
    assert "%servicio%de%limpieza%" in patrones


def test_filtros_sugeridos_desde_el_perfil() -> None:
    perfil = {
        "ofertas": [{"nombre": "Mantenimiento de vehículos", "descripcion": "CPC 87141"}],
        "experiencia": [{"cpc": "8715"}],
        "palabras": [{"texto": "Llantas"}, {"texto": "llantas"}],
        "cobertura": [{"provincia": "Pichincha", "canton": "Quito"}, {"provincia": "Pichincha"}],
        "dedicaciones": [{"tipo_procedimiento": "subasta_inversa"}],
    }
    sugeridos = filtros_sugeridos(perfil)
    assert sugeridos["cpc"] == ["87141", "8715"]
    assert sugeridos["palabras"] == ["Llantas", "Mantenimiento de vehículos"]
    assert sugeridos["provincias"] == ["Pichincha"]
    assert sugeridos["tipos_proceso"] == ["Subasta Inversa Electrónica"]
    assert sugeridos["vacio"] is False
    assert filtros_sugeridos({})["vacio"] is True
