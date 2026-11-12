"""Detector de intenciones del asistente: lo que se contesta sin modelo y lo que no.

El error caro aquí es el falso positivo: contestar «tus propuestas» a quien pidió buscar algo con
filtros. Por eso hay tantas pruebas de lo que **no** debe reconocerse como de lo que sí.
"""

from __future__ import annotations

import pytest

from contratacion.dominio.intencion import (
    TipoIntencion,
    codigo_de_proceso,
    detectar,
    plegar,
    provincia_mencionada,
    provincia_oficial,
    ruc_en,
)

T = TipoIntencion


@pytest.mark.parametrize(
    "texto",
    ["hola", "Hola!", "buenos días", "Buenas tardes, asistente", "¡HOLA! ¿cómo estás?", "gracias"],
)
def test_saludos(texto: str) -> None:
    assert detectar(texto).tipo is T.SALUDO


@pytest.mark.parametrize(
    "texto", ["ayuda", "¿Qué puedes hacer?", "como funciona esto", "en qué me puedes ayudar"]
)
def test_ayuda(texto: str) -> None:
    assert detectar(texto).tipo is T.AYUDA


def test_mensaje_vacio_es_ayuda() -> None:
    assert detectar("   ").tipo is T.AYUDA


@pytest.mark.parametrize(
    "texto",
    [
        "recomiéndame ínfimas",
        "Recomiendame infimas",
        "¿Qué ínfimas hay para mí?",
        "propuestas",
        "¿A qué puedo aplicar hoy?",
        "oportunidades para mi empresa",
        "muéstrame mis propuestas",
    ],
)
def test_recomendaciones_van_por_el_camino_rapido(texto: str) -> None:
    intencion = detectar(texto)
    assert intencion.tipo is T.PROPUESTAS
    assert intencion.rapida


def test_recomendaciones_con_provincia_y_orden() -> None:
    intencion = detectar("Recomiéndame ínfimas en Pichincha que cierran pronto")
    assert intencion.tipo is T.PROPUESTAS
    assert intencion.argumentos == {"orden": "cierre", "provincia": "Pichincha"}


def test_recomendaciones_por_presupuesto() -> None:
    assert detectar("propuestas por mayor presupuesto").argumentos["orden"] == "presupuesto"


@pytest.mark.parametrize(
    "texto",
    [
        "propuestas de limpieza en Guayas",
        "oportunidades de mantenimiento de impresoras",
        "busca ínfimas de impresoras en Pichincha",
        "recomiéndame ínfimas de computadoras con más de 5000 dólares",
    ],
)
def test_peticiones_con_filtros_van_al_modelo(texto: str) -> None:
    assert detectar(texto).tipo is T.LIBRE


@pytest.mark.parametrize(
    "texto",
    [
        "crea una alerta para mantenimiento de impresoras en Pichincha",
        "Créame una alerta de limpieza",
        "avísame cuando salga algo de uniformes",
        "nueva alerta de computadoras",
    ],
)
def test_crear_alerta_va_al_modelo_aunque_diga_alerta(texto: str) -> None:
    assert detectar(texto).tipo is T.LIBRE


@pytest.mark.parametrize("texto", ["mis alertas", "¿Qué alertas tengo?", "ver mis alertas"])
def test_listar_alertas(texto: str) -> None:
    assert detectar(texto).tipo is T.LISTAR_ALERTAS


@pytest.mark.parametrize("texto", ["mis ofertas", "Mis proformas", "¿cómo van mis ofertas?"])
def test_mis_ofertas(texto: str) -> None:
    intencion = detectar(texto)
    assert intencion.tipo is T.MIS_OFERTAS
    assert intencion.argumentos == {}


def test_mis_ofertas_con_etapa() -> None:
    intencion = detectar("mis ofertas en borrador")
    assert intencion.tipo is T.MIS_OFERTAS
    assert intencion.argumentos == {"etapa": "borrador"}
    assert detectar("mis proformas ganadas").argumentos == {"etapa": "adjudicada"}


@pytest.mark.parametrize(
    "texto", ["mi empresa", "datos de mi empresa", "mis datos", "¿Cuáles son mis CPC?", "mi perfil"]
)
def test_datos_empresa(texto: str) -> None:
    assert detectar(texto).tipo is T.DATOS_EMPRESA


@pytest.mark.parametrize(
    ("texto", "codigo"),
    [
        ("¿Cómo va el NIC-1768123450001-2026-00123?", "NIC-1768123450001-2026-00123"),
        ("estado del proceso sie-uta-2026-0038-3205", "SIE-UTA-2026-0038-3205"),
        ("IC-GADM-2026-001", "IC-GADM-2026-001"),
        ("info COTO-HCAM-001-2026", "COTO-HCAM-001-2026"),
    ],
)
def test_estado_de_un_proceso(texto: str, codigo: str) -> None:
    intencion = detectar(texto)
    assert intencion.tipo is T.ESTADO_PROCESO
    assert intencion.argumentos == {"codigo": codigo}


def test_proforma_para_un_codigo() -> None:
    intencion = detectar("Prepárame la proforma para NIC-1768123450001-2026-00123")
    assert intencion.tipo is T.PREPARAR_PROFORMA
    assert intencion.argumentos == {"codigo": "NIC-1768123450001-2026-00123"}


def test_un_codigo_en_una_frase_larga_sin_pista_va_al_modelo() -> None:
    texto = "compara NIC-1768123450001-2026-00123 con lo que vendimos el año pasado a esa entidad"
    assert detectar(texto).tipo is T.LIBRE


@pytest.mark.parametrize(
    "texto", ["consulta el RUC 1790012345001", "ruc 1790012345001", "1790012345001"]
)
def test_consultar_ruc(texto: str) -> None:
    intencion = detectar(texto)
    assert intencion.tipo is T.CONSULTAR_RUC
    assert intencion.argumentos == {"ruc": "1790012345001"}


@pytest.mark.parametrize(
    "texto",
    [
        "¿Cuántos procesos ha ganado el RUC 1790012345001?",
        "historial del RUC 1790012345001",
        "procesos del RUC 1790012345001",
        "contratos de 1790012345001",
    ],
)
def test_historial_de_un_ruc(texto: str) -> None:
    intencion = detectar(texto)
    assert intencion.tipo is T.HISTORIAL_RUC
    assert intencion.argumentos == {"ruc": "1790012345001"}


def test_pregunta_libre() -> None:
    assert detectar("¿Qué documentos necesito para vender al Estado?").tipo is T.LIBRE


def test_codigos_que_no_lo_son() -> None:
    assert codigo_de_proceso("compra de equipos a-b") is None
    assert codigo_de_proceso("obra-2026") is None
    assert codigo_de_proceso("e-mail") is None
    assert codigo_de_proceso("NIC-1768123450001-2026-00123") == "NIC-1768123450001-2026-00123"


def test_ruc_exige_trece_digitos() -> None:
    assert ruc_en("17900123450012") is None
    assert ruc_en("mi ruc es 1790012345001.") == "1790012345001"


def test_plegar_quita_tildes_y_signos() -> None:
    assert plegar("¿Recomiéndame ÍNFIMAS?") == "recomiendame infimas"


def test_provincias() -> None:
    assert provincia_oficial("galapagos") == "Galápagos"
    assert provincia_oficial("PICHINCHA") == "Pichincha"
    assert provincia_oficial("santo domingo") == "Santo Domingo de los Tsáchilas"
    assert provincia_oficial("Quito") is None
    assert provincia_mencionada("infimas en los rios hoy") == "Los Ríos"
