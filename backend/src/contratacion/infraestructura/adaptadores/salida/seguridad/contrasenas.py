"""Adaptador de contraseñas sobre Argon2id.

Argon2id es la recomendación actual porque encarece el ataque por GPU y por memoria: además de
tiempo, exige memoria por intento, así que probar millones de contraseñas en paralelo deja de ser
barato.

Parámetros elegidos y por qué
-----------------------------
`memory_cost = 32 MiB`, `time_cost = 3`, `parallelism = 2`. Los valores por defecto de la biblioteca
piden 64 MiB por comprobación; con varios inicios de sesión a la vez eso son cientos de megas en un
servidor pequeño, que es un modo de caída fácil de provocar. 32 MiB sigue muy por encima de lo que
hace inviable un ataque por diccionario y cabe en la instancia más pequeña prevista.

`verificar` **no lanza** cuando la contraseña no coincide: devuelve `False`. Y cuando la huella
guardada está corrupta o vacía también devuelve `False`. Una fila mal formada no puede volverse un
fallo del servidor, y menos en el camino de autenticación.
"""

from __future__ import annotations

import logging

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

registro = logging.getLogger(__name__)

MEMORIA_KIB = 32 * 1024
COSTO_TIEMPO = 3
PARALELISMO = 2


class ContrasenasArgon2:
    """Implementación del puerto de contraseñas."""

    def __init__(
        self,
        *,
        memoria_kib: int = MEMORIA_KIB,
        costo_tiempo: int = COSTO_TIEMPO,
        paralelismo: int = PARALELISMO,
    ) -> None:
        self._hasher = PasswordHasher(
            time_cost=costo_tiempo,
            memory_cost=memoria_kib,
            parallelism=paralelismo,
        )

    def hash(self, texto: str) -> str:
        return self._hasher.hash(texto)

    def verificar(self, huella: str, texto: str) -> bool:
        if not huella:
            return False
        try:
            return bool(self._hasher.verify(huella, texto))
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False
        except Exception:  # noqa: BLE001 - ningún fallo del hash debe tumbar el inicio de sesión
            registro.warning("Fallo al comprobar una contraseña", exc_info=False)
            return False

    def necesita_rehash(self, huella: str) -> bool:
        if not huella:
            return True
        try:
            return bool(self._hasher.check_needs_rehash(huella))
        except InvalidHashError:
            # Una huella que no se puede interpretar hay que recalcularla en cuanto se pueda.
            return True


# Huella de descarte para igualar tiempos.
#
# Cuando el correo no corresponde a ninguna cuenta, el caso de uso comprueba la contraseña contra
# esta huella en lugar de salir por la puerta rápida. Sin ello, el tiempo de respuesta delataría si
# un correo existe: responder en 2 ms sería «no existe» y en 60 ms «existe y la contraseña está
# mal», y eso convierte el inicio de sesión en un buscador de usuarios.
HUELLA_DESCARTE = ContrasenasArgon2().hash("contrasena-de-descarte-sin-uso")
