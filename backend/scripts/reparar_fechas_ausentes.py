"""Repara la fecha de publicación de los registros que quedaron sin ella.

Por qué existe
--------------
`_fecha` no reconocía el ISO 8601 completo —el que usan los datos abiertos, con la `T` y el
desfase horario—, así que devolvía `None` y el campo **se descartaba sin ruido** al guardar. Las
filas afectadas ya están en la base, y volver a ingestarlas no es seguro: el planificador pide solo
la ventana reciente, así que un proceso de hace meses no se vuelve a consultar nunca y habría
quedado sin fecha para siempre.

La reparación es posible porque la ingesta guarda el payload íntegro en `registro.crudo`. Este guion
vuelve a aplicar **los mismos mapeos y el mismo conversor** que la ingesta sobre ese crudo, de modo
que el valor que escribe es exactamente el que se habría escrito si el conversor hubiera funcionado.
No se inventa nada: si la fecha sigue sin interpretarse, la fila se deja como está y se cuenta.

Qué toca y qué no
-----------------
Solo escribe en filas cuya fecha está **vacía** y en las que el crudo sí la trae. Una fila que ya
tiene fecha no se toca, ni siquiera para reescribirla igual.

Uso:

    .\\.venv\\Scripts\\python.exe scripts\\reparar_fechas_ausentes.py

Con `--simular` no escribe nada y solo informa de lo que haría.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from typing import Any

sys.path.insert(0, "src")

from sqlalchemy import text

from contratacion.aplicacion.mapeo import MapeoCampo, aplicar
from contratacion.infraestructura.adaptadores.salida.bd.contexto import sin_contexto
from contratacion.infraestructura.adaptadores.salida.bd.sesion import cerrar_bd, obtener_motor

CAMPOS = ("fecha", "fecha_hora")

CONSULTA_MAPEOS = """
SELECT f.codigo AS fuente, cm.clave_cruda, cm.campo_canonico, cm.tipo_dato,
       cm.transformacion, cm.requerido
FROM campo_mapeo cm
JOIN fuente f ON f.id = cm.fuente_id
ORDER BY f.codigo, cm.orden
"""

CONSULTA_PENDIENTES = """
SELECT r.id, r.crudo, f.codigo AS fuente
FROM registro r
JOIN fuente f ON f.id = r.fuente_id
WHERE r.fecha_publicacion IS NULL AND r.crudo IS NOT NULL
ORDER BY f.codigo, r.id
"""

ACTUALIZAR = """
UPDATE registro
SET fecha_publicacion = :fecha,
    datos = datos || jsonb_build_object('fecha_publicacion', CAST(:texto AS text))
WHERE id = :id
"""


def _mapeos_por_fuente(filas: list[Any]) -> dict[str, list[MapeoCampo]]:
    por_fuente: dict[str, list[MapeoCampo]] = {}
    for fila in filas:
        por_fuente.setdefault(fila.fuente, []).append(
            MapeoCampo(
                clave_cruda=fila.clave_cruda,
                campo_canonico=fila.campo_canonico,
                tipo_dato=fila.tipo_dato,
                transformacion=fila.transformacion or {},
                requerido=fila.requerido,
            )
        )
    return por_fuente


async def main() -> None:
    simular = "--simular" in sys.argv
    motor = obtener_motor()

    async with sin_contexto(motor) as conexion:
        mapeos = _mapeos_por_fuente(list((await conexion.execute(text(CONSULTA_MAPEOS))).all()))
        pendientes = list((await conexion.execute(text(CONSULTA_PENDIENTES))).all())

    print("=" * 66)
    print("Reparación de fechas ausentes" + ("  (simulación)" if simular else ""))
    print("=" * 66)

    if not pendientes:
        print("  No hay ningún registro con la fecha vacía. Nada que hacer.")
        await cerrar_bd()
        return

    print(f"  Registros con la fecha vacía: {len(pendientes)}")

    reparados = 0
    sin_dato: dict[str, int] = {}

    for fila in pendientes:
        lista = mapeos.get(fila.fuente, [])
        crudo = fila.crudo if isinstance(fila.crudo, dict) else json.loads(fila.crudo or "{}")
        datos, _ = aplicar(lista, crudo)
        valor = datos.get("fecha_publicacion")

        if not valor:
            sin_dato[fila.fuente] = sin_dato.get(fila.fuente, 0) + 1
            continue

        reparados += 1
        if simular:
            continue

        # El controlador quiere un `datetime`, no el texto ISO. Es el mismo valor: se pasa el objeto
        # para la columna con zona horaria y el texto para el dato canónico, que es lo que hace la
        # ingesta y por tanto lo que dejan las dos formas de escribir coincidiendo.
        async with sin_contexto(motor) as conexion:
            await conexion.execute(
                text(ACTUALIZAR),
                {"id": fila.id, "fecha": datetime.fromisoformat(valor), "texto": valor},
            )

    print(f"  Reparados: {reparados}")
    for fuente, cuantos in sorted(sin_dato.items()):
        print(f"  Sin fecha recuperable en {fuente}: {cuantos}")

    # Segunda pasada: es la única forma de demostrar que la escritura ocurrió de verdad y que el
    # valor quedó legible para las consultas, en lugar de dar por bueno el `UPDATE`.
    if not simular and reparados:
        async with sin_contexto(motor) as conexion:
            quedan: int = (
                await conexion.execute(
                    text(
                        """
                        SELECT count(*) FROM registro
                        WHERE fecha_publicacion IS NULL AND crudo IS NOT NULL
                        """
                    )
                )
            ).scalar_one()
            muestra = (
                await conexion.execute(
                    text(
                        """
                        SELECT f.codigo AS fuente, r.fecha_publicacion,
                               r.datos ->> 'fecha_publicacion' AS dato
                        FROM registro r JOIN fuente f ON f.id = r.fuente_id
                        WHERE f.codigo = 'OCDS'
                        ORDER BY r.fecha_publicacion DESC NULLS LAST
                        LIMIT 3
                        """
                    )
                )
            ).all()
        print(f"  Quedan con la fecha vacía: {quedan}")
        print("  Comprobación sobre OCDS:")
        for fila in muestra:
            print(f"    {fila.fuente}: columna={fila.fecha_publicacion} dato={fila.dato}")

    await cerrar_bd()


asyncio.run(main())
