"""Importa el año de OCDS desde los ficheros mensuales del portal: minutos en lugar de días.

    .\\.venv\\Scripts\\python.exe scripts\\importar_ocds_masivo.py --simular
    .\\.venv\\Scripts\\python.exe scripts\\importar_ocds_masivo.py
    .\\.venv\\Scripts\\python.exe scripts\\importar_ocds_masivo.py --desde-mes 9 --hasta-mes 9
    .\\.venv\\Scripts\\python.exe scripts\\importar_ocds_masivo.py --conservar

POR QUÉ. El listado paginado devuelve diez filas por petición y no acepta tamaño de página, así que
el año son 10.363 peticiones contra un origen que responde 429 cada cinco o seis: medido, ~9 s por
página y ~26 horas. El portal publica los mismos procedimientos por meses en un ZIP: **doce
peticiones** y minutos. La comparación de totales cuadra —103.628 en el listado, 103.628 en
`get-totals`— y el fichero trae más por registro (proveedor y monto que el listado deja a cero).

CÓMO, Y POR QUÉ ASÍ. El fichero es un **delta de publicaciones**, no la foto del proceso: de las
4.634 publicaciones de septiembre, 2.340 no traen `tender` —son las de adjudicación y contrato, cuyo
anuncio se publicó en un mes anterior—. Por eso los doce meses se traducen y se **combinan por
`ocid`** antes de escribir nada: sin esa combinación, la publicación de la adjudicación dejaría el
título y la descripción en blanco, y la del anuncio borraría el proveedor y el monto.

Se escribe **por tandas**: cada tanda es un ciclo normal —los mismos mapeos, la misma huella,
el mismo `upsert`, el mismo historial— con su transacción y su registro de sincronización.
Una transacción de 103.000 filas sería un todo o nada que perdería el año entero por un fallo en la
última página; así, lo escrito queda escrito y volver a lanzarlo no duplica nada (la clave natural y
la huella son las mismas).

QUÉ NO HACE. No adelanta la marca de agua —se declara parcial, porque una foto con horas de retraso
no cubre el final del listado—, así que el ciclo de cada quince minutos sigue leyendo su rabo y lo
publicado entre la foto y ahora entra por ahí.

EL DESGLOSE DEL PRODUCTO. El fichero trae los ítems de cada proceso —el CPC del bien o servicio, el
nombre estándar, la unidad y la cantidad— y hasta ahora se tiraban. Ahora se guardan en `registro`
como los de las ínfimas —los mismos cuatro campos, la misma forma—, y con ellos el texto y los
códigos con los que se busca por clasificación: es lo que permite que la ficha de una oferta diga
**qué se compra** y no solo el párrafo del objeto. Como el desglose **no entra en la huella** del
contenido, volver a pasar el año es lo que lo rellena de las filas ya importadas: se reescriben solo
las que traen ítems, y sin tocar el histórico.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, "src")

from contratacion.aplicacion.casos_uso.ejecutar_ingesta import (
    DefinicionFuente,
    ejecutar_ciclo,
)
from contratacion.aplicacion.puertos.fuente import ResultadoExtraccion
from contratacion.dominio.ingesta import Presupuesto
from contratacion.infraestructura.adaptadores.salida.bd.bloqueo import bloqueo_de_ingesta
from contratacion.infraestructura.adaptadores.salida.bd.ingesta import RepositorioIngesta
from contratacion.infraestructura.adaptadores.salida.bd.sesion import cerrar_bd, obtener_motor
from contratacion.infraestructura.adaptadores.salida.cache.cliente import (
    cerrar_cache,
    obtener_cache,
)
from contratacion.infraestructura.adaptadores.salida.fuentes import ocds, ocds_mapeos
from contratacion.infraestructura.adaptadores.salida.fuentes.ocds_masiva import (
    combinar,
    nombre_del_mes,
    traducir_fichero,
    url_del_mes,
)
from contratacion.infraestructura.config.ajustes import obtener_ajustes

# Filas por vuelta. Diez mil da tandas de un par de minutos: suficiente para ver el avance, corto
# para que un fallo no se lleve por delante más de lo que cuesta rehacerlo.
FILAS_POR_TANDA = 10_000


def _duracion(segundos: float) -> str:
    if segundos < 60:
        return f"{segundos:.0f} s"
    if segundos < 3600:
        return f"{segundos // 60:.0f} min {segundos % 60:.0f} s"
    return f"{segundos // 3600:.0f} h {segundos % 3600 // 60:.0f} min"


def _megas(bytes_: float) -> str:
    return f"{bytes_ / 1024 / 1024:.1f} MB"


class FuenteDeRegistros(ocds.FuenteOcds):
    """Sirve un trozo de filas ya traducidas y combinadas.

    Existe para poder escribir el año importado **por tandas** sin volver a leer los ficheros: la
    lectura y la combinación se hacen una vez, y cada tanda es un ciclo normal sobre su rebanada.
    Hereda de `FuenteOcds` la clave natural —el `ocid`— para que las filas se escriban exactamente
    igual que las que deja la ingesta diaria.
    """

    codigo = ocds.CODIGO

    def __init__(self, filas: Sequence[dict[str, Any]], *, peticiones: int = 0) -> None:
        super().__init__(())
        self._filas = list(filas)
        self._peticiones = peticiones

    async def extraer(self, desde: datetime, presupuesto: Presupuesto) -> ResultadoExtraccion:
        """`parcial=True` siempre: la marca de agua no la mueve una importación de histórico."""
        resultado = ResultadoExtraccion(parcial=True)
        if not presupuesto.consumir():
            resultado.agoto_presupuesto = True
            return resultado
        resultado.peticiones = self._peticiones
        resultado.registros.extend(self._filas)
        return resultado


async def _descargar(anio: int, mes: int, destino: Path) -> Path | None:
    """Trae el ZIP del mes, reutiliza el que ya esté descargado, o devuelve `None` si no existe.

    Reutilizarlo importa: son 25 MB descomprimidos por mes, y volver a bajarlos tras un corte a
    mitad de la importación sería pagar dos veces lo mismo.

    Devolver `None` en lugar de abortar también importa, y se comprobó a la mala: el mes en curso
    todavía no tiene fichero —el 1 de octubre, octubre responde **500**, no 404—, y una excepción
    ahí tiraba por la borda la importación entera antes de escribir una sola fila. Un mes que falta
    no es un error: es el presente, y lo cubre el ciclo de cada quince minutos.
    """
    ruta = destino / f"releases_{anio}_{nombre_del_mes(mes)}.zip"
    if ruta.exists():
        tamano = _megas(ruta.stat().st_size)
        print(f"  {mes:>2} · {nombre_del_mes(mes):<10} ya descargado ({tamano})")
        return ruta

    inicio = time.monotonic()
    try:
        with httpx.stream("GET", url_del_mes(anio, mes), timeout=600.0, follow_redirects=True) as r:
            r.raise_for_status()
            with ruta.open("wb") as salida:
                for bloque in r.iter_bytes():
                    salida.write(bloque)
    except (httpx.HTTPStatusError, httpx.TransportError) as exc:
        ruta.unlink(missing_ok=True)
        motivo = getattr(getattr(exc, "response", None), "status_code", type(exc).__name__)
        print(f"  {mes:>2} · {nombre_del_mes(mes):<10} no disponible ({motivo}): se omite")
        return None
    print(
        f"  {mes:>2} · {nombre_del_mes(mes):<10} {_megas(ruta.stat().st_size)} "
        f"en {_duracion(time.monotonic() - inicio)}"
    )
    return ruta


async def main() -> int:
    ajustes = obtener_ajustes()
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument("--anio", type=int, default=datetime.now(UTC).year)
    analizador.add_argument("--desde-mes", type=int, default=1, help="Primer mes a importar.")
    analizador.add_argument("--hasta-mes", type=int, default=12, help="Último mes a importar.")
    analizador.add_argument(
        "--tanda", type=int, default=FILAS_POR_TANDA, help="Filas por vuelta de escritura."
    )
    analizador.add_argument(
        "--directorio",
        type=Path,
        default=None,
        help="Dónde dejar los ZIP (por defecto: tmp/ocds_<año>).",
    )
    analizador.add_argument(
        "--conservar",
        action="store_true",
        help="No borrar los ZIP al terminar (útiles para volver a importar sin descargar).",
    )
    analizador.add_argument(
        "--simular", action="store_true", help="Solo muestra el plan; no descarga ni escribe."
    )
    opciones = analizador.parse_args()

    destino = opciones.directorio or Path("tmp") / f"ocds_{opciones.anio}"
    meses = list(range(opciones.desde_mes, opciones.hasta_mes + 1))
    if not meses or meses[0] < 1 or meses[-1] > 12:
        print("Los meses van del 1 al 12.")
        return 2

    print(f"OCDS {opciones.anio}: importación masiva de {len(meses)} mes(es)")
    print(f"  ficheros en {destino.resolve()}")
    print("  una petición por mes; el listado paginado costaría ~10.363")

    if opciones.simular:
        return 0

    destino.mkdir(parents=True, exist_ok=True)
    print("\nDescarga")
    descargados = [await _descargar(opciones.anio, mes, destino) for mes in meses]
    rutas = [ruta for ruta in descargados if ruta is not None]
    if not rutas:
        print("\nNo hay ningún fichero que importar.")
        return 1

    print("\nLectura y combinación")
    inicio = time.monotonic()
    filas: list[dict[str, Any]] = []
    publicaciones = 0
    for ruta in rutas:
        traducidas = traducir_fichero(ruta)
        publicaciones += len(traducidas)
        filas.extend(traducidas)
    combinadas = combinar(filas)
    con_titulo = sum(1 for fila in combinadas if fila.get("description"))
    con_proveedor = sum(1 for fila in combinadas if fila.get("suppliers"))
    print(
        f"  {publicaciones} publicaciones → {len(combinadas)} procedimientos "
        f"en {_duracion(time.monotonic() - inicio)}"
    )
    print(f"  con objeto de compra: {con_titulo} · con proveedor adjudicado: {con_proveedor}")

    repositorio = RepositorioIngesta(obtener_motor())
    cache = obtener_cache()
    total = len(combinadas)
    escritas = 0
    nuevos = 0
    actualizados = 0
    iguales = 0
    tanda = 0
    inicio = time.monotonic()

    try:
        for posicion in range(0, total, opciones.tanda):
            trozo = combinadas[posicion : posicion + opciones.tanda]
            # La primera vuelta declara las descargas que se hicieron para traer el histórico.
            definicion = DefinicionFuente(
                codigo=ocds.CODIGO,
                nombre="Procesos publicados (OCDS)",
                endpoint_base=ocds.SEARCH_URL,
                adaptador=FuenteDeRegistros(trozo, peticiones=len(rutas) if posicion == 0 else 0),
                mapeos_por_defecto=ocds_mapeos.MAPEOS_POR_DEFECTO,
                desde=datetime(opciones.anio, 1, 1, tzinfo=UTC),
                # **No** se declara listado completo: lo que se escribe es el histórico de un año,
                # no la foto de lo vigente, y declararlo cerraría como «ya no vigente» lo que hay.
            )
            async with bloqueo_de_ingesta(ocds.CODIGO) as conexion:
                if conexion is None:
                    print("  el worker está ingestando OCDS; esperando 30 s")
                    await asyncio.sleep(30)
                    continue
                resultado = await ejecutar_ciclo(
                    definicion,
                    repositorio,
                    cache,
                    intervalo_min=ajustes.intervalo_ingesta_min,
                    ventana_solape_ciclos=ajustes.ventana_solape_ciclos,
                    presupuesto_peticiones=ajustes.presupuesto_peticiones_ciclo,
                )
            tanda += 1
            escritas += len(trozo)
            nuevos += resultado.nuevos
            actualizados += resultado.actualizados
            iguales += resultado.iguales
            transcurrido = time.monotonic() - inicio
            ritmo = escritas / transcurrido if transcurrido else 0
            falta = total - escritas
            estimado = f" · quedan ~{_duracion(falta / ritmo)}" if ritmo and falta else ""
            print(
                f"[{tanda:3}] {escritas:>6}/{total} filas · nuevas {resultado.nuevos:5} · "
                f"actualizadas {resultado.actualizados:5} · iguales {resultado.iguales:5} · "
                f"sin mapear {resultado.sin_mapear:3}{estimado}"
            )
            for aviso in resultado.avisos:
                print(f"      aviso: {aviso}")
    except KeyboardInterrupt:
        print("\nInterrumpido. Lo escrito ya está guardado; vuelve a lanzarlo para continuar.")
    finally:
        await cerrar_cache()
        await cerrar_bd()

    print()
    print(
        f"Procedimientos escritos: {escritas} de {total} en {_duracion(time.monotonic() - inicio)}"
    )
    print(f"  nuevos: {nuevos} · actualizados: {actualizados} · iguales: {iguales}")
    print(f"  peticiones al portal: {len(rutas)} (una por mes)")
    if escritas < total:
        print("  vuelve a lanzarlo: lo ya escrito se reconoce por su huella y no se duplica")
    if not opciones.conservar:
        for ruta in rutas:
            ruta.unlink(missing_ok=True)
        print(f"  ZIP borrados de {destino.resolve()} (--conservar para no borrarlos)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
