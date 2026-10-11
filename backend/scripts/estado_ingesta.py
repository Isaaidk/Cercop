"""¿El worker está trabajando de verdad, o solo está vivo?

La pregunta no se contesta mirando si el proceso está en marcha. Un proceso puede llevar horas
arriba, tener ciclos registrados y **cero filas** escritas: eso es el fallo silencioso, y desde
fuera se parece mucho a que todo va bien. La única forma de distinguirlo es mirar lo que cada ciclo
dejó escrito.

Cada ciclo completo escribe una fila en `sincronizacion` al empezar y la completa al terminar, con
cuatro contadores que juntos cuentan la historia:

* **`peticiones`** — cuántas veces se habló con la fuente oficial. Si es cero, el ciclo no salió de
  casa: está simulado, o la fuente no responde, o el presupuesto se agotó antes de empezar.
* **`nuevos`** — cuántas necesidades entraron que no estaban. Cero es normal en una vuelta corta; es
  la cifra que sube cuando la fuente publica.
* **`actualizados`** — cuántas se revisaron y ya estaban. **Este es el que demuestra trabajo real**:
  para saber que un registro no cambió hay que haberlo leído.
* **`errores`** — y el campo `avisos`, que dice lo que la fuente contestó raro.

Uso:

    python scripts/estado_ingesta.py
    python scripts/estado_ingesta.py --horas 6
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from sqlalchemy import text  # noqa: E402

from contratacion.infraestructura.adaptadores.salida.bd.sesion import (  # noqa: E402
    cerrar_bd,
    obtener_motor,
)

# Lo que dejó la copia el 2026-10-07, cuando se trajeron los datos de la base anterior. Sirve para
# responder a «¿ha entrado algo desde entonces?» sin tener que acordarse de la cifra.
FILAS_DE_LA_COPIA = 110201

CICLOS = """
SELECT f.codigo,
       s.iniciada_en,
       s.terminada_en,
       s.estado,
       s.peticiones,
       s.nuevos,
       s.actualizados,
       s.errores
FROM sincronizacion s
JOIN fuente f ON f.id = s.fuente_id
WHERE s.iniciada_en >= now() - make_interval(hours => :horas)
ORDER BY s.iniciada_en DESC
"""

RESUMEN = """
SELECT f.codigo,
       count(s.id)                                AS ciclos,
       max(s.iniciada_en)                      AS ultimo,
       sum(s.peticiones)                       AS peticiones,
       sum(s.nuevos)                           AS nuevos,
       sum(s.actualizados)                     AS actualizados,
       sum(s.errores)                          AS errores,
       count(s.id) FILTER (WHERE s.estado = 'error') AS fallidos,
       count(s.id) FILTER (WHERE s.terminada_en IS NULL) AS sin_cerrar
FROM fuente f
LEFT JOIN sincronizacion s
       ON s.fuente_id = f.id
      AND s.iniciada_en >= now() - make_interval(hours => :horas)
GROUP BY f.codigo
ORDER BY f.codigo
"""

AVISOS = """
SELECT f.codigo, s.iniciada_en, s.avisos
FROM sincronizacion s
JOIN fuente f ON f.id = s.fuente_id
WHERE s.iniciada_en >= now() - make_interval(hours => :horas)
  AND s.avisos IS NOT NULL
  AND s.avisos::text NOT IN ('[]', 'null')
ORDER BY s.iniciada_en DESC
LIMIT 10
"""


def _minutos(momento: object) -> float | None:
    """Los minutos transcurridos desde ese instante. `None` si no hay instante."""
    if not isinstance(momento, datetime):
        return None

    # Las marcas vienen del servidor y ya traen zona horaria; el `if` está por si alguna consulta
    # devolviera una fecha ingenua, que restada contra una con zona reventaría.
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=UTC)
    return max(0.0, (datetime.now(UTC) - momento).total_seconds() / 60)


def _hace(momento: object) -> str:
    """Cuánto hace de algo, en la unidad que se entiende de un vistazo."""
    minutos = _minutos(momento)
    if minutos is None:
        return "nunca"

    if minutos < 1.5:
        return f"{minutos * 60:.0f} s"
    if minutos < 90:
        return f"{minutos:.0f} min"
    if minutos < 2880:
        return f"{minutos / 60:.1f} h"
    return f"{minutos / 1440:.1f} días"


async def principal() -> int:
    analizador = argparse.ArgumentParser(description="Comprueba si la ingesta trabaja de verdad.")
    analizador.add_argument(
        "--horas", type=int, default=24, help="Ventana a mirar. Por defecto 24."
    )
    analizador.add_argument(
        "--cadencia-min",
        type=int,
        default=15,
        help="Minutos que puede estar el worker sin empezar un ciclo antes de darlo por parado.",
    )
    argumentos = analizador.parse_args()
    ventana = {"horas": argumentos.horas}

    motor = obtener_motor()
    try:
        async with motor.connect() as conexion:
            ahora: datetime = (await conexion.execute(text("SELECT now()"))).scalar_one()
            print(f"Hora del servidor de la base: {ahora:%Y-%m-%d %H:%M:%S}\n")

            print(f"Ciclos de las últimas {argumentos.horas} h:")
            print(
                f"  {'fuente':<7} {'iniciado':<17} {'estado':<8} {'hace':>8} "
                f"{'petic.':>7} {'nuevos':>7} {'act.':>7} {'err.':>5}"
            )
            print("  " + "-" * 76)
            ciclos = (await conexion.execute(text(CICLOS), ventana)).all()
            if not ciclos:
                print("  (ninguno)")
            for codigo, iniciada, _fin, estado, peticiones, nuevos, act, errores in ciclos:
                print(
                    f"  {codigo:<7} {iniciada:%Y-%m-%d %H:%M} {estado:<8} {_hace(iniciada):>8} "
                    f"{peticiones:>7} {nuevos:>7} {act:>7} {errores:>5}"
                )

            print("\nResumen de la ventana, por fuente:")
            resumen = (await conexion.execute(text(RESUMEN), ventana)).all()
            totales = {
                "ciclos": 0,
                "peticiones": 0,
                "nuevos": 0,
                "revisados": 0,
                "fallidos": 0,
                "en_curso": 0,
            }
            for fila in resumen:
                codigo, cuantos, ultimo, pets, nvos, act, errs, falls, abiertos = fila
                totales["ciclos"] += int(cuantos)
                totales["peticiones"] += int(pets or 0)
                totales["nuevos"] += int(nvos or 0)
                totales["revisados"] += int(act or 0)
                totales["fallidos"] += int(falls or 0)
                totales["en_curso"] += int(abiertos or 0)
                print(
                    f"  {codigo:<7} {cuantos:>3} ciclos · último hace {_hace(ultimo):>8} · "
                    f"{pets or 0} peticiones · {nvos or 0} nuevos · {act or 0} revisados · "
                    f"{errs or 0} errores · {falls} fallidos · {abiertos} sin cerrar"
                )

            total: int = (
                await conexion.execute(text("SELECT count(*) FROM registro"))
            ).scalar_one()
            print(
                f"\nRegistros en el histórico: {total} "
                f"({total - FILAS_DE_LA_COPIA:+d} desde la copia)"
            )

            avisos = (await conexion.execute(text(AVISOS), ventana)).all()
            print(f"\nAvisos de la fuente en la ventana: {len(avisos)}")
            for codigo, iniciada, contenido in avisos:
                print(f"  {codigo} {iniciada:%Y-%m-%d %H:%M} · {contenido}")

            # El último ciclo de todos, cruzando las fuentes. Es el número del que depende el
            # veredicto: los ciclos de la ventana pueden haber llegado dentro de una copia de otra
            # base, y contarlos como actividad propia es exactamente el error que hay que evitar.
            ultimo_de_todos = max(
                (fila[2] for fila in resumen if fila[2] is not None),
                default=None,
            )
            print(f"\nÚltimo ciclo de cualquier fuente: hace {_hace(ultimo_de_todos)}")

            print()
            print(
                _veredicto(
                    minutos_sin_ciclo=_minutos(ultimo_de_todos),
                    cadencia_min=argumentos.cadencia_min,
                    **totales,
                )
            )
            return 0
    finally:
        await cerrar_bd()


def _veredicto(
    *,
    ciclos: int,
    peticiones: int,
    nuevos: int,
    revisados: int,
    fallidos: int,
    en_curso: int,
    minutos_sin_ciclo: float | None,
    cadencia_min: int,
) -> str:
    """La frase que contesta a la pregunta. Sin adornos y sin optimismo.

    Lo primero que mira es **cuándo fue el último ciclo**, no cuántos hay en la ventana. La razón es
    un error que ya se cometió una vez: después de traer los datos de otra base, la tabla de
    sincronizaciones llega llena de ciclos ajenos, y contarlos como actividad propia da un
    «trabaja de verdad» con el worker parado. Los ciclos viejos no son prueba de nada; lo único que
    prueba algo es un ciclo **de hace un momento**.
    """
    if minutos_sin_ciclo is None:
        return (
            "VEREDICTO: no hay ni un ciclo registrado, ni siquiera antiguo. O el worker no ha "
            "arrancado nunca contra esta base, o no puede escribir en ella."
        )

    if minutos_sin_ciclo > cadencia_min:
        return (
            f"VEREDICTO: el worker NO está trabajando. Su último ciclo empezó hace "
            f"{minutos_sin_ciclo:.0f} min, cuando la cadencia esperada no pasa de "
            f"{cadencia_min} min. Los ciclos que aparecen en la ventana son anteriores y no "
            "cuentan: mira los registros del servicio, no la base."
        )

    if not ciclos:
        return "VEREDICTO: hay un ciclo reciente pero fuera de la ventana pedida. Amplía `--horas`."

    # Un ciclo abierto todavía no tiene contadores: `peticiones`, `nuevos` y `actualizados` se
    # escriben al **cerrarlo**. Juzgar por ellos mientras está en curso da un «no hace nada» falso
    # justo cuando sí está haciendo algo.
    if en_curso:
        return (
            f"VEREDICTO: está trabajando. Hay {en_curso} ciclo(s) sin cerrar, el último empezó "
            f"hace {minutos_sin_ciclo:.1f} min. Los contadores se escriben al cerrarse, así que "
            "estarán llenos dentro de un momento: vuelve a mirar en unos minutos."
        )

    if peticiones == 0:
        return (
            "VEREDICTO: hay ciclos, pero ninguno hizo una sola petición a la fuente. Eso no es "
            "trabajo: es un ciclo que se cierra solo. Revisa los avisos y el presupuesto de "
            "peticiones del ciclo."
        )

    if fallidos == ciclos:
        return (
            "VEREDICTO: todos los ciclos de la ventana terminaron en error. El worker está vivo y "
            "alcanza la fuente, pero no consigue cerrar el trabajo: mira los avisos."
        )

    if revisados == 0 and nuevos == 0:
        return (
            "VEREDICTO: los ciclos salieron a la fuente y volvieron, pero no revisaron ni "
            "encontraron nada. Puede ser una ventana sin novedades, o que la consulta no esté "
            "devolviendo registros."
        )

    return (
        f"VEREDICTO: la ingesta trabaja de verdad. {peticiones} peticiones a la fuente, {nuevos} "
        f"registros nuevos y {revisados} revisados en la ventana. No es trabajo simulado."
    )


if __name__ == "__main__":
    raise SystemExit(asyncio.run(principal()))
