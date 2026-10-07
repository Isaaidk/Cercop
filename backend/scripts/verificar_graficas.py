"""Comprueba que las gráficas del panel cuentan lo mismo que la tabla.

    .\\.venv\\Scripts\\python.exe scripts\\verificar_graficas.py

Existe por un defecto concreto que se vio en pantalla: en provincias donde el mapa decía **0**, al
pulsarlas aparecían contrataciones, y al elegir una las demás se ponían en cero. Las dos causas eran
de la consulta de agregados, y las dos se comprueban aquí:

1. **El reparto venía recortado a doce filas** (`LIMITE_PROVINCIAS = 12`) sobre veinticuatro
   provincias. Lo que no entraba en el corte llegaba al mapa con cero, mientras el filtro de la
   tabla —que no lleva tope— sí encontraba filas.
2. **El reparto se contaba con el propio filtro de provincia aplicado**, así que elegir una
   provincia dejaba a las demás en cero y el mapa dejaba de servir para navegar.

Además se comprueba la coherencia de las tres gráficas entre sí: el reparto por provincia, el conteo
por fuente y la serie mensual tienen que sumar el mismo total que la tabla con los mismos filtros.
Una gráfica que suma otra cosa que la tabla es peor que no tenerla, porque nadie sabe cuál creer.

No escribe nada: lee la base y compara.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

sys.path.insert(0, "src")

from sqlalchemy import text

from contratacion.aplicacion.casos_uso.buscar_registros import obtener_estadisticas
from contratacion.dominio.busqueda import Filtros, OrdenBusqueda
from contratacion.infraestructura.adaptadores.salida.bd.consultas import RepositorioConsultasBd
from contratacion.infraestructura.adaptadores.salida.bd.sesion import cerrar_bd, obtener_motor
from contratacion.infraestructura.adaptadores.salida.cache.nula import CacheNula

FUENTES = ("NCO", "OCDS")

fallos: list[str] = []


def _comprobar(condicion: bool, mensaje: str) -> None:
    if condicion:
        print(f"  ok   · {mensaje}")
    else:
        print(f"  FALLA· {mensaje}")
        fallos.append(mensaje)


def _suma(filas: list[dict[str, Any]], campo: str = "total") -> int:
    return sum(int(fila[campo]) for fila in filas)


async def main() -> int:
    repositorio = RepositorioConsultasBd(obtener_motor())

    def filtros(**cambios: object) -> Filtros:
        base: dict[str, object] = {
            "fuentes_permitidas": FUENTES,
            "orden": OrdenBusqueda.RECIENTES,
        }
        base.update(cambios)
        return Filtros(**base)  # type: ignore[arg-type]

    async def cuadro(f: Filtros) -> tuple[int, dict[str, Any]]:
        """El total de la tabla y **la respuesta que sirve la API**, no la del repositorio.

        Se pasa por el caso de uso a propósito: es el que traduce el conteo por fuente a las dos
        familias de las pestañas, y comprobando la respuesta completa se comprueba también eso.
        """
        _, total_tabla = await repositorio.buscar(f)
        respuesta = await obtener_estadisticas(f, cache=CacheNula(), repositorio=repositorio)
        return total_tabla, respuesta

    try:
        print("=" * 70)
        print("1. Sin filtros: el reparto llega entero y cuadra con la tabla")
        print("=" * 70)
        total, datos = await cuadro(filtros())
        provincias = [dict(fila) for fila in datos["por_provincia"]]
        nombres = {str(fila["provincia"]) for fila in provincias}
        print(f"  filas del reparto: {len(provincias)} · total de la tabla: {total}")
        _comprobar(len(provincias) > 12, "el reparto no viene recortado a doce filas")
        _comprobar(
            "pichincha" in nombres and "zamora chinchipe" in nombres,
            "aparecen la primera y la última provincia por volumen, no solo el principio",
        )
        _comprobar(
            _suma(provincias) == total,
            f"el reparto suma el total de la tabla ({_suma(provincias)} = {total})",
        )
        _comprobar(
            _suma([dict(fila) for fila in datos["por_fuente"]]) == total,
            "el conteo por fuente suma el total de la tabla",
        )

        # La serie cubre los **últimos 24 meses** (`MESES_SERIE`), así que no suma el total: lo
        # anterior a esa ventana queda fuera por diseño. La comprobación honesta no es «suma el
        # total» sino «suma el total menos lo que hay fuera de la ventana», y eso se cuenta aquí.
        serie = [dict(fila) for fila in datos["serie_mensual"]]
        if serie:
            mas_antiguo = min(fila["mes"] for fila in serie)
            async with obtener_motor().connect() as conexion:
                fuera = int(
                    (
                        await conexion.execute(
                            text(
                                """
                                SELECT count(*) FROM registro
                                WHERE es_vigente AND fecha_publicacion < :desde
                                """
                            ),
                            {"desde": mas_antiguo},
                        )
                    ).scalar_one()
                )
            print(
                f"  serie: {len(serie)} meses, suma {_suma(serie)} · fuera de la ventana: {fuera}"
            )
            _comprobar(
                _suma(serie) + fuera == total,
                "la serie suma el total menos lo anterior a su ventana de 24 meses",
            )
        else:
            _comprobar(total == 0, "sin serie solo si no hay datos")

        print()
        print("=" * 70)
        print("2. Con una provincia filtrada: las demás NO se ponen en cero")
        print("=" * 70)
        elegida = "Zamora Chinchipe"
        total_provincia, datos_provincia = await cuadro(filtros(provincias=(elegida,)))
        reparto = {
            str(fila["provincia"]): int(fila["total"]) for fila in datos_provincia["por_provincia"]
        }
        suyo = reparto.get("zamora chinchipe")
        print(f"  tabla con {elegida}: {total_provincia} · su barra en el mapa: {suyo}")
        _comprobar(
            reparto.get("zamora chinchipe") == total_provincia,
            "la barra de la provincia elegida coincide con el total de la tabla",
        )
        _comprobar(
            int(reparto.get("pichincha") or 0) > 0,
            f"las otras provincias siguen contando (Pichincha: {reparto.get('pichincha')})",
        )
        _comprobar(
            len(reparto) == len(nombres),
            "el reparto sigue trayendo todas las provincias, no solo la elegida",
        )

        print()
        print("=" * 70)
        print("3. La provincia del final de la lista ya no sale con cero")
        print("=" * 70)
        cola = provincias[-4:]
        for fila in cola:
            nombre = str(fila["provincia"])
            total_nombre, _ = await cuadro(filtros(provincias=(nombre,)))
            print(f"  {nombre:<28} mapa {int(fila['total']):>6} · tabla {total_nombre:>6}")
            _comprobar(
                int(fila["total"]) > 0 and total_nombre > 0,
                f"{nombre}: el mapa y la tabla coinciden en que hay datos",
            )

        print()
        print("=" * 70)
        print("4. Con un término: las tres gráficas siguen cuadrando con la tabla")
        print("=" * 70)
        total_termino, datos_termino = await cuadro(filtros(terminos=("mantenimiento",)))
        partes = {
            "reparto": _suma([dict(fila) for fila in datos_termino["por_provincia"]]),
            "por fuente": _suma([dict(fila) for fila in datos_termino["por_fuente"]]),
            "serie": _suma([dict(fila) for fila in datos_termino["serie_mensual"]]),
        }
        print(f"  tabla con «mantenimiento»: {total_termino}")
        for nombre, suma in partes.items():
            print(f"    {nombre:<12} {suma}")
            _comprobar(
                suma == total_termino,
                f"el {nombre} suma lo mismo que la tabla con ese filtro",
            )
        _comprobar(
            total_termino < total,
            "el filtro por término reduce el conjunto (las gráficas no ignoran el filtro)",
        )

        print()
        print("=" * 70)
        print("5. Totales por familia: las dos pestañas con los mismos filtros")
        print("=" * 70)
        por_categoria = {
            str(fila["categoria"]): int(fila["total"]) for fila in datos["por_categoria"]
        }
        print(f"  {por_categoria}")
        _comprobar(
            set(por_categoria) == {"infimas", "ofertas"},
            "se responden siempre las dos familias, aunque una esté en cero",
        )
        _comprobar(
            sum(por_categoria.values()) == total,
            "las dos familias juntas suman el total de la tabla",
        )

        print()
        print("=" * 70)
        print("6. El reparto por tipo de procedimiento")
        print("=" * 70)
        tipos = [dict(fila) for fila in datos["por_tipo_proceso"]]
        suma_tipos = _suma(tipos)
        print(f"  valores distintos devueltos: {len(tipos)}")
        for fila in tipos[:6]:
            print(f"    {int(fila['total']):>7}  {str(fila['tipo_proceso'])[:60]}")
        _comprobar(bool(tipos), "se devuelve el reparto por tipo de proceso")
        _comprobar(
            suma_tipos == total,
            f"el reparto por tipo suma el total de la tabla ({suma_tipos} = {total})",
        )
        # El tope es 40 y hoy hay 18 valores: si algún día el vocabulario de la fuente creciera por
        # encima del tope, el «los otros suman X» de la gráfica empezaría a mentir, y esto lo dice.
        _comprobar(
            len(tipos) < 40,
            "el reparto no viene recortado por el tope (si lo estuviera, la suma no cuadraría)",
        )
        # Y con un filtro puesto, para que no sea un reparto que ignora lo que se pide.
        _, datos_termino_tipos = await cuadro(filtros(terminos=("mantenimiento",)))
        suma_tipos_termino = _suma([dict(fila) for fila in datos_termino_tipos["por_tipo_proceso"]])
        print(f"  con «mantenimiento»: {suma_tipos_termino} de {total_termino}")
        _comprobar(
            suma_tipos_termino == total_termino,
            "el reparto por tipo suma lo mismo que la tabla con ese filtro",
        )

        print()
        print("=" * 70)
        print("7. El mapa cambia con la familia: ínfimas, ofertas y las dos")
        print("=" * 70)
        # El mapa tiene un selector de familia, y lo que se comprueba aquí es que el reparto que lo
        # pinta **depende** de ella. Se mira el reparto y no el mapa porque el mapa dibuja lo que le
        # llega: si el reparto no cambiara, el mapa tampoco, y el selector parecería decorativo.
        cuadros: dict[str, tuple[int, dict[str, Any]]] = {}
        for familia in (None, "infimas", "ofertas"):
            cuadros[str(familia)] = await cuadro(filtros(categoria=familia))
        for familia, (total_familia, datos_familia) in cuadros.items():
            reparto_familia = [dict(fila) for fila in datos_familia["por_provincia"]]
            print(
                f"  familia={familia:8} tabla {total_familia:>7} · "
                f"reparto {len(reparto_familia):>2} filas, suma {_suma(reparto_familia):>7}"
            )
            _comprobar(
                _suma(reparto_familia) == total_familia,
                f"con la familia «{familia}» el reparto suma el total de su tabla",
            )
        total_ambas = cuadros["None"][0]
        total_infimas = cuadros["infimas"][0]
        total_ofertas = cuadros["ofertas"][0]
        _comprobar(
            total_infimas + total_ofertas == total_ambas,
            f"las dos familias suman la vista de ambas "
            f"({total_infimas} + {total_ofertas} = {total_ambas})",
        )
        # El caso que se veía mal: el reparto de una familia **no** puede ser el de la otra. Con el
        # encuadre roto del mapa las cifras cambiaban y el dibujo no; y si el reparto ignorara la
        # familia, el mapa enseñaría los mismos números en las tres posiciones del selector.
        reparto_infimas = {
            str(fila["provincia"]): int(fila["total"])
            for fila in cuadros["infimas"][1]["por_provincia"]
        }
        reparto_ofertas = {
            str(fila["provincia"]): int(fila["total"])
            for fila in cuadros["ofertas"][1]["por_provincia"]
        }
        compartidas = set(reparto_infimas) & set(reparto_ofertas)
        distintas = [
            provincia
            for provincia in compartidas
            if reparto_infimas[provincia] != reparto_ofertas[provincia]
        ]
        print(
            f"  provincias con cifra distinta entre familias: "
            f"{len(distintas)} de {len(compartidas)}"
        )
        _comprobar(
            len(distintas) == len(compartidas),
            "el reparto de ínfimas y el de ofertas no comparten ni una cifra",
        )
    finally:
        await cerrar_bd()

    print()
    if fallos:
        print(f"{len(fallos)} comprobación(es) fallidas:")
        for fallo in fallos:
            print(f"  - {fallo}")
        return 1
    print("Todas las comprobaciones pasaron.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
