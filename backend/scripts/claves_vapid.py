"""Genera el par de claves VAPID de las notificaciones web.

    python scripts/claves_vapid.py > /ruta/privada/vapid.env

Escribe dos líneas, `VAPID_PUBLICA=…` y `VAPID_PRIVADA=…`, listas para las variables del API
(la pública) y del worker (las dos). La privada no se imprime en ningún otro sitio ni se guarda
en el repositorio: quien la tenga puede mandar notificaciones en nombre de CercoApp.
"""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def _b64(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode()


def main() -> None:
    privada = ec.generate_private_key(ec.SECP256R1())
    numero = privada.private_numbers().private_value.to_bytes(32, "big")
    publica = privada.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    print(f"VAPID_PUBLICA={_b64(publica)}")
    print(f"VAPID_PRIVADA={_b64(numero)}")


if __name__ == "__main__":
    main()
