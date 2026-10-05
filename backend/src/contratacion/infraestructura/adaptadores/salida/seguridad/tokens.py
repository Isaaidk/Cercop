"""Adaptador de tokens sobre JWT firmados con HMAC.

Por qué HMAC y no firma asimétrica
----------------------------------
Con HMAC (HS256) la misma clave firma y verifica. Sirve mientras sea **un solo** componente quien
emite y verifica, que es el caso: la API emite y la API verifica. Si algún día un tercero tuviera
que verificar sin poder emitir, habría que pasar a firma asimétrica; hasta entonces, HMAC es más
simple y no hay clave privada que repartir.

Lo que este adaptador comprueba, y por qué cada cosa importa
------------------------------------------------------------
- **El algoritmo se fija de forma explícita.** No se acepta el que declare el token: aceptarlo es la
  vulnerabilidad clásica de esta tecnología, porque un atacante firma con «ningún algoritmo» o con
  HMAC usando la clave pública como secreto y el token pasa por válido.
- **El tipo de token se comprueba.** Un token de acceso no puede usarse para renovar, ni uno de
  renovación para leer. Sin ello, robar uno de minutos daría acceso indefinido.
- **La caducidad, el emisor y la audiencia se verifican.** La caducidad evita el uso diferido; el
  emisor y la audiencia evitan que un token de otro sistema con la misma clave sirva aquí.
- **Los fallos no se detallan.** Cualquier problema devuelve el mismo mensaje: distinguir «firmado
  mal» de «caducado» ayuda más a quien ataca que a quien depura.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt

from contratacion.aplicacion.puertos.seguridad import Claims, TipoToken
from contratacion.dominio.errores import SinPermiso

registro = logging.getLogger(__name__)

EMISOR = "contratacion-api"
AUDIENCIA = "contratacion-web"

# Nombres cortos en el contenido porque el token viaja en cada petición.
CAMPO_PERIODO = "exp"
CAMPO_EMITIDO = "iat"

# El mensaje que ve una persona. **No habla de tokens**, y es deliberado: este texto llega a la
# pantalla cuando la sesión no se puede revalidar, y un usuario no tiene por qué saber qué es un
# token ni qué se hace con él. Lo que necesita saber es que tiene que volver a entrar.
#
# Al servidor y a quien depura les sirve igual: el motivo real queda en el registro, donde sí
# interesa. Un mensaje técnico en la pantalla no ayuda a nadie —a quien ataca tampoco, porque desde
# luego ya sabe lo que estaba intentando— y sí asusta a quien no ha hecho nada.
MENSAJE_INVALIDO = "Tu sesión ha caducado. Vuelve a entrar."


class TokensJwt:
    """Implementación del puerto de tokens."""

    def __init__(
        self,
        secreto: str,
        *,
        algoritmo: str = "HS256",
        emisor: str = EMISOR,
        audiencia: str = AUDIENCIA,
    ) -> None:
        self._secreto = secreto
        self._algoritmo = algoritmo
        self._emisor = emisor
        self._audiencia = audiencia

    def emitir(self, claims: Claims, ttl_seg: int) -> str:
        ahora = datetime.now(UTC)
        contenido: dict[str, Any] = {
            "sub": str(claims.usuario_id),
            "neg": str(claims.negocio_id),
            "rol": claims.rol,
            "sid": str(claims.sesion_id),
            "tip": str(claims.tipo),
            CAMPO_EMITIDO: int(ahora.timestamp()),
            CAMPO_PERIODO: int((ahora + timedelta(seconds=ttl_seg)).timestamp()),
            "iss": self._emisor,
            "aud": self._audiencia,
        }
        return jwt.encode(contenido, self._secreto, algorithm=self._algoritmo)

    def verificar(self, token: str, tipo: TipoToken) -> Claims:
        if not token or not token.strip():
            raise SinPermiso(MENSAJE_INVALIDO)

        try:
            contenido = jwt.decode(
                token,
                self._secreto,
                # Lista explícita: nunca la que declare el propio token.
                algorithms=[self._algoritmo],
                issuer=self._emisor,
                audience=self._audiencia,
                options={"require": ["exp", "iat", "sub", "sid", "tip"]},
            )
        except jwt.InvalidTokenError as exc:
            registro.info("Token rechazado: %s", type(exc).__name__)
            raise SinPermiso(MENSAJE_INVALIDO) from exc

        if str(contenido.get("tip")) != str(tipo):
            # Un token de acceso presentado donde se espera uno de renovación —o al contrario— no es
            # un error de formato: es un intento de usar un token para lo que no sirve.
            registro.warning("Token del tipo equivocado: %s", contenido.get("tip"))
            raise SinPermiso(MENSAJE_INVALIDO)

        return self._a_claims(contenido)

    def huella(self, token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _a_claims(contenido: dict[str, Any]) -> Claims:
        try:
            return Claims(
                usuario_id=UUID(str(contenido["sub"])),
                negocio_id=UUID(str(contenido["neg"])),
                rol=str(contenido.get("rol") or ""),
                sesion_id=UUID(str(contenido["sid"])),
                tipo=TipoToken(str(contenido["tip"])),
                expira_en=datetime.fromtimestamp(int(contenido["exp"]), tz=UTC),
            )
        except (KeyError, ValueError, TypeError) as exc:
            # Un token firmado correctamente pero con contenido inservible solo puede venir de un
            # cambio de formato mal desplegado, así que conviene verlo en los registros.
            registro.warning("Contenido de token inservible", exc_info=False)
            raise SinPermiso(MENSAJE_INVALIDO) from exc
