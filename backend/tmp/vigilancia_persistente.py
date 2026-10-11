"""Ejecuta la vuelta de vigilancia de NCO esperando a que el bloqueo quede libre.

El `worker` del despliegue toma el bloqueo de NCO casi todo el rato, así que un intento suelto cae
dentro de su ciclo y se omite. Esto reintenta con una espera corta hasta colarse en la ventana en que
lo suelta.

Por qué merece la pena esperar: el listado de necesidades **solo publica lo vigente** y la fuente no
guarda histórico. Una necesidad que no se capture antes de que venza su plazo de proformas se pierde
para siempre, así que cada minuto que pasa con el listado sin leer es pérdida irreversible, no un
retraso.

Se ejecuta con `DATABASE_URL` apuntando a la base donde se quiera escribir:

    python tmp/vigilancia_persistente.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
INTENTOS = 25
ESPERA_SEG = 8.0
SENAL_OCUPADO = "Otra réplica"


async def _intento() -> str:
    """Lanza una vuelta de vigilancia y devuelve lo que escribió."""
    proceso = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "contratacion.tareas.worker",
        "--vigilancia",
        cwd=str(RAIZ),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=dict(os.environ),
    )
    salida, _ = await proceso.communicate()
    return salida.decode("utf-8", "replace")


async def principal() -> None:
    for numero in range(1, INTENTOS + 1):
        texto = await _intento()
        if SENAL_OCUPADO not in texto:
            print(f"\nIntentos hasta conseguirlo: {numero}\n")
            print(texto)
            return
        print(f"  intento {numero}: el bloqueo sigue ocupado", flush=True)
        if numero < INTENTOS:
            await asyncio.sleep(ESPERA_SEG)

    print(
        f"\nEl bloqueo siguió ocupado en los {INTENTOS} intentos "
        f"({INTENTOS * ESPERA_SEG / 60:.0f} minutos). El worker del despliegue está atrapado dentro "
        "de su ciclo y no llegó a soltarlo en ningún hueco."
    )
    sys.exit(1)


if __name__ == "__main__":
    asyncio.run(principal())
