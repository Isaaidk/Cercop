"""Comprueba, contra la base, lo que el relleno de OCDS tiene que haber dejado.

    .\\.venv\\Scripts\\python.exe scripts\\verificar_relleno.py

Existe porque el relleno comparte la base con el worker y hay dos cosas que no se pueden verificar
en el propio guion, porque dependen de lo que el worker haga **después** o de lo que ya haya en la
base:

1. **La marca de agua no se movió.** La marca de agua no vive en la tabla de la fuente: es el
   `watermark_fecha` de la sincronización más reciente con estado `ok` o `parcial`, y un ciclo
   parcial escribe en su fila la marca **anterior**, no un «ahora». De ahí que el relleno se declare
   parcial: una tanda lee el principio del año, no el final del listado, así que no puede declararse
   al día. Si lo hiciera, el ciclo siguiente leería las dos páginas de siempre y lo publicado
   durante el relleno se perdería en silencio.
2. **Las filas entraron y están vigentes.** Un relleno que insertara filas ya cerradas —o que las
   marcara cerradas por leer solo una parte del listado— dejaría el panel con datos que no salen.
   Por eso el relleno **no** declara `listado_completo`: declararlo cerraría como «ya no vigente»
   casi todo lo que hay en la base.

Es de solo lectura: no escribe nada.
"""

from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, "src")

from sqlalchemy import text

from contratacion.infraestructura.adaptadores.salida.bd.sesion import cerrar_bd, obtener_motor

CODIGO = "OCDS"
FILAS = """
    SELECT s.iniciada_en, s.estado, s.peticiones, s.nuevos, s.actualizados, s.watermark_fecha,
           jsonb_array_length(s.avisos) AS avisos
    FROM sincronizacion s
    JOIN fuente f ON f.id = s.fuente_id
    WHERE f.codigo = :codigo
    ORDER BY s.iniciada_en DESC
    LIMIT :limite
"""


async def main() -> int:
    motor = obtener_motor()
    async with motor.connect() as conexion:
        fuente = (
            await conexion.execute(
                text(
                    "SELECT intervalo_min, presupuesto_peticiones_ciclo, actualizado_en "
                    "FROM fuente WHERE codigo = :codigo"
                ),
                {"codigo": CODIGO},
            )
        ).first()
        print(f"Fuente {CODIGO}")
        if fuente is None:
            print("  no existe: el worker no ha corrido nunca")
            await cerrar_bd()
            return 1
        print(f"  configuración: cada {fuente[0]} min · {fuente[1]} peticiones por ciclo")
        print(f"  fila actualizada por última vez: {fuente[2]:%Y-%m-%d %H:%M:%S}")

        sincronizaciones = (
            await conexion.execute(text(FILAS), {"codigo": CODIGO, "limite": 12})
        ).all()
        print("\nÚltimas 12 sincronizaciones (manda la marca de la última ok o parcial: el relleno")
        print("escribe en su fila la marca anterior, no un «ahora»)")
        for fila in sincronizaciones:
            marca = f"{fila[5]:%Y-%m-%d %H:%M:%S}" if fila[5] else "—"
            avisos = f" · {fila[6]} avisos" if fila[6] else ""
            print(
                f"  {fila[0]:%Y-%m-%d %H:%M:%S} · {fila[1]:8} · {fila[2]:3} pet. · "
                f"{fila[3]:5} nuevas · {fila[4]:5} actualizadas · agua {marca}{avisos}"
            )

        datos = (
            await conexion.execute(
                text(
                    "SELECT count(*) AS total, count(*) FILTER (WHERE r.es_vigente) AS vigentes, "
                    "min(r.fecha_publicacion) AS primera, max(r.fecha_publicacion) AS ultima "
                    "FROM registro r JOIN fuente f ON f.id = r.fuente_id WHERE f.codigo = :codigo"
                ),
                {"codigo": CODIGO},
            )
        ).first()
        print(f"\nRegistros de {CODIGO}")
        if datos is None or not datos[0]:
            print("  ninguno")
        else:
            print(f"  total: {datos[0]} · vigentes: {datos[1]}")
            print(f"  fechas publicadas: de {datos[2]} a {datos[3]}")

    await cerrar_bd()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
