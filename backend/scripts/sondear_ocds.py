"""Sonda del listado **general** de OCDS: ¿cuánto costaría traerlo sin palabras clave?

    .\\.venv\\Scripts\\python.exe scripts\\sondear_ocds.py
    .\\.venv\\Scripts\\python.exe scripts\\sondear_ocds.py --anio 2026

Pregunta a la fuente **sin término de búsqueda** (`search=` vacío) y responde a la pregunta que
decide el diseño de la ingesta: cuántas páginas tiene el año entero, cuántas filas son, cuántas se
publican al día y qué fechas traen las últimas páginas.

El contexto que la hace necesaria: hoy cada palabra clave cuesta 2-3 peticiones por año y ciclo, así
que veinte términos son ~45-60 peticiones cada quince minutos —unos 4.700 al día, solo contra OCDS—
y la fuente responde 429 con un `Retry-After` de 11-20 s cuando se le aprieta. La alternativa es
leer el **final del listado general**, que es donde se acumula lo recién publicado: cuesta una
petición para saber cuántas páginas hay (la primera página las declara) más las que hayan crecido
desde la lectura anterior, y no depende de cuántas palabras clave tenga el cliente.

Usa el **mismo limitador** que la ingesta —semáforo, intervalo mínimo, enfriamiento y reintentos—,
así que esta sonda no puede provocar un 429 que después pague el worker.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, date, datetime
from typing import Any

sys.path.insert(0, "src")

from contratacion.infraestructura.adaptadores.salida.fuentes.limitador import LimitadorTasa
from contratacion.infraestructura.adaptadores.salida.fuentes.ocds import SEARCH_URL

FILAS_POR_PAGINA = 10


async def _pagina(
    limitador: LimitadorTasa, anio: int, pagina: int, termino: str = ""
) -> dict[str, Any] | None:
    return await limitador.solicitar_json(
        SEARCH_URL,
        {"year": anio, "search": termino, "page": pagina},
        etiqueta=f"{termino or 'general'} {anio} pág. {pagina}",
    )


def _fechas(payload: dict[str, Any]) -> list[str]:
    return [str(fila.get("date") or "") for fila in (payload.get("data") or [])]


def _informe_fila(etiqueta: str, payload: dict[str, Any]) -> None:
    """Qué campos trae una fila y cuántos bytes ocupa su JSON.

    El tamaño se promedia sobre la página entera y no se toma de la primera fila: hay registros con
    proveedor y con importe y otros sin nada de eso, y una sola fila puede desviar la cuenta.
    """
    filas = [fila for fila in (payload.get("data") or []) if isinstance(fila, dict)]
    if not filas:
        print(f"  {etiqueta}: sin filas que mirar")
        return
    fila = filas[0]
    llenos = sorted(campo for campo, valor in fila.items() if valor not in (None, "", [], {}))
    vacios = sorted(campo for campo, valor in fila.items() if valor in (None, "", [], {}))
    media = sum(len(json.dumps(f, ensure_ascii=False).encode()) for f in filas) / len(filas)
    print(f"  {etiqueta} {media:>6.0f} bytes por fila · {len(llenos)} campos con dato")
    print(f"              con dato: {', '.join(llenos) or '(ninguno)'}")
    if vacios:
        print(f"              vacios  : {', '.join(vacios)}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Mide el listado general de OCDS.")
    parser.add_argument("--anio", type=int, default=datetime.now(UTC).year)
    parser.add_argument(
        "--palabra",
        default="mantenimiento",
        help="Término con el que comparar los campos del listado general.",
    )
    argumentos = parser.parse_args()
    anio = argumentos.anio

    limitador = LimitadorTasa()
    try:
        primera = await _pagina(limitador, anio, 1)
        if primera is None:
            print("\n  La fuente no respondió. Nada que medir.\n")
            return

        total = int(primera.get("total") or 0)
        paginas = int(primera.get("pages") or 0)
        if total <= 0 or paginas <= 0:
            print(f"\n  El año {anio} no devolvió nada (total={total}, páginas={paginas}).\n")
            return

        dias = (datetime.now(UTC).date() - date(anio, 1, 1)).days + 1
        por_dia = total / dias
        paginas_por_dia = paginas / dias

        print()
        print(f"  LISTADO GENERAL DE OCDS — año {anio}, sin palabra clave")
        print(f"  {'-' * 60}")
        print(f"  filas           {total:>10,}   (10 por página)")
        print(f"  páginas         {paginas:>10,}")
        print(f"  días del año    {dias:>10,}   (hasta hoy)")
        print(f"  filas por día   {por_dia:>10,.0f}")
        print(f"  páginas por día {paginas_por_dia:>10,.1f}")
        print()
        print(f"  la página 1 trae lo MÁS ANTIGUO: {_fechas(primera)[:2]}")
        print()

        ultima = await _pagina(limitador, anio, paginas)
        if ultima is None:
            print("  La última página no respondió; no se pudo comprobar qué trae.\n")
            return

        print(f"  la última página ({paginas}) trae: {_fechas(ultima)[:3]}")
        print()

        print("  ¿VIENEN DETALLADAS LAS FILAS?")
        print(f"  {'-' * 60}")
        _informe_fila("general ", ultima)
        comparable = await _pagina(limitador, anio, 1, termino=argumentos.palabra)
        if comparable is not None:
            _informe_fila("palabra ", comparable)
            print(
                "              (la comparación es contra la búsqueda por palabra, que es de donde"
            )
            print("               salen hoy las filas que se guardan)")
        print()

        # Lo que costaría cada estrategia para **mantenerse al día**, que es lo que se decide.
        print("  COSTE DE MANTENERSE AL DÍA")
        print(f"  {'-' * 60}")
        print(f"  por palabra clave, 20 terminos x 15 min  ~{20 * 3 * 96:>8,} peticiones/dia")
        print(
            f"  general, cada 15 min (1 + lo que crecio) ~{96 + int(96 * paginas_por_dia / 96):>8,}"
            " peticiones/dia"
        )
        print()
        print("  La cuenta de la general: una peticion por vuelta para saber cuantas paginas hay")
        print(f"  (crecen {paginas_por_dia:.1f} al dia, o sea una cada")
        print(f"   {24 * 60 / max(paginas_por_dia, 0.01):.0f} min),")
        print("  mas las paginas nuevas que hayan aparecido desde la vuelta anterior.")
        print()
    finally:
        await limitador.cerrar()


if __name__ == "__main__":
    asyncio.run(main())
