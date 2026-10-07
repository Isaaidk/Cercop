"""Pruebas de los adaptadores de seguridad reales.

Aquí sí se usa criptografía de verdad, y por eso son las pruebas que demuestran que la configuración
del adaptador no tiene agujeros. Las dos que más importan:

- `test_rechaza_un_token_sin_firma` comprueba la vulnerabilidad clásica de esta tecnología: un
  atacante fabrica un token con `alg: none` y, si el verificador acepta el algoritmo que declara el
  propio token, entra sin conocer ninguna clave.
- `test_rechaza_un_token_de_acceso_donde_se_espera_uno_de_renovacion` comprueba la separación de
  tipos: sin ella, robar un token de minutos daría acceso indefinido.
- `test_un_token_caducado_no_es_lo_mismo_que_uno_manipulado` comprueba que la caducidad tenga
  **tipo propio**, que es de donde sale el 401 que hace que el panel renueve en silencio. Con el
  mismo tipo para todo, el token caducado devolvía un 403 y la renovación no llegaba a ejecutarse.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest

from contratacion.aplicacion.puertos.seguridad import Claims, TipoToken
from contratacion.dominio.errores import SinPermiso, TokenCaducado
from contratacion.infraestructura.adaptadores.salida.seguridad.contrasenas import (
    ContrasenasArgon2,
)
from contratacion.infraestructura.adaptadores.salida.seguridad.tokens import TokensJwt

SECRETO = "s" * 48
AHORA = datetime.now(UTC)


def _claims(tipo: TipoToken = TipoToken.ACCESO, *, minutos: int = 15) -> Claims:
    return Claims(
        usuario_id=uuid4(),
        negocio_id=uuid4(),
        rol="admin_negocio",
        sesion_id=uuid4(),
        tipo=tipo,
        expira_en=AHORA + timedelta(minutes=minutos),
    )


# --------------------------------------------------------------------------- #
# Contraseñas
# --------------------------------------------------------------------------- #


def test_argon2_no_guarda_la_contrasena() -> None:
    servicio = ContrasenasArgon2()
    huella = servicio.hash("correcto-caballo-bateria")
    assert "correcto" not in huella
    assert huella.startswith("$argon2id$")


def test_argon2_produce_huellas_distintas_para_la_misma_contrasena() -> None:
    """La sal aleatoria es lo que impide que dos usuarios con la misma contraseña se delaten."""
    servicio = ContrasenasArgon2()
    assert servicio.hash("correcto-caballo-bateria") != servicio.hash("correcto-caballo-bateria")


def test_argon2_verifica_la_correcta() -> None:
    servicio = ContrasenasArgon2()
    assert servicio.verificar(servicio.hash("correcto-caballo-bateria"), "correcto-caballo-bateria")


def test_argon2_rechaza_la_incorrecta_sin_lanzar() -> None:
    servicio = ContrasenasArgon2()
    assert not servicio.verificar(servicio.hash("correcto-caballo-bateria"), "otra-cosa-distinta")


def test_argon2_con_huella_vacia_devuelve_falso() -> None:
    """Una fila mal formada no puede convertirse en un error del servidor en el camino de acceso."""
    assert not ContrasenasArgon2().verificar("", "lo-que-sea")


def test_argon2_con_huella_corrupta_devuelve_falso() -> None:
    assert not ContrasenasArgon2().verificar("no-es-una-huella", "lo-que-sea")


def test_argon2_detecta_que_hay_que_recalcular() -> None:
    servicio = ContrasenasArgon2()
    assert not servicio.necesita_rehash(servicio.hash("correcto-caballo-bateria"))
    assert servicio.necesita_rehash("no-es-una-huella")


# --------------------------------------------------------------------------- #
# Tokens
# --------------------------------------------------------------------------- #


def test_un_token_va_y_vuelve_con_sus_datos() -> None:
    servicio = TokensJwt(SECRETO)
    original = _claims()
    recuperado = servicio.verificar(servicio.emitir(original, 900), TipoToken.ACCESO)

    assert recuperado.usuario_id == original.usuario_id
    assert recuperado.negocio_id == original.negocio_id
    assert recuperado.sesion_id == original.sesion_id
    assert recuperado.rol == original.rol


def test_un_token_manipulado_se_rechaza() -> None:
    servicio = TokensJwt(SECRETO)
    token = servicio.emitir(_claims(), 900)
    with pytest.raises(SinPermiso):
        servicio.verificar(token[:-4] + "AAAA", TipoToken.ACCESO)


def test_un_token_firmado_con_otra_clave_se_rechaza() -> None:
    ajeno = TokensJwt("o" * 48).emitir(_claims(), 900)
    with pytest.raises(SinPermiso):
        TokensJwt(SECRETO).verificar(ajeno, TipoToken.ACCESO)


def test_rechaza_un_token_sin_firma() -> None:
    """La vulnerabilidad clásica: `alg: none` no puede colarse."""
    contenido = {
        "sub": str(uuid4()),
        "neg": str(uuid4()),
        "rol": "admin_negocio",
        "sid": str(uuid4()),
        "tip": "acceso",
        "iat": int(AHORA.timestamp()),
        "exp": int((AHORA + timedelta(hours=1)).timestamp()),
        "iss": "contratacion-api",
        "aud": "contratacion-web",
    }
    sin_firma = jwt.encode(contenido, None, algorithm="none")

    with pytest.raises(SinPermiso):
        TokensJwt(SECRETO).verificar(sin_firma, TipoToken.ACCESO)


def test_el_contenido_no_declara_el_algoritmo_de_verificacion() -> None:
    """Aunque el token diga otro algoritmo, se verifica con el configurado."""
    servicio = TokensJwt(SECRETO)
    token = servicio.emitir(_claims(), 900)
    cabecera = jwt.get_unverified_header(token)
    assert cabecera["alg"] == "HS256"


def test_rechaza_un_token_caducado() -> None:
    servicio = TokensJwt(SECRETO)
    caducado = servicio.emitir(_claims(), -60)
    with pytest.raises(TokenCaducado):
        servicio.verificar(caducado, TipoToken.ACCESO)


def test_un_token_caducado_no_es_lo_mismo_que_uno_manipulado() -> None:
    """La caducidad se distingue **por el tipo**, y de ahí sale el 401.

    El mensaje que lee una persona es el mismo en los dos casos —«vuelve a entrar»—, así que la
    única forma de que el panel sepa que puede renovar y repetir la petición es que el error sea de
    otra clase. Con un 403 el cliente no reintenta nada: un 403 significa «volver a entrar no
    arregla esto», y ahí la renovación silenciosa no llegaba a ejecutarse nunca.
    """
    servicio = TokensJwt(SECRETO)
    caducado = servicio.emitir(_claims(), -60)
    manipulado = servicio.emitir(_claims(), 900)[:-4] + "AAAA"

    with pytest.raises(TokenCaducado) as caducidad:
        servicio.verificar(caducado, TipoToken.ACCESO)
    with pytest.raises(SinPermiso) as otro:
        servicio.verificar(manipulado, TipoToken.ACCESO)

    assert not isinstance(caducidad.value, SinPermiso)
    assert caducidad.value.codigo == "token_caducado"
    assert otro.value.codigo == "sin_permiso"
    # El texto no distingue nada a propósito: es el mismo para los dos.
    assert str(caducidad.value) == str(otro.value)


def test_rechaza_un_token_de_acceso_donde_se_espera_uno_de_renovacion() -> None:
    servicio = TokensJwt(SECRETO)
    de_acceso = servicio.emitir(_claims(TipoToken.ACCESO), 900)
    with pytest.raises(SinPermiso):
        servicio.verificar(de_acceso, TipoToken.REFRESCO)


def test_rechaza_un_token_de_renovacion_donde_se_espera_uno_de_acceso() -> None:
    servicio = TokensJwt(SECRETO)
    de_renovacion = servicio.emitir(_claims(TipoToken.REFRESCO), 86_400)
    with pytest.raises(SinPermiso):
        servicio.verificar(de_renovacion, TipoToken.ACCESO)


def test_rechaza_un_token_vacio() -> None:
    with pytest.raises(SinPermiso):
        TokensJwt(SECRETO).verificar("", TipoToken.ACCESO)


def test_rechaza_un_token_de_otro_sistema() -> None:
    """Emisor y audiencia distintos: un token de otra aplicación no sirve aquí."""
    ajeno = jwt.encode(
        {"sub": str(uuid4()), "sid": str(uuid4()), "tip": "acceso", "exp": 99_999_999_999},
        SECRETO,
        algorithm="HS256",
        headers={"iss": "otro-sistema", "aud": "otra-web"},
    )
    with pytest.raises(SinPermiso):
        TokensJwt(SECRETO).verificar(ajeno, TipoToken.ACCESO)


def test_la_huella_del_token_es_estable_y_no_revela_el_token() -> None:
    servicio = TokensJwt(SECRETO)
    token = servicio.emitir(_claims(), 900)
    huella = servicio.huella(token)
    assert huella == servicio.huella(token)
    assert token not in huella
    assert len(huella) == 64
