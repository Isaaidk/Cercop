"""Claves de las sesiones vivas.

El cierre por inactividad no lo vigila ningún proceso, y eso es lo importante de este módulo. La
tentación es escribir un barrendero que cada minuto recorra las sesiones y cierre las que llevan
tiempo sin usarse; sería un proceso más que puede caerse, que hay que arrancar en cada réplica y que
recorre filas para decidir algo que el propio almacén ya sabe hacer solo.

Aquí se declara **cómo se llama una sesión viva** y **qué se guarda en su clave**. El tiempo de vida
lo pone quien escribe, y el almacén lo respeta: cuando vence, la clave desaparece sin que nadie
tenga que pasar a borrarla. El cierre es una consecuencia del vencimiento, no una tarea.

Qué se guarda, y por qué tan poco
---------------------------------
Solo el identificador del dueño. El rol, el negocio y el correo viajan **firmados en el token**, así
que repetirlos aquí sería duplicar un dato que ya viene autenticado. Lo que el token no puede decir
por sí solo es que la sesión viva siga siendo de quien la abrió, y eso es exactamente lo que se
comprueba con este valor.
"""

from __future__ import annotations

from uuid import UUID

PREFIJO_SESION_VIVA = "sesion_viva"


def clave_de_sesion(sesion_id: UUID) -> str:
    """Nombre con el que consta que una sesión está abierta."""
    return f"{PREFIJO_SESION_VIVA}:{sesion_id}"


def valor_de_sesion(usuario_id: UUID) -> str:
    """Contenido de la clave: el dueño de la sesión."""
    return str(usuario_id)


def usuario_de_sesion(valor: str) -> UUID | None:
    """Lee el dueño de una clave. `None` si lo guardado no es un identificador.

    Se contempla el caso en vez de dar por hecho que lo guardado es correcto: una clave escrita por
    una versión anterior del sistema, o por un script, no puede convertirse en una excepción que
    tumbe la petición de alguien. Un contenido que no se entiende se trata como una sesión cuyo
    dueño no se puede confirmar, y quien llama decide qué hacer con eso.
    """
    try:
        return UUID(valor)
    except ValueError:
        return None
