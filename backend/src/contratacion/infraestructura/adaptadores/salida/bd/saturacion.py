"""Reconoce el fallo que significa «la base está saturada» y no «esta consulta está mal».

El 2026-10-06 el panel se llenó de «La API respondió 500.» y la causa no estaba en ningún endpoint:
el agrupador de conexiones de Supabase no tenía una sola conexión libre, así que **toda** petición
—incluidas las triviales— fallaba al pedirla. El agotamiento se anunciaba como un error del programa
cuando es lo contrario: el programa está bien, es la dependencia la que no da paso.

Distinguirlos importa porque la respuesta correcta a cada uno es distinta: ante una saturación se
reintenta en unos segundos, y ante un defecto se avisa. Mezclados, el panel manda a la persona a
«algo se rompió» en un caso en el que basta con esperar.

Se clasifica por el **texto** de la excepción y no por su tipo. No es gusto: las cinco formas de
quedarse sin conexión llegan con tipos distintos —unas como `DBAPIError`, la del conjunto propio
como `TimeoutError`— y no comparten ninguna clase común más específica que `SQLAlchemyError`, que
también cubre los errores de sintaxis. El texto es lo único que las separa.
"""

from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError

# Cada señal viene de una pieza distinta, y por eso están todas: cubrir solo la que se vio el primer
# día deja fuera las otras cuatro, que dan el mismo problema con otro mensaje.
#
#   · EMAXCONNSESSION           — el agrupador rechaza una conexión nueva: se alcanzó su tope de
#                                 clientes en modo sesión (quince, en el plan actual).
#   · ECHECKOUTTIMEOUT          — el agrupador no tiene ninguna libre y se rinde tras quince
#                                 segundos de espera.
#   · too many clients          — el tope es del propio PostgreSQL (`max_connections`).
#   · remaining connection slots— PostgreSQL reservando las últimas ranuras para superusuarios.
#   · QueuePool limit           — el tope es el conjunto de conexiones **de este proceso**: aquí
#                                 nadie más tiene la culpa, pero la respuesta correcta también es
#                                 «reintenta», no «el programa está roto».
SENALES_DE_SATURACION: tuple[str, ...] = (
    "emaxconnsession",
    "echeckouttimeout",
    "too many clients",
    "remaining connection slots",
    "queuepool limit",
)


def es_saturacion(excepcion: BaseException) -> bool:
    """`True` si el fallo es «no hay conexiones», y `False` si es cualquier otra cosa.

    Se compara en minúsculas porque el mismo mensaje llega con distinta caja según quién lo emita:
    `asyncpg` lo escribe como `(EMAXCONNSESSION)`, y el agrupador como `(EMAXCONNSESSION)` dentro de
    una frase. La comprobación por subcadena evita depender de esa caja.
    """
    if not isinstance(excepcion, SQLAlchemyError):
        # Un fallo que ni siquiera viene de la capa de base de datos no se puede leer como
        # «saturación»: sería convertir un defecto del programa en un «vuelve a intentarlo».
        return False
    mensaje = str(excepcion).lower()
    return any(senal in mensaje for senal in SENALES_DE_SATURACION)
