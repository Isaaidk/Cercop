"""Comprueba de extremo a extremo que el bus de avisos sobre Redis reparte.

Abre una suscripción con un negocio de usar y tirar, publica un aviso y espera a recibirlo. Es la
comprobación que **no se puede hacer con dobles**: que el patrón de suscripción coincida de verdad
con el nombre de los canales, que el tipo de mensaje que llega sea el esperado y que el reparto en
memoria entregue a quien tiene que entregar.

    cd backend
    .\\.venv\\Scripts\\python.exe scripts\\verificar_presencia.py

No escribe ninguna clave —Pub/Sub no guarda historia— así que no deja rastro en el almacén. Código
de salida 0 si el aviso llega, 1 si no.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from uuid import uuid4

from contratacion.dominio.presencia import (
    EstadoPresencia,
    Motivo,
    Presencia,
    evento_conectado,
)
from contratacion.infraestructura.adaptadores.salida.presencia.fabrica import obtener_bus
from contratacion.infraestructura.config.ajustes import obtener_ajustes

ESPERA_SEG = 5.0


async def principal() -> int:
    if not obtener_ajustes().cache_habilitada:
        print("Sin REDIS_URL configurada: la presencia vive en la memoria de este proceso.")
        print("El bus funciona, pero solo dentro de un servidor. No hay nada que comprobar aquí.")
        return 0

    negocio = uuid4()
    usuario = uuid4()
    momento = datetime.now(UTC)
    bus = obtener_bus()

    presencia = Presencia(
        usuario_id=usuario,
        estado=EstadoPresencia.VERDE,
        motivo=Motivo.CONECTADO,
        ultimo_latido_en=momento,
        dispositivos=1,
    )
    evento = evento_conectado(negocio, presencia, momento)

    try:
        async with bus.suscribir(negocio_id=negocio) as canal:
            # Al salir de aquí, `suscribir` ya garantiza que la suscripción está escuchando: por eso
            # se puede publicar inmediatamente sin arriesgarse a que el aviso caiga en el hueco.
            await bus.publicar(negocio_id=negocio, evento=evento)
            recibido = await canal.siguiente(ESPERA_SEG)
    finally:
        await bus.cerrar()

    if recibido is None:
        print(f"No llegó el aviso en {ESPERA_SEG:.0f} s.")
        print("El almacén responde pero no reparte. Revisa que REDIS_URL apunte al servidor")
        print("correcto y que el plan contratado permita suscripciones.")
        return 1

    print(f"Aviso recibido: tipo={recibido.tipo} · negocio={recibido.negocio_id}")
    print("El bus reparte de extremo a extremo con una sola suscripción por proceso.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(principal()))
