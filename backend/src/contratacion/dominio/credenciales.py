"""Reglas de las credenciales de acceso.

Una contraseña **no se guarda**: se guarda una huella que solo sirve para comprobarla. Lo que decide
si una contraseña es aceptable vive aquí, sin depender de la biblioteca de hash: así se puede probar
sin instalarla y la política no se puede saltar cambiando de biblioteca.

Sobre el bloqueo tras varios fallos
-----------------------------------
Bloquear la cuenta es la respuesta habitual y **también es un ataque**: cualquiera que conozca el
correo de alguien puede dejarlo fuera del sistema escribiendo mal su contraseña a propósito. Por eso
el bloqueo es **temporal** y corto: encarece la fuerza bruta sin regalar una denegación de servicio
permanente.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from contratacion.dominio.errores import DatoInvalido

LONGITUD_MINIMA = 12
# Argon2 no tiene límite de entrada, pero procesar un texto de megabytes agota la CPU del servidor.
# El tope es de generosidad, no de seguridad.
LONGITUD_MAXIMA = 128
# Variedad mínima de caracteres distintos. No se exigen «mayúscula, número y símbolo» porque empuja
# a patrones predecibles («Password1!»); se exige longitud y se penaliza lo obvio.
CARACTERES_DISTINTOS_MINIMOS = 4

INTENTOS_ANTES_DE_BLOQUEO = 5
MINUTOS_DE_BLOQUEO = 15

# Las contraseñas más usadas del mundo, en minúsculas y sin acentos. No pretende ser exhaustiva: es
# el filtro que atrapa el caso habitual sin obligar a mantener un diccionario enorme ni a consultar
# un servicio externo en cada cambio.
OBVIAS = frozenset(
    {
        "contrasena",
        "contraseña",
        "password",
        "contrasenasegura",
        "administrador",
        "quertyuiop",
        "qwertyuiop",
        "123456789012",
        "1234567890123",
        "abcdefghijkl",
        "iloveyou1234",
        "bienvenido123",
        "contratacion",
        "sercop123456",
    }
)


def validar_contrasena(texto: str, *, email: str | None = None) -> None:
    """Comprueba la política y lanza `DatoInvalido` con el motivo concreto.

    El mensaje explica **qué** falta, no solo que está mal: una política que dice «contraseña
    inválida» obliga al usuario a adivinar.
    """
    if len(texto) < LONGITUD_MINIMA:
        raise DatoInvalido(f"La contraseña debe tener al menos {LONGITUD_MINIMA} caracteres.")
    if len(texto) > LONGITUD_MAXIMA:
        raise DatoInvalido(f"La contraseña no puede superar {LONGITUD_MAXIMA} caracteres.")
    if len(set(texto)) < CARACTERES_DISTINTOS_MINIMOS:
        raise DatoInvalido(
            "La contraseña repite demasiado los mismos caracteres. Usa al menos "
            f"{CARACTERES_DISTINTOS_MINIMOS} caracteres distintos."
        )

    plegada = texto.strip().lower()
    if plegada in OBVIAS:
        raise DatoInvalido("Esa contraseña aparece en las listas de las más usadas. Elige otra.")

    if email:
        # Una contraseña que contiene el propio correo es pública para cualquiera que lo conozca.
        usuario_del_correo = email.split("@", 1)[0].strip().lower()
        if len(usuario_del_correo) >= 4 and usuario_del_correo in plegada:
            raise DatoInvalido("La contraseña no puede contener tu correo electrónico.")


def esta_bloqueada(bloqueado_hasta: datetime | None, momento: datetime) -> bool:
    """¿La cuenta está en periodo de bloqueo temporal?"""
    return bloqueado_hasta is not None and bloqueado_hasta > momento


def siguiente_bloqueo(intentos_fallidos: int, momento: datetime) -> datetime | None:
    """Instante hasta el que bloquear, o `None` si aún no toca.

    Devuelve `None` mientras no se alcance el umbral: bloquear al primer fallo convertiría un error
    de tecleo en un cierre de sesión, que es lo contrario de lo que quiere un usuario.
    """
    if intentos_fallidos < INTENTOS_ANTES_DE_BLOQUEO:
        return None
    return momento + timedelta(minutes=MINUTOS_DE_BLOQUEO)


def intentos_tras_fallo(intentos_actuales: int) -> int:
    """Contador de fallos tras un intento incorrecto más."""
    return max(0, intentos_actuales) + 1
