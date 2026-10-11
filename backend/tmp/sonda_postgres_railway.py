"""Comprueba si una dirección de Railway habla el protocolo de PostgreSQL.

Por qué esto y no un `psql`
---------------------------
El fallo que hay que distinguir es «la dirección no lleva a ninguna base», y para verlo no hace
falta autenticarse. Se abre un TCP, se envía el saludo de arranque del protocolo de PostgreSQL con
un usuario cualquiera y se mira **qué contesta**:

  - nada (el otro extremo cierra): la dirección existe pero no hay una base detrás;
  - `R`: el servidor pide autenticación. Es la respuesta que se busca: hay un PostgreSQL ahí;
  - `E`: el servidor contesta con un error (contraseña, base inexistente). También sirve.

Y así no hay que escribir ninguna contraseña en ninguna parte para saber si el camino está abierto.

    python tmp/sonda_postgres_railway.py
    python tmp/sonda_postgres_railway.py iriguchi.proxy.rlwy.net:43396
"""

from __future__ import annotations

import socket
import struct
import sys

# Los tres caminos posibles que da la plataforma, y qué es cada uno:
#
#   - el dominio público, en el puerto de la base: así solo funciona si la plataforma enruta TCP
#     crudo al puerto;
#   - el mismo dominio en el 443: es el borde HTTPS de la plataforma, que espera HTTP y no
#     PostgreSQL;
#   - el proxy TCP, que es el camino que la plataforma documenta para entrar desde fuera.
#
# El destino del proxy (el puerto de dentro) es lo que se comprueba aquí: si el proxy apunta a un
# puerto donde no hay nadie escuchando, acepta la conexión y la cierra en el acto.
OBJETIVOS: tuple[tuple[str, int], ...] = (
    ("bd-production-cfe3.up.railway.app", 5432),
    ("bd-production-cfe3.up.railway.app", 443),
    ("iriguchi.proxy.rlwy.net", 54407),
)

ESPERA = 8.0


def _saludo_de_arranque() -> bytes:
    """El primer mensaje que envía un cliente de PostgreSQL al conectarse."""
    cuerpo = b"user\x00sonda\x00database\x00sonda\x00\x00"
    return struct.pack("!ii", len(cuerpo) + 8, 196608) + cuerpo


def _respuesta(host: str, puerto: int) -> str:
    try:
        with socket.create_connection((host, puerto), timeout=ESPERA) as conexion:
            conexion.sendall(_saludo_de_arranque())
            recibido = conexion.recv(1)
    except TimeoutError:
        return "sin respuesta dentro del plazo (¿firewall?)"
    except OSError as error:
        return f"no se pudo abrir: {error}"

    if not recibido:
        return "cerrado sin contestar (no hay una base en ese puerto)"

    if recibido == b"R":
        return "es un PostgreSQL: pide autenticación"
    if recibido == b"E":
        return "es un PostgreSQL: contestó con un error (normal sin credenciales)"
    if recibido in (b"H", b"S"):
        return "parece un servidor HTTP, no una base de datos"
    return f"contestó algo inesperado: {recibido!r}"


def _destinos(argumentos: list[str]) -> tuple[tuple[str, int], ...]:
    """Los destinos a probar: los que se indiquen, o los tres de siempre."""
    if not argumentos:
        return OBJETIVOS
    resultado: list[tuple[str, int]] = []
    for argumento in argumentos:
        host, _, puerto = argumento.partition(":")
        resultado.append((host, int(puerto)))
    return tuple(resultado)


def main() -> None:
    print("destino                                    resultado")
    print("-" * 92)
    for host, puerto in _destinos(sys.argv[1:]):
        destino = f"{host}:{puerto}"
        print(f"{destino:<42} {_respuesta(host, puerto)}")


if __name__ == "__main__":
    main()
