"""Verificación de los filtros de búsqueda contra la base real.

    .\\.venv\\Scripts\\python.exe scripts\\verificar_filtros.py

No pasa por HTTP: llama a la capa de consulta directamente. Se hace así por dos razones. La
primera es que no necesita credenciales, y un guion de verificación con una contraseña dentro
acaba copiándose a otro sitio. La segunda es que comprueba **la consulta**, que es donde de
verdad se decide si un filtro funciona; una prueba por HTTP diría si la respuesta llega, no si
el `WHERE` es el correcto.

Lo que se busca no son valores concretos —eso cambia con cada ingesta— sino **invariantes**:
cosas que tienen que cumplirse siempre y que, si dejan de cumplirse, delatan un filtro que no
filtra.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date, timedelta

from sqlalchemy import text

sys.path.insert(0, "src")

from contratacion.dominio.busqueda import Categoria, Filtros, ModoBusqueda, OrdenBusqueda
from contratacion.infraestructura.adaptadores.salida.bd.consultas import (
    RepositorioConsultasBd,
)
from contratacion.infraestructura.adaptadores.salida.bd.sesion import (
    cerrar_bd,
    obtener_motor,
)

FALLOS: list[str] = []
FUENTES = ("NCO", "OCDS")

# Veinte palabras clave: la mitad inventadas, para comprobar que un término que no existe devuelve
# cero en lugar de devolver todo, que es el fallo clásico de un `OR` mal construido.
PALABRAS = [
    "medicamentos",
    "hospital",
    "servicio",
    "adquisición",
    "equipos",
    "construcción",
    "consultoría",
    "vehículos",
    "alimentos",
    "software",
    "limpieza",
    "seguridad",
    "capacitación",
    "obra",
    "ferretería",
    "papelería",
    "laboratorio",
    "transporte",
    "palabra-que-no-existe-xyz",
    "otro-termino-inexistente-abc",
]


def marca(condicion: bool, texto: str) -> None:
    if not condicion:
        FALLOS.append(texto)
    print(f"  {'OK ' if condicion else 'MAL'} {texto}")


async def _contar_con_cpc() -> int:
    """Cuántos registros tienen ya el CPC leído.

    No es un dato del filtro, pero sin él esta sección sería engañosa: «cpc=lavado -> 0» puede
    significar que el filtro no funciona o que todavía no se ha leído ninguna ficha, y son dos
    cosas muy distintas. El CPC llega ficha a ficha, así que tras desplegar esto lo normal es que
    casi ningún registro lo tenga hasta que el worker haya dado varias vueltas.
    """
    async with obtener_motor().connect() as conexion:
        resultado = await conexion.execute(
            text("SELECT count(*) FROM registro WHERE cpc_busqueda <> ''")
        )
        return int(resultado.scalar_one())


async def main() -> None:
    repositorio = RepositorioConsultasBd(obtener_motor())

    def filtros(**cambios: object) -> Filtros:
        base: dict[str, object] = {
            "fuentes_permitidas": FUENTES,
            "orden": OrdenBusqueda.RECIENTES,
        }
        base.update(cambios)
        return Filtros(**base)  # type: ignore[arg-type]

    async def total(f: Filtros) -> int:
        _, cantidad = await repositorio.buscar(f)
        return cantidad

    try:
        print("=" * 66)
        print("1. Sin filtros: el total de partida")
        print("=" * 66)
        base = await total(filtros())
        print(f"  registros en la base: {base}")
        marca(base > 0, f"hay datos que filtrar ({base})")
        if base == 0:
            print("\nNo hay nada ingestado; ejecuta el worker antes de verificar filtros.")
            return

        print("\n" + "=" * 66)
        print("2. Veinte palabras clave, una a una")
        print("=" * 66)
        encontradas = 0
        for palabra in PALABRAS:
            cantidad = await total(filtros(terminos=(palabra,)))
            if cantidad:
                encontradas += 1
            else:
                print(f"  ·  {palabra:34} -> 0")
        marca(True, f"{encontradas} de {len(PALABRAS)} palabras devuelven algo")
        # Las dos inventadas tienen que dar cero: si devolvieran algo, el término no se aplica.
        for inventada in PALABRAS[-2:]:
            cantidad = await total(filtros(terminos=(inventada,)))
            marca(cantidad == 0, f"«{inventada}» devuelve 0 ({cantidad})")

        print("\n" + "=" * 66)
        print("3. Veinte palabras a la vez: «todas» frente a «cualquiera»")
        print("=" * 66)
        todas = await total(filtros(terminos=tuple(PALABRAS), modo=ModoBusqueda.TODAS))
        cualquiera = await total(filtros(terminos=tuple(PALABRAS), modo=ModoBusqueda.CUALQUIERA))
        print(f"  modo=todas      -> {todas}")
        print(f"  modo=cualquiera -> {cualquiera}")
        # Con veinte términos de los que dos no existen, «todas» no puede devolver nada, y
        # «cualquiera» tiene que devolver al menos lo que devuelve una sola palabra.
        marca(todas == 0, f"«todas» con dos términos inexistentes no devuelve nada ({todas})")
        marca(cualquiera > 0, f"«cualquiera» sí devuelve ({cualquiera})")
        marca(cualquiera <= base, f"«cualquiera» no supera el total ({cualquiera} <= {base})")

        print("\n" + "=" * 66)
        print("4. Fechas: desde, hasta y rango")
        print("=" * 66)
        hoy = date.today()
        desde = hoy - timedelta(days=30)
        hasta = hoy - timedelta(days=20)
        solo_desde = await total(filtros(desde=desde))
        solo_hasta = await total(filtros(hasta=hoy))
        rango = await total(filtros(desde=desde, hasta=hasta))
        print(f"  desde {desde}                 -> {solo_desde}")
        print(f"  hasta {hoy}                   -> {solo_hasta}")
        print(f"  entre {desde} y {hasta} -> {rango}")
        marca(solo_desde <= base, "«desde» no puede devolver más que el total")
        marca(rango <= solo_desde, "un rango no puede devolver más que su propio «desde»")
        marca(solo_hasta <= base, "«hasta» no puede devolver más que el total")
        # Un rango imposible no puede devolver nada, y sobre todo no puede reventar: este es el caso
        # que devolvía un 500 antes de arreglar el `:hasta::date`.
        antiguo = await total(filtros(desde=date(2000, 1, 1), hasta=date(2000, 1, 2)))
        marca(antiguo == 0, f"un rango sin datos devuelve 0 sin error ({antiguo})")

        print("\n" + "=" * 66)
        print("5. Provincia y cantón")
        print("=" * 66)
        catalogo = await repositorio.catalogos()
        provincias = list(catalogo.get("provincia") or [])
        marca(bool(provincias), f"el catálogo trae provincias ({len(provincias)})")
        # El valor guardado puede ser «PICHINCHA» o «PICHINCHA - QUITO» según la fuente y la
        # fecha de ingesta, así que se comprueban las dos formas sin suponer cuál toca.
        con_canton = [p for p in provincias if " - " in p]
        print(f"  con formato «PROVINCIA - CANTÓN»: {len(con_canton)} de {len(provincias)}")
        suma = 0
        for completa in provincias[:6]:
            por_completa = await total(filtros(provincias=(completa,)))
            solo_provincia = completa.split(" - ", 1)[0].strip()
            por_nombre = await total(filtros(provincias=(solo_provincia,)))
            print(f"  {completa[:34]:34} -> completa={por_completa} | solo provincia={por_nombre}")
            marca(por_completa > 0, f"«{completa}» encuentra algo")
            marca(
                por_nombre >= por_completa,
                f"«{solo_provincia}» abarca al menos lo de «{completa}»",
            )
            suma += por_nombre
        marca(suma > 0, f"filtrar por provincia encuentra algo (suma parcial={suma})")
        provincia_inventada = await total(filtros(provincias=("Provincia Que No Existe",)))
        marca(
            provincia_inventada == 0,
            f"una provincia inventada devuelve 0 ({provincia_inventada})",
        )

        # Varias provincias a la vez: es el caso nuevo, y su comprobación no es la suma exacta
        # —dos provincias pueden compartir filas por la forma en que la fuente escribe el campo—
        # sino que el conjunto tiene que abarcar a cada una por separado y quedarse por debajo del
        # total. Es lo que distingue «filtra por dos» de «filtró por una y se olvidó de la otra».
        primera_dos = provincias[0].split(" - ", 1)[0].strip()
        segunda_dos = provincias[1].split(" - ", 1)[0].strip()
        solo_primera = await total(filtros(provincias=(primera_dos,)))
        solo_segunda = await total(filtros(provincias=(segunda_dos,)))
        las_dos = await total(filtros(provincias=(primera_dos, segunda_dos)))
        print(f"  {primera_dos} + {segunda_dos} -> {las_dos} ({solo_primera} + {solo_segunda})")
        marca(las_dos >= solo_primera, "con dos provincias no se pierde la primera")
        marca(las_dos >= solo_segunda, "con dos provincias no se pierde la segunda")
        marca(las_dos <= base, "dos provincias no superan el total")
        marca(
            las_dos <= solo_primera + solo_segunda,
            "dos provincias no cuentan nada dos veces",
        )
        # El orden de los clics no puede cambiar el resultado: si lo cambiara, la caché guardaría
        # dos entradas distintas para lo mismo y el panel daría cifras diferentes según cómo se
        # hubiera pulsado el mapa.
        al_reves = await total(filtros(provincias=(segunda_dos, primera_dos)))
        marca(al_reves == las_dos, f"el orden no cambia el resultado ({al_reves} = {las_dos})")

        print("\n" + "=" * 66)
        print("6. Solo con plazo abierto (el botón de ocultar vencidas)")
        print("=" * 66)
        con_plazo = await total(filtros(solo_con_plazo=True))
        sin_plazo = await total(filtros(solo_con_plazo=False))
        print(f"  solo_con_plazo=True  -> {con_plazo}")
        print(f"  solo_con_plazo=False -> {sin_plazo}")
        marca(con_plazo <= sin_plazo, "activo no puede devolver más que el total")
        marca(con_plazo < sin_plazo, f"el filtro descarta algo ({sin_plazo - con_plazo} fuera)")
        primera = provincias[0].split(" - ", 1)[0].strip()
        combinado = await total(filtros(solo_con_plazo=True, provincias=(primera,)))
        marca(combinado <= con_plazo, "combinar con provincia acota, no amplía")

        print("\n" + "=" * 66)
        print("7. Todo junto")
        print("=" * 66)
        mezcla = await total(
            filtros(
                terminos=("servicio", "medicamentos"),
                modo=ModoBusqueda.CUALQUIERA,
                provincias=(primera,),
                desde=desde,
                hasta=hoy,
                solo_con_plazo=True,
                texto="de",
            )
        )
        print(f"  palabras + provincia + fechas + plazo + texto -> {mezcla}")
        marca(mezcla <= base, "la combinación de filtros acota el resultado")

        print("\n" + "=" * 66)
        print("8. Búsqueda por CPC")
        print("=" * 66)
        # El CPC se lee ficha a ficha, así que al principio la mayoría de los registros todavía no
        # lo tienen. Lo que se comprueba no es un número —cambia con cada tanda— sino la propiedad
        # que hace útil el filtro: que busque en la clasificación **y no** en el texto libre.
        leidos = await _contar_con_cpc()
        print(f"  registros con el CPC ya leído: {leidos}")
        if leidos == 0:
            print("  ·  Ejecuta el worker (lee fichas por tandas) y vuelve a pasar esto.")
        else:
            por_cpc = await total(filtros(cpc=("lavado",)))
            por_texto = await total(filtros(terminos=("lavado",)))
            print(f"  cpc=lavado     -> {por_cpc}")
            print(f"  termino=lavado -> {por_texto}")
            marca(por_cpc <= leidos, "el filtro por CPC no devuelve más de lo leído")
            marca(
                por_cpc < por_texto,
                f"el CPC acota frente al texto libre ({por_cpc} < {por_texto})",
            )
            # Un criterio imposible tiene que dar cero, y no el total: si devolviera el total, la
            # condición no estaría llegando a la consulta.
            imposible = await total(filtros(cpc=("zzzzzz-no-existe",)))
            marca(imposible == 0, f"un CPC inexistente devuelve 0 ({imposible})")
            sin_cpc = await total(filtros())
            marca(sin_cpc == base, f"sin el criterio el total no cambia ({sin_cpc})")

        print("\n" + "=" * 66)
        print("9. Búsqueda por NIC (el código de la necesidad de ínfima cuantía)")
        print("=" * 66)
        # El NIC es el `codigo` de la necesidad NCO: «NIC-...». Se toma uno real de la base en lugar
        # de inventarlo, porque lo que se comprueba no es un formato sino que el fragmento que una
        # persona recuerda —unos dígitos, el año— encuentre la fila y que un código inexistente no
        # devuelva el listado entero.
        async with obtener_motor().connect() as conexion:
            fila_nic = await conexion.execute(
                text(
                    "SELECT r.datos ->> 'codigo' FROM registro r "
                    "JOIN fuente f ON f.id = r.fuente_id "
                    "WHERE f.codigo = 'NCO' AND r.datos ->> 'codigo' LIKE 'NIC-%' "
                    "ORDER BY r.fecha_publicacion DESC NULLS LAST LIMIT 1"
                )
            )
            nic = fila_nic.scalar_one_or_none()

        if not nic:
            print("  ·  Todavía no hay ningún NIC en la base; ejecuta el worker y vuelve.")
        else:
            print(f"  NIC de muestra: {nic}")
            exacto = await total(filtros(codigo=nic))
            fragmento = await total(filtros(codigo=nic[-8:]))
            inexistente = await total(filtros(codigo="NIC-0000000000000-0000-00000"))
            en_infimas = await total(filtros(codigo=nic, categoria=Categoria.INFIMAS))
            print(f"  codigo completo        -> {exacto}")
            print(f"  codigo={nic[-8:]} (fragmento) -> {fragmento}")
            print(f"  codigo inexistente     -> {inexistente}")
            print(f"  codigo + infimas       -> {en_infimas}")
            marca(exacto >= 1, f"el NIC completo encuentra al menos una fila ({exacto})")
            marca(fragmento >= 1, f"un fragmento del NIC también la encuentra ({fragmento})")
            marca(inexistente == 0, f"un NIC inexistente devuelve 0 ({inexistente})")
            marca(en_infimas >= 1, f"acotar a ínfimas sigue encontrándolo ({en_infimas})")
            marca(en_infimas <= exacto, "acotar por familia no añade filas")
            # El NIC lo teclea cada persona, así que no se guarda en el caché, igual que el texto
            # libre: su espacio de combinaciones es ilimitado y casi ninguna se repite.
            marca(
                not filtros(codigo=nic).cacheable,
                "una búsqueda por NIC no se guarda en el caché",
            )
    finally:
        await cerrar_bd()

    print()
    if FALLOS:
        print(f"{len(FALLOS)} COMPROBACIONES FALLIDAS:")
        for fallo in FALLOS:
            print(f"  · {fallo}")
    else:
        print("Todas las comprobaciones pasaron.")


if __name__ == "__main__":
    asyncio.run(main())
