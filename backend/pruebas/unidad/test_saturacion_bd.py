"""Pruebas de la costura entre «la base está saturada» y lo que recibe el navegador.

Existen por lo que pasó el 2026-10-06: el agrupador de conexiones de Supabase llegó a su tope
—quince clientes en modo sesión— y el API empezó a contestar **500** a todo, setenta y seis
peticiones seguidas. El panel enseñaba «La API respondió 500.», que no dice nada a quien lo lee y
manda a buscar el fallo en el sitio equivocado: el programa estaba bien, la dependencia no daba
paso.

Ninguna prueba de unidad podía verlo, porque lo que estaba mal no era una función: era el código
HTTP que se elegía para un tipo de fallo. Se comprueba aquí lo que recibe el navegador, y también lo
contrario —que un defecto de verdad **siga** siendo un 500 y que su cuerpo no lleve la consulta—,
porque un manejador que se lo traga todo convierte los defectos en «vuelve a intentarlo».

No hace falta base de datos: los fallos se provocan a mano en dos rutas de prueba, montadas sobre la
aplicación real para que pasen por el mismo manejador que las de producción.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import (
    DBAPIError,
    InternalError,
    ProgrammingError,
)
from sqlalchemy.exc import (
    TimeoutError as ErrorDeEspera,
)

from contratacion.infraestructura.adaptadores.salida.bd.saturacion import es_saturacion
from contratacion.infraestructura.app import crear_app

# El mensaje literal del agrupador, copiado del registro del 2026-10-06. La prueba usa el texto real
# y no uno inventado: lo que se clasifica es el texto, así que un mensaje de mentira probaría la
# prueba y no el código.
MENSAJE_AGRUPADOR = (
    "(EMAXCONNSESSION) max clients reached in session mode - "
    "max clients are limited to pool_size: 15"
)
MENSAJE_ESPERA_AGRUPADOR = (
    "(ECHECKOUTTIMEOUT) unable to check out connection from the pool after 15000ms in Session mode"
)
MENSAJE_CONJUNTO_PROPIO = "QueuePool limit of size 4 overflow 2 reached, connection timed out"

RUTA_SATURADA = "/probar/saturacion"
RUTA_DEFECTUOSA = "/probar/defecto"
CONSULTA_CON_DATOS = "SELECT objeto_compra FROM registro WHERE entidad = 'Hospital de prueba'"


def _error_de_agrupador(mensaje: str) -> DBAPIError:
    """Un error de base con el texto del agrupador, con la forma que tiene en la realidad."""
    return InternalError("SELECT 1", {}, Exception(mensaje))


@pytest.mark.parametrize(
    "excepcion",
    [
        _error_de_agrupador(MENSAJE_AGRUPADOR),
        _error_de_agrupador(MENSAJE_ESPERA_AGRUPADOR),
        _error_de_agrupador("FATAL: sorry, too many clients already"),
        _error_de_agrupador("FATAL: remaining connection slots are reserved for superusers"),
        ErrorDeEspera(MENSAJE_CONJUNTO_PROPIO),
    ],
)
def test_las_cinco_formas_de_quedarse_sin_conexiones_se_reconocen(
    excepcion: DBAPIError,
) -> None:
    """Las cinco dan el mismo problema con mensajes distintos, y dos son de otra pieza."""
    assert es_saturacion(excepcion) is True


@pytest.mark.parametrize(
    "excepcion",
    [
        # Un error de SQL es un defecto del programa, no una saturación. Si esto se clasificara como
        # saturación, la persona reintentaría para siempre un fallo que no se arregla reintentando.
        ProgrammingError("SELECT x", {}, Exception('column "x" does not exist')),
        # Y este otro se dio hoy mismo: la consulta se canceló por tardar demasiado. También es un
        # fallo del programa —una consulta sin índice— y también se queda en 500.
        _error_de_agrupador("canceling statement due to statement timeout"),
        # Un fallo que ni siquiera viene de la base no puede leerse como saturación, aunque su texto
        # lo parezca.
        RuntimeError("too many clients"),
    ],
)
def test_lo_que_no_es_saturacion_no_se_clasifica_como_tal(excepcion: Exception) -> None:
    assert es_saturacion(excepcion) is False


@pytest.fixture
def cliente() -> TestClient:
    """La aplicación real, con dos rutas que fallan: una por saturación y otra por defecto."""
    aplicacion = crear_app()

    @aplicacion.get(RUTA_SATURADA)
    async def _saturada() -> None:
        raise _error_de_agrupador(MENSAJE_AGRUPADOR)

    @aplicacion.get(RUTA_DEFECTUOSA)
    async def _defectuosa() -> None:
        raise ProgrammingError(CONSULTA_CON_DATOS, {}, Exception("syntax error"))

    return TestClient(aplicacion)


def test_la_base_saturada_responde_503_y_lo_explica(cliente: TestClient) -> None:
    """503, no 500: es la misma respuesta que `/listo` usa para «vivo, pero una dependencia no»."""
    respuesta = cliente.get(RUTA_SATURADA)

    assert respuesta.status_code == 503, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["codigo"] == "bd_saturada"
    # El mensaje tiene que decir qué hacer. «La API respondió 500.» es exactamente lo que no.
    assert "conexiones libres" in cuerpo["detail"]
    assert "intentarlo" in cuerpo["detail"]


def test_la_saturacion_no_ensena_vocabulario_del_agrupador(cliente: TestClient) -> None:
    """Quien lee no administra Supabase: el mensaje dice qué pasa, no cómo se llama por dentro."""
    texto = cliente.get(RUTA_SATURADA).text

    assert "EMAXCONNSESSION" not in texto
    assert "pool_size" not in texto


def test_un_defecto_de_sql_sigue_siendo_500(cliente: TestClient) -> None:
    """Lo que se arregla con un despliegue no puede disfrazarse de «reintenta en unos segundos»."""
    respuesta = cliente.get(RUTA_DEFECTUOSA)

    assert respuesta.status_code == 500, respuesta.text
    assert respuesta.json()["codigo"] == "error_bd"


def test_el_cuerpo_del_500_no_lleva_la_consulta(cliente: TestClient) -> None:
    """Un error de SQL trae la consulta y sus parámetros: datos de negocio que no salen por HTTP."""
    texto = cliente.get(RUTA_DEFECTUOSA).text

    assert "syntax error" not in texto
    assert "Hospital de prueba" not in texto
    assert "SELECT" not in texto
