"""Mide el coste real de las consultas del panel y el plan que elige el motor.

    .\\.venv\\Scripts\\python.exe scripts\\medir_consultas.py [repeticiones]

Solo lectura. Existe porque «va lento» no es un dato: sin números no se puede decidir si un índice
sirve, si el caché acierta o si el problema está en la consulta o en el viaje. Cada caso se ejecuta
varias veces y se informa de la **mediana**, que no la infla una sola medición mala.

Conviene pasarlo **sin** el API ni el worker levantados: compiten por las conexiones del agrupador
(unas quince de sesión) y las cifras salen infladas; a veces la consulta se queda esperando en vez
de fallar, que es peor, porque parece que el script se ha colgado.

Además de los tiempos imprime el **primer paso del plan** de las consultas que dependen de un índice
nuevo. Un `Seq Scan on registro` significa que el índice no se está usando, y eso no se ve en el
tiempo cuando el motor ya tiene la tabla en memoria: por eso se miran las dos cosas.

Se llama a la capa de consulta directamente y no por HTTP —igual que `verificar_filtros.py`— porque
así no hacen falta credenciales y lo que se mide es la consulta, que es donde está el coste.
"""

from __future__ import annotations

import asyncio
import statistics
import sys
import time
from collections.abc import Sequence
from datetime import date

from sqlalchemy import text

sys.path.insert(0, "src")

from contratacion.dominio.busqueda import Filtros, OrdenBusqueda
from contratacion.infraestructura.adaptadores.salida.bd.consultas import (
    ORDENES,
    RepositorioConsultasBd,
    _condiciones,
)
from contratacion.infraestructura.adaptadores.salida.bd.sesion import cerrar_bd, obtener_motor

REPETICIONES = 5
FUENTES = ("NCO", "OCDS")
# Una fecha lejana del final del histórico: lo que se mide es el coste del filtro por fecha, no el
# de que haya o no filas.
HASTA = date(2000, 1, 1)


def _casos() -> tuple[tuple[str, Filtros], ...]:
    return (
        ("página sin filtros", Filtros(fuentes_permitidas=FUENTES)),
        (
            "página con el orden por defecto",
            Filtros(fuentes_permitidas=FUENTES, orden=OrdenBusqueda.RECIENTES),
        ),
        (
            "provincia (lo que hace el mapa)",
            Filtros(fuentes_permitidas=FUENTES, provincias=("PICHINCHA",)),
        ),
        (
            "código por fragmento (lo que hace el NIC)",
            Filtros(fuentes_permitidas=FUENTES, codigo="26-00053"),
        ),
        ("CPC por código", Filtros(fuentes_permitidas=FUENTES, cpc=("871410032",))),
        ("palabra clave", Filtros(fuentes_permitidas=FUENTES, terminos=("servicio",))),
        # La descripción del producto se mide aparte de las palabras clave porque **no** usa el
        # mismo índice: va contra el del objeto de compra, que es otra expresión. Si algún día el
        # plan dejara de usarlo, aquí se vería como un salto de milisegundos a segundos.
        (
            "descripción del producto",
            Filtros(fuentes_permitidas=FUENTES, descripcion=("servicio",)),
        ),
        ("rango de fechas", Filtros(fuentes_permitidas=FUENTES, hasta=HASTA)),
    )


async def _medir(repositorio: RepositorioConsultasBd) -> None:
    print(f"{'caso':44} {'mediana':>10} {'mín':>9} {'máx':>9}")
    print("-" * 76)
    for etiqueta, filtros in _casos():
        # Una pasada de calentamiento antes de medir: la primera consulta paga la conexión y el
        # primer acceso a disco, y contarla mezclaría dos cosas.
        await repositorio.buscar(filtros)
        tiempos: list[float] = []
        for _ in range(REPETICIONES):
            comienzo = time.perf_counter()
            await repositorio.buscar(filtros)
            tiempos.append((time.perf_counter() - comienzo) * 1000)
        print(
            f"{etiqueta:44} {statistics.median(tiempos):9.0f}ms "
            f"{min(tiempos):8.0f}ms {max(tiempos):8.0f}ms"
        )
    # Las gráficas del panel son la otra mitad de cada consulta.
    comienzo = time.perf_counter()
    await repositorio.estadisticas(Filtros(fuentes_permitidas=FUENTES))
    print(f"\n{'estadísticas (las gráficas)':44} {(time.perf_counter() - comienzo) * 1000:9.0f}ms")
    comienzo = time.perf_counter()
    await repositorio.catalogos()
    print(f"{'catálogos (los desplegables)':44} {(time.perf_counter() - comienzo) * 1000:9.0f}ms")


async def _planes() -> None:
    """El primer paso del plan de las consultas que deberían apoyarse en un índice nuevo."""
    pantallas = (
        ("página con el orden por defecto", Filtros(fuentes_permitidas=FUENTES)),
        ("provincia normalizada", Filtros(fuentes_permitidas=FUENTES, provincias=("PICHINCHA",))),
    )
    print("\nPlan que elige el motor (lo que dice si el índice se usa)")
    print("-" * 76)
    async with obtener_motor().connect() as conexion:
        for etiqueta, filtros in pantallas:
            condiciones, parametros = _condiciones(filtros)
            donde = " AND ".join(condiciones) if condiciones else "TRUE"
            orden = ORDENES[filtros.orden]
            plan: Sequence[str] = (
                (
                    await conexion.execute(
                        text(
                            "EXPLAIN SELECT r.id FROM registro r "
                            "JOIN fuente f ON f.id = r.fuente_id "
                            f"WHERE {donde} ORDER BY {orden} LIMIT :limite"
                        ),
                        {**parametros, "limite": filtros.tamano},
                    )
                )
                .scalars()
                .all()
            )
            print(f"\n{etiqueta}:")
            for linea in plan[:4]:
                print(f"  {linea}")


async def main() -> None:
    repositorio = RepositorioConsultasBd(obtener_motor())
    try:
        await _medir(repositorio)
        await _planes()
    finally:
        await cerrar_bd()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        REPETICIONES = int(sys.argv[1])
    asyncio.run(main())
