"""Averigua con qué cifrado se puede abrir la base de origen desde el controlador.

`motivo_legible` traduce los fallos de conexión a frases que se entienden, y eso está bien para
quien lee un registro, pero no para diagnosticar: «problema de cifrado TLS» puede ser que el
servidor exija cifrado, que lo rechace o que el certificado no cuadre. Aquí se prueba cada forma y
se enseña el error de verdad, con la contraseña tachada.
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import asyncpg  # type: ignore[import-untyped]

from contratacion.infraestructura.adaptadores.salida.bd.sesion import normalizar_url_bd
from contratacion.infraestructura.config.ajustes import obtener_ajustes

FORMAS: tuple[tuple[str, object], ...] = (
    ("True", True),
    ("prefer", "prefer"),
    ("False", False),
)


def _tachar(texto: str) -> str:
    """Quita cualquier credencial que venga dentro de un mensaje de error."""
    return re.sub(r"://[^@\s]*@", "://***@", texto)


async def principal() -> None:
    url = normalizar_url_bd(obtener_ajustes().database_url)
    print(f"Parámetros de la dirección: {dict(url.query)}")

    dsn = url.set(query={}).set(drivername="postgresql").render_as_string(hide_password=False)
    for etiqueta, cifrado in FORMAS:
        try:
            conexion = await asyncpg.connect(dsn=dsn, ssl=cifrado)
        except Exception as error:  # noqa: BLE001 - es una sonda: interesa cualquier fallo
            print(f"  ssl={etiqueta:<7} {type(error).__name__}: {_tachar(str(error))[:180]}")
            continue
        try:
            print(f"  ssl={etiqueta:<7} correcto: {await conexion.fetchval('SELECT 1')}")
        finally:
            await conexion.close()


if __name__ == "__main__":
    asyncio.run(principal())
