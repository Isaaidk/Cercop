"""Días que quedan para entregar proformas, y el semáforo que los resume.

Una ínfima cuantía se adjudica entre las proformas que llegan antes de su fecha límite. Pasada esa
fecha el registro deja de ser una oportunidad y pasa a ser historia, así que el dato que importa no
es la fecha sino **cuántos días quedan**: «29 de septiembre» obliga a contar de cabeza, «faltan 2
días» no.

La regla del semáforo es una sola y vive aquí para que el panel y el archivo de Excel no puedan
pintar el mismo registro de dos colores distintos:

- **7 días o más**: verde, hay margen para preparar la proforma.
- **Menos de 7**: amarillo, hay que ponerse.
- **Menos de 3**: rojo, es para hoy o casi.

    Los mismos tres umbrales están en `frontend/src/utils/plazo.js`. Son dos lenguajes distintos, y
no hay forma de compartir el valor; lo que sí se puede es no duplicar la *regla* en cada pantalla, y
por eso el frontend tiene un único módulo para esto y aquí hay otro.
"""

from __future__ import annotations

from datetime import UTC, datetime

# Umbrales, en días. Se comparan con `>=`, así que 7 es verde y 3 es amarillo.
DIAS_VERDE = 7
DIAS_AMARILLO = 3

NIVEL_VERDE = "verde"
NIVEL_AMARILLO = "amarillo"
NIVEL_ROJO = "rojo"
# Sin fecha límite no se puede decir nada: ni verde ni rojo, simplemente no aplica. Inventar color
# para un dato que falta sería afirmar algo que no se sabe.
NIVEL_SIN_FECHA = "sin"

TEXTO_SIN_FECHA = "Sin fecha límite"


def dias_para_proforma(
    fecha_limite: str | datetime | None, *, ahora: datetime | None = None
) -> int | None:
    """Días completos que quedan hasta la fecha límite. `None` si no hay fecha utilizable.

    Se descuentan los días **completos** que faltan, con el suelo de la división. Importa para que
    un plazo que vence hoy a las 23:00 dé `0` y no `1`: con `1` el semáforo diría que queda un día
    entero y el registro aparece en amarillo cuando en realidad es para hoy.

    Una fecha ya pasada devuelve un número negativo. No se recorta a cero a propósito: «vencida hace
    cuatro días» y «vence hoy» son situaciones distintas, y aplastarlas en el mismo cero borraría la
    diferencia en cuanto alguien quiera mostrarla.
    """
    momento = ahora or datetime.now(UTC)
    limite = _a_fecha(fecha_limite)
    if limite is None:
        return None
    return (limite - momento).days


def nivel_de_plazo(dias: int | None) -> str:
    """Color del semáforo para una cantidad de días. `NIVEL_SIN_FECHA` si no hay dato.

    Una fecha ya vencida cae en rojo, que es lo que corresponde: ya no se puede entregar proforma.
    """
    if dias is None:
        return NIVEL_SIN_FECHA
    if dias >= DIAS_VERDE:
        return NIVEL_VERDE
    if dias >= DIAS_AMARILLO:
        return NIVEL_AMARILLO
    return NIVEL_ROJO


def texto_de_plazo(dias: int | None) -> str:
    """Cómo se dice el plazo en una celda o en una etiqueta."""
    if dias is None:
        return TEXTO_SIN_FECHA
    if dias < 0:
        return f"Vencida hace {abs(dias)} {'día' if abs(dias) == 1 else 'días'}"
    if dias == 0:
        return "Vence hoy"
    return f"{dias} {'día' if dias == 1 else 'días'}"


def _a_fecha(valor: str | datetime | None) -> datetime | None:
    """Convierte el valor almacenado en un instante con zona.

    Se acepta texto porque así es como llega el dato guardado en el JSON del registro, y se acepta
    un `datetime` porque es lo que devuelve la base. Un valor que no se pueda interpretar devuelve
    `None` en lugar de lanzar: un registro con la fecha mal formada debe salir sin semáforo, no
    tumbar la exportación entera de la que forma parte.
    """
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=UTC)
    texto = str(valor).strip()
    if not texto:
        return None
    try:
        momento = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError:
        return None
    return momento if momento.tzinfo else momento.replace(tzinfo=UTC)
