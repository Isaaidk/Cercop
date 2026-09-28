"""Puertos de seguridad: contraseñas y tokens.

La aplicación pide «comprueba esta contraseña» y «emite un token para este usuario». No sabe si
detrás hay Argon2 y JWT, y no debería: cambiar de biblioteca de hash o de formato de token no debe
tocar ni una línea de los casos de uso.

**Este diseño permite probar la autenticación sin criptografía real.** Los dobles de prueba
implementan estos contratos con comparaciones de texto y tokens falsos, así que las pruebas de los
casos de uso son rápidas y deterministas, y la criptografía se prueba aparte y en su sitio.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID


class TipoToken(StrEnum):
    """Para qué sirve un token.

    La distinción no es cosmética: un token de **acceso** permite leer durante minutos; uno de
    **renovación** permite obtener accesos nuevos durante días. Si un token de acceso sirviera
    para renovar, robar uno de minutos daría acceso indefinido.
    """

    ACCESO = "acceso"
    REFRESCO = "refresco"


@dataclass(frozen=True, slots=True)
class Claims:
    """Contenido verificado de un token.

    El `negocio_id` viaja **dentro del token firmado**, nunca como parámetro de la petición: es la
    regla R-04 y es lo que impide que un cliente elija a qué negocio pertenece.
    """

    usuario_id: UUID
    negocio_id: UUID
    rol: str
    sesion_id: UUID
    tipo: TipoToken
    expira_en: datetime


class ServicioContrasenas(Protocol):
    """Derivación y comprobación de contraseñas."""

    def hash(self, texto: str) -> str:
        """Devuelve la huella que se guarda. Nunca el texto, ni un hash reversible."""
        ...

    def verificar(self, huella: str, texto: str) -> bool:
        """Comprueba si el texto corresponde a la huella, en tiempo constante."""
        ...

    def necesita_rehash(self, huella: str) -> bool:
        """¿La huella se calculó con parámetros que ya están desactualizados?

        Permite subir el coste del algoritmo sin invalidar las contraseñas existentes: al iniciar
        sesión correctamente, se vuelve a calcular con los parámetros nuevos.
        """
        ...


class ServicioTokens(Protocol):
    """Emisión y verificación de tokens firmados."""

    def emitir(self, claims: Claims, ttl_seg: int) -> str:
        """Devuelve un token firmado con esa vigencia."""
        ...

    def verificar(self, token: str, tipo: TipoToken) -> Claims:
        """Devuelve las declaraciones, o lanza `SinPermiso` si el token no sirve.

        Debe rechazar por firma inválida, por caducidad, por algoritmo distinto del esperado y por
        tipo de token distinto del pedido. El algoritmo se comprueba de forma explícita: aceptar el
        que declara el propio token es la vulnerabilidad clásica de esta tecnología.
        """
        ...

    def huella(self, token: str) -> str:
        """Huella del token, para guardarla y poder detectar su reutilización.

        No se guarda el token en claro: si la base se filtra, los tokens guardados no sirven para
        suplantar a nadie. Y como el token ya es un valor aleatorio de alta entropía, una huella
        rápida es suficiente aquí; no hace falta derivar una contraseña.
        """
        ...
