"""Pruebas del motivo legible de un fallo de conexión.

Existen por un despliegue que se quedó parado sin decir por qué: el registro del API solo escribía
`Postgres no responde`, así que la causa —el nombre del servicio mal puesto, que hacía imposible
resolver la dirección— había que adivinarla. Lo que se comprueba aquí son dos cosas a la vez, y las
dos importan: que el motivo **diga qué pasó** y que **no pueda filtrar nada**.

La segunda mitad se prueba de verdad: se construye una excepción cuyo mensaje lleva una contraseña,
como hacen algunos errores del controlador, y se exige que esa contraseña **no aparezca** en el
motivo.
"""

from __future__ import annotations

import socket

import pytest
from sqlalchemy.exc import InternalError, OperationalError

from contratacion.infraestructura.adaptadores.salida.bd.motivos import motivo_legible

CLAVE_DE_VERDAD = "ChispoyNaomi0305"


def _error(mensaje: str) -> OperationalError:
    """Un error de base de datos con el texto que se quiera comprobar."""
    return OperationalError("SELECT 1", {}, Exception(mensaje))


@pytest.mark.parametrize(
    ("excepcion", "esperado"),
    [
        # El caso del despliegue: el nombre no se resuelve. Llega como `socket.gaierror`, que es el
        # tipo exacto, y también como el texto que escribe asyncpg.
        (socket.gaierror(11001, "getaddrinfo failed"), "no se pudo resolver el nombre"),
        (_error("[Errno 11001] getaddrinfo failed"), "no se pudo resolver el nombre"),
        # Credenciales: el mensaje original sí lleva la cadena de conexión en algunos controladores,
        # por eso se responde por el tipo del fallo y no copiando el texto.
        (
            _error('password authentication failed for user "contratacion"'),
            "credenciales rechazadas",
        ),
        (_error("InvalidPasswordError: password authentication failed"), "credenciales rechazadas"),
        # El puerto cerrado y la máquina que no contesta.
        (_error("connect call failed ('10.0.0.5', 5432)"), "no acepta conexiones"),
        (ConnectionRefusedError(111, "Connection refused"), "no acepta conexiones"),
        (_error("timeout expired"), "tiempo de espera"),
        # El usuario o la base que no existen: el texto lleva comillas, y eso lo separa de un
        # «column does not exist», que sería un defecto de una consulta y no de la configuración.
        (_error('InvalidCatalogNameError: database "contratacion" does not exist'), "no existen"),
        (_error('role "contratacion" does not exist'), "no existen"),
        # El agrupador de Supabase en modo transacción, que es una trampa conocida de este proyecto.
        (_error("prepared statement already exists"), "sentencias preparadas"),
    ],
)
def test_el_motivo_dice_que_paso(excepcion: BaseException, esperado: str) -> None:
    assert esperado in motivo_legible(excepcion)


def test_la_saturacion_se_reconoce_igual_que_en_el_resto_del_sistema() -> None:
    """La misma frase que usa el manejador HTTP: la clasificación no se duplica."""
    error = InternalError(
        "SELECT 1", {}, Exception("(EMAXCONNSESSION) max clients reached in session mode")
    )
    assert "no hay conexiones libres" in motivo_legible(error)


def test_un_fallo_desconocido_dice_el_tipo_y_no_el_mensaje() -> None:
    """Un nombre de excepción no lleva datos; el mensaje sí puede llevarlos."""
    motivo = motivo_legible(RuntimeError("algo raro con la clave " + CLAVE_DE_VERDAD))

    assert "RuntimeError" in motivo
    assert CLAVE_DE_VERDAD not in motivo


def test_una_consulta_mal_escrita_no_se_confunde_con_credenciales() -> None:
    """`column does not exist` es un defecto de una consulta, no un problema de configuración."""
    motivo = motivo_legible(_error('column "objeto_compra" does not exist'))

    assert "no existen" not in motivo


def test_ningun_motivo_lleva_el_mensaje_original() -> None:
    """Ni la dirección, ni el usuario, ni la contraseña: el texto lo escribe este módulo."""
    con_secretos = (
        f"connection to server at 10.0.0.5, port 5432 failed: password authentication failed "
        f"for user contratacion (password={CLAVE_DE_VERDAD})"
    )
    motivo = motivo_legible(_error(con_secretos))

    for dato in ("10.0.0.5", "5432", "contratacion", CLAVE_DE_VERDAD):
        assert dato not in motivo
