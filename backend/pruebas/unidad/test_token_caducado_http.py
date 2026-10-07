"""Pruebas del contrato HTTP de un token caducado.

Este archivo existe por un fallo que nadie veía como un fallo. El verificador rechazaba igual un
token manipulado y uno caducado —mismo mensaje, mismo tipo—, así que el transporte devolvía **403**
en los dos casos. El panel solo intenta renovar ante un 401, de modo que la renovación silenciosa no
llegaba a ejecutarse nunca: después de un rato con el panel abierto aparecía «no tienes permiso para
esto» por haber dejado la pestaña ahí.

Ninguna prueba de unidad podía detectarlo, porque la pieza que estaba mal era la costura: el tipo
del error y el código HTTP que le corresponde. Lo que se comprueba aquí es exactamente eso, la
respuesta que recibe el navegador.

No hace falta base de datos ni almacén: el token se verifica **antes** de tocar cualquiera de los
dos, y es ahí donde se decide el código de la respuesta.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from contratacion.aplicacion.puertos.seguridad import Claims, TipoToken
from contratacion.infraestructura.adaptadores.salida.seguridad.tokens import TokensJwt
from contratacion.infraestructura.app import crear_app

RUTA_PROTEGIDA = "/v1/presencia"


@pytest.fixture
def aplicacion() -> FastAPI:
    return crear_app()


@pytest.fixture
def cliente(aplicacion: FastAPI) -> TestClient:
    return TestClient(aplicacion)


def _token(aplicacion: FastAPI, *, segundos: int) -> str:
    """Emite un token de acceso con el mismo secreto que usa la aplicación montada.

    Se lee el secreto de los ajustes de la aplicación en lugar de componerlo aquí: con otro
    secreto, la prueba comprobaría el rechazo de una firma ajena y no el caso que importa.
    """
    ajustes = aplicacion.state.ajustes
    servicio = TokensJwt(ajustes.jwt_secreto, algoritmo=ajustes.jwt_algoritmo)

    ahora = datetime.now(UTC)
    return servicio.emitir(
        Claims(
            usuario_id=uuid4(),
            negocio_id=uuid4(),
            rol="admin_negocio",
            sesion_id=uuid4(),
            tipo=TipoToken.ACCESO,
            expira_en=ahora + timedelta(seconds=segundos),
        ),
        segundos,
    )


def _pedir(cliente: TestClient, token: str) -> tuple[int, dict[str, object]]:
    respuesta = cliente.get(RUTA_PROTEGIDA, headers={"Authorization": f"Bearer {token}"})
    return respuesta.status_code, respuesta.json()


def test_un_token_caducado_devuelve_401_y_su_codigo(
    aplicacion: FastAPI, cliente: TestClient
) -> None:
    """Es lo que hace que el panel renueve y repita la petición sin molestar a nadie."""
    estado, cuerpo = _pedir(cliente, _token(aplicacion, segundos=-60))

    assert estado == 401, cuerpo
    assert cuerpo["codigo"] == "token_caducado"


def test_un_token_manipulado_sigue_devolviendo_403(
    aplicacion: FastAPI, cliente: TestClient
) -> None:
    """Y no 401, porque aquí no hay nada que renovar: volver a entrar es lo único que lo arregla.

    Tratar un token manipulado como una sesión caducada mandaría al panel a renovar contra un token
    que el servidor no va a aceptar nunca, y el usuario acabaría en la pantalla de acceso sin
    entender por qué se le habla de una sesión que él no ha tocado.
    """
    valido = _token(aplicacion, segundos=900)
    estado, cuerpo = _pedir(cliente, f"{valido[:-4]}AAAA")

    assert estado == 403, cuerpo
    assert cuerpo["codigo"] == "sin_permiso"


def test_los_dos_llevan_el_mismo_mensaje(aplicacion: FastAPI, cliente: TestClient) -> None:
    """La diferencia está en el código, no en el texto, y eso es deliberado.

    El mensaje que lee una persona es el mismo porque explicarle qué es un token no le sirve para
    nada. Si alguien separa los textos «para que se entiendan mejor», lo que conseguirá es contarle
    al usuario detalles del protocolo y, de paso, a quien intenta forzar el sistema.
    """
    caducado = _pedir(cliente, _token(aplicacion, segundos=-60))[1]["detail"]
    manipulado = _pedir(cliente, f"{_token(aplicacion, segundos=900)[:-4]}AAAA")[1]["detail"]

    assert caducado == manipulado

    assert caducado == manipulado
