"""Fábrica de los adaptadores de seguridad.

Se construyen una sola vez por proceso porque ambos son caros de crear y no guardan estado por
petición: el derivador de contraseñas reserva memoria para el cálculo, y el firmante de tokens solo
necesita la clave.

Los adaptadores se piden por su **puerto**, no por su clase. Así las pruebas pueden sustituirlos por
dobles sin tocar ni el enrutador ni los casos de uso.
"""

from __future__ import annotations

import logging

from contratacion.aplicacion.puertos.seguridad import ServicioContrasenas, ServicioTokens
from contratacion.infraestructura.adaptadores.salida.seguridad.contrasenas import (
    HUELLA_DESCARTE,
    ContrasenasArgon2,
)
from contratacion.infraestructura.adaptadores.salida.seguridad.tokens import TokensJwt
from contratacion.infraestructura.config.ajustes import obtener_ajustes

registro = logging.getLogger(__name__)

_contrasenas: ServicioContrasenas | None = None
_tokens: ServicioTokens | None = None


def obtener_contrasenas() -> ServicioContrasenas:
    """Derivador de contraseñas compartido."""
    global _contrasenas
    if _contrasenas is None:
        _contrasenas = ContrasenasArgon2()
    return _contrasenas


def obtener_tokens() -> ServicioTokens:
    """Firmante de tokens compartido."""
    global _tokens
    if _tokens is None:
        ajustes = obtener_ajustes()
        _tokens = TokensJwt(ajustes.jwt_secreto, algoritmo=ajustes.jwt_algoritmo)
    return _tokens


def huella_de_descarte() -> str:
    """Huella contra la que se comprueba una contraseña cuando la cuenta no existe.

    Se expone desde aquí para que el caso de uso no dependa del adaptador: recibe la huella como
    parámetro y así se puede probar con un valor trivial.
    """
    return HUELLA_DESCARTE


def liberar_seguridad() -> None:
    """Olvida los adaptadores creados.

    Lo usan las pruebas, que cambian de ajustes entre casos: sin esto, el firmante de la primera
    prueba seguiría usando su clave en las siguientes.
    """
    global _contrasenas, _tokens
    _contrasenas = None
    _tokens = None
