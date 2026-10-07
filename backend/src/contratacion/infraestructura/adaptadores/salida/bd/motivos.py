"""Traduce un fallo de conexión a una frase que se pueda leer, **sin exponer nada de la cadena**.

Existe por un caso concreto que costó un despliegue entero: el registro del API decía
`Postgres no responde` y nada más. La causa real —que el nombre del servidor no se resolvía porque
el servicio tenía otro nombre— estaba dentro de la excepción, que no se imprimía por miedo a que el
mensaje llevara la contraseña. El resultado era lo peor de los dos mundos: ni se diagnosticaba ni se
protegía nada, porque el servidor se quedaba caído igual.

La solución es **no devolver nunca el mensaje original**: se clasifica el fallo en una lista corta
de causas y se devuelve esa frase. Así se diagnostica y no hay nada que se pueda filtrar.

Se clasifica primero por **tipo** (los casos que se reconocen solos: resolución de nombres, conexión
rechazada, tiempo agotado) y después por el **texto**, que es lo único que distingue unos errores de
otros dentro del mismo tipo.
"""

from __future__ import annotations

import socket

from contratacion.infraestructura.adaptadores.salida.bd.saturacion import es_saturacion

# Señales por texto, en orden de comprobación. La primera que encaje gana, así que las más
# específicas van delante: «authentication failed» antes que «failed», y el cifrado antes que el
# tiempo agotado —un fallo de TLS también termina en tiempo agotado si nadie lo mira antes—.
SENALES: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        ("password authentication", "authentication failed", "invalid password", "invalidpassword"),
        "credenciales rechazadas (usuario o contraseña no coinciden)",
    ),
    (
        ('role "', 'database "', "unknown database"),
        "el usuario o la base de datos no existen en ese servidor",
    ),
    (
        ("ssl", "tls", "certificate"),
        "problema de cifrado TLS (el servidor puede exigirlo, o el certificado no es de fiar)",
    ),
    (
        ("prepared statement", "prepared statements"),
        "el agrupador de conexiones no admite sentencias preparadas",
    ),
    (
        ("connect call failed", "connection refused", "connection reset by peer"),
        "el servidor no acepta conexiones en ese puerto",
    ),
    (
        ("timeout", "timed out"),
        "se agotó el tiempo de espera (¿la dirección es correcta? ¿hay cortafuegos?)",
    ),
    (
        ("getaddrinfo", "name or service not known", "nodename nor servname", "no such host"),
        "no se pudo resolver el nombre del servidor (revisa la dirección)",
    ),
    (
        ("controlador", "driver", "unsupported"),
        "el controlador de la base de datos no está disponible o no es compatible",
    ),
)


def motivo_legible(excepcion: BaseException) -> str:
    """Una frase corta que dice qué pasó, sin el mensaje original y sin nada que se pueda filtrar.

    El texto que se devuelve es **de este archivo**, nunca el de la excepción: una contraseña mal
    puesta aparece dentro de la cadena de conexión de algunos errores, y esa cadena acaba en los
    registros del servidor y en las capturas de pantalla.
    """
    if es_saturacion(excepcion):
        return "no hay conexiones libres (el conjunto del proceso o el del proveedor están al tope)"

    # Los tipos que se reconocen solos. Se comprueban antes que el texto porque son exactos.
    if isinstance(excepcion, socket.gaierror):
        return "no se pudo resolver el nombre del servidor (revisa la dirección)"
    if isinstance(excepcion, ConnectionRefusedError):
        return "el servidor no acepta conexiones en ese puerto"
    if isinstance(excepcion, TimeoutError):
        return "se agotó el tiempo de espera (¿la dirección es correcta? ¿hay cortafuegos?)"

    # Y después el texto, en minúsculas porque la caja cambia según quién lo escriba.
    mensaje = str(excepcion).lower()
    for senales, motivo in SENALES:
        if any(senal in mensaje for senal in senales):
            return motivo

    # Nada reconocido: se dice **el tipo** y se calla el mensaje. Un nombre de excepción no lleva
    # datos, y sigue diciendo más que «no responde».
    return f"fallo de conexión ({type(excepcion).__name__})"
