"""Copia el contenido de una base a otra, tabla por tabla.

Para qué sirve
--------------
Para llevar los datos de la base anterior a la del despliegue cuando las dos tienen **el mismo
esquema** —lo construyó Alembic con las mismas migraciones— y lo único que falta en la nueva son
las filas. No es un `pg_dump`/`pg_restore`: por eso no necesita el cliente de PostgreSQL instalado,
y por eso puede correr en cualquier sitio donde haya Python y se alcancen las dos bases —el
portátil a través de un proxy, o el propio contenedor del despliegue, que ve a las dos.

Las dos direcciones
-------------------
* **Origen**: la variable `DATABASE_URL_ORIGEN`, o `--origen`. Es la base que tiene los datos.
* **Destino**: la `DATABASE_URL` de la aplicación, o `--destino`. Es la que los recibe.

Cómo se usa
-----------
    # Primero, sin tocar nada: cuenta, compara y enseña el plan.
    python scripts/copiar_base.py --simular

    # Después, de verdad. Pide confirmación antes de borrar nada.
    python scripts/copiar_base.py

    # Sin preguntar, para cuando la decisión ya está tomada.
    python scripts/copiar_base.py --si

    # Una sola tabla, para probar el camino con algo pequeño.
    python scripts/copiar_base.py --tabla negocio --tabla usuario

Lo que hace, en orden
---------------------
1. Pregunta a las dos bases qué tablas tienen y **aborta si no son las mismas**: un esquema distinto
   no se arregla con una copia, y descubrirlo a mitad dejaría el destino a medias.
2. Cuenta las filas del origen.
3. **Vacía el destino** (`TRUNCATE ... CASCADE`), porque lo que hay allí ahora es una foto
   incompleta: lo que ingestó el worker desde el despliegue. No toca `alembic_version`, que es la
   que dice en qué revisión está el esquema.
4. Copia con `COPY` binario, por lotes, sin cargar ninguna tabla entera en memoria.
5. Vuelve a contar y **compara**. Si un número no cuadra, lo dice y termina con error.

Dos decisiones que no son obvias
--------------------------------
* **Las tablas particionadas se copian por la tabla padre**, no por sus particiones. Las particiones
  se crearon con la base, y las del origen y las del destino no son las mismas: el origen tiene
  septiembre, octubre y noviembre de 2026 y el destino las del mes en que se desplegó. Copiando por
  la raíz, PostgreSQL reparte cada fila —y lo que no tenga partición cae en la predeterminada, que
  existe en las dos.
* **Se desactivan las comprobaciones de integridad durante la copia** (`session_replication_role`),
  para no depender del orden en que se copien las tablas. Necesita el rol propietario, que es el que
  crea las tablas.

No imprime credenciales en ningún caso.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import ssl
import sys
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

import asyncpg  # type: ignore[import-untyped]  # noqa: E402
from sqlalchemy.engine import URL  # noqa: E402

from contratacion.infraestructura.adaptadores.salida.bd.motivos import (  # noqa: E402
    motivo_legible,
)
from contratacion.infraestructura.adaptadores.salida.bd.sesion import (  # noqa: E402
    normalizar_url_bd,
)
from contratacion.infraestructura.config.ajustes import obtener_ajustes  # noqa: E402

# Cuántas filas viajan en cada `COPY`. El número es un compromiso: más grande no gana apenas nada
# —la red ya va llena con un lote de estos—, y más pequeño multiplica los viajes. Lo que importa es
# que quepa en memoria: quinientas filas del histórico son unos pocos megabytes.
TAMANO_LOTE = 500

# La tabla que lleva la cuenta de las migraciones **no se copia ni se vacía**: es la única que
# describe la base de destino, y la del origen podría estar en otra revisión.
EXCLUIDAS = ("alembic_version",)

# Los fallos que significan «no se pudo hablar con la base» y no «la consulta estaba mal». Son dos
# a propósito: lo que llegue de más abajo —una clave ajena, un dato que no cabe— **tiene** que salir
# como error de verdad, no confundirse con un problema de red.
FALLOS_DE_CONEXION = (OSError, asyncpg.PostgresError)

# Los valores de `ssl` que significan «sin cifrado», y los que además exigen comprobar de quién es
# el certificado. La diferencia importa: en PostgreSQL `require` **cifra sin verificar** —así está
# definido—, y eso no es un descuido, es lo que hace falta con un proveedor gestionado que presenta
# una cadena con su propio certificado. Con `True` a secas, el controlador comprueba y la conexión
# se cae con «self-signed certificate in certificate chain».
SIN_CIFRADO = ("", "disable", "allow", "false", "0")
CON_VERIFICACION = ("verify-ca", "verify-full")

TABLAS = """
SELECT c.relname
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relkind IN ('r', 'p')
  AND NOT c.relispartition
  AND c.relname::text <> ALL($1::text[])
ORDER BY c.relname
"""

# Solo las columnas que admiten un valor escrito. Las generadas —`GENERATED ALWAYS AS ... STORED`— y
# las de identidad las calcula el servidor, y enviarles un valor es un error.
COLUMNAS = """
SELECT column_name
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = $1
  AND is_generated = 'NEVER'
  AND is_identity = 'NO'
ORDER BY ordinal_position
"""


def _dsn(url: URL) -> str:
    """Pasa la dirección al formato del controlador.

    `asyncpg` no entiende `?ssl=` dentro de la dirección —no es un parámetro del servidor, es una
    decisión de la conexión—, así que el cifrado se saca de ahí (ver `_cifrado`) y aquí solo queda
    la dirección limpia, sin un parámetro que el controlador rechazaría.
    """
    return url.set(query={}).set(drivername="postgresql").render_as_string(hide_password=False)


def _cifrado(url: URL) -> object:
    """Lo que hay que pedirle al controlador sobre el cifrado, según lo que diga la dirección."""
    pedido = ""
    for clave in ("ssl", "sslmode"):
        valor = url.query.get(clave)
        if isinstance(valor, str) and valor:
            pedido = valor.lower()
            break

    if pedido in SIN_CIFRADO:
        return False
    if pedido in CON_VERIFICACION:
        return True
    if pedido == "prefer":
        return "prefer"

    # `require` y compañía: se cifra, pero no se comprueba el certificado.
    contexto = ssl.create_default_context()
    contexto.check_hostname = False
    contexto.verify_mode = ssl.CERT_NONE
    return contexto


@asynccontextmanager
async def _conexion(url: URL) -> AsyncIterator[Any]:
    """Abre la conexión del controlador, que es la que sabe copiar en binario.

    Se abre con `asyncpg` **directamente**, y no a través de SQLAlchemy, por un motivo que solo
    aparece a mitad de una copia larga: al conectar, SQLAlchemy sustituye el codificador de `jsonb`
    de la conexión por el suyo, que espera texto, y el histórico guarda los datos como objetos. El
    síntoma es un `'dict' object has no attribute 'encode'` en la tabla número dos.
    """
    conexion = await asyncpg.connect(dsn=_dsn(url), ssl=_cifrado(url))
    try:
        yield conexion
    finally:
        await conexion.close()


async def _tablas(conexion: Any) -> list[str]:
    filas = await conexion.fetch(TABLAS, list(EXCLUIDAS))
    return [str(fila["relname"]) for fila in filas]


async def _columnas(conexion: Any, tabla: str) -> list[str]:
    filas = await conexion.fetch(COLUMNAS, tabla)
    return [str(fila["column_name"]) for fila in filas]


async def _contar(conexion: Any, tabla: str) -> int:
    total: int = await conexion.fetchval(f'SELECT count(*) FROM "{tabla}"')
    return total


def _confirmar(tablas: list[str], filas: dict[str, int]) -> bool:
    total = sum(filas.values())
    print("\nSe van a vaciar y volver a llenar estas tablas del destino:")
    for tabla in tablas:
        print(f"  {tabla:<28} {filas.get(tabla, 0):>10} filas")
    print(f"\n  {'TOTAL':<28} {total:>10} filas\n")

    respuesta = input("Escribe COPIAR para continuar: ").strip()
    return respuesta == "COPIAR"


async def _copiar_tabla(
    origen: Any, destino: Any, tabla: str, columnas: list[str], esperadas: int
) -> int:
    """Copia una tabla por lotes y devuelve cuántas filas viajaron."""
    lista = ", ".join(f'"{columna}"' for columna in columnas)
    puestos = 0

    # Una transacción por tabla, y **también en el origen**: `asyncpg` no deja abrir un cursor
    # fuera de una transacción, y el cursor es lo que permite leer 110.000 filas por lotes en vez de
    # traérselas todas de golpe a la memoria. Si algo falla a mitad, esa tabla no se queda a medias.
    async with origen.transaction(), destino.transaction():
        cursor = await origen.cursor(f'SELECT {lista} FROM "{tabla}"')
        lote = await cursor.fetch(TAMANO_LOTE)
        while lote:
            await destino.copy_records_to_table(tabla, records=lote, columns=columnas)
            puestos += len(lote)
            if esperadas:
                print(f"\r  {tabla}: {puestos}/{esperadas}", end="", flush=True)
            lote = await cursor.fetch(TAMANO_LOTE)

    print(f"\r  {tabla}: {puestos} filas{' ' * 20}")
    return puestos


def _argumentos() -> argparse.Namespace:
    analizador = argparse.ArgumentParser(description="Copia el contenido entre dos bases.")
    analizador.add_argument("--origen", help="Cadena de la base de origen (o DATABASE_URL_ORIGEN).")
    analizador.add_argument("--destino", help="Cadena de la base de destino (o DATABASE_URL).")
    analizador.add_argument("--tabla", action="append", help="Copiar solo esta tabla. Repetible.")
    analizador.add_argument(
        "--simular",
        action="store_true",
        help="Contar y comparar, sin vaciar ni escribir nada.",
    )
    analizador.add_argument(
        "--si",
        action="store_true",
        help="No preguntar antes de vaciar el destino. Para cuando la decisión ya está tomada.",
    )
    return analizador.parse_args()


async def _ejecutar(origen: Any, destino: Any | None, argumentos: argparse.Namespace) -> int:
    tablas_origen = await _tablas(origen)

    if destino is not None:
        tablas_destino = await _tablas(destino)
        solo_origen = sorted(set(tablas_origen) - set(tablas_destino))
        solo_destino = sorted(set(tablas_destino) - set(tablas_origen))
        if solo_origen or solo_destino:
            if solo_origen:
                print(f"Tablas que existen en el origen y no en el destino: {solo_origen}")
            if solo_destino:
                print(f"Tablas que existen en el destino y no en el origen: {solo_destino}")
            print("Los dos esquemas no coinciden: hay que igualarlos antes de copiar datos.")
            return 3

    if argumentos.tabla:
        desconocidas = sorted(set(argumentos.tabla) - set(tablas_origen))
        if desconocidas:
            print(f"No existen en el origen: {desconocidas}")
            return 2
        tablas = [tabla for tabla in tablas_origen if tabla in set(argumentos.tabla)]
    else:
        tablas = tablas_origen

    filas: dict[str, int] = {}
    for tabla in tablas:
        filas[tabla] = await _contar(origen, tabla)

    print(f"Tablas a copiar: {len(tablas)} · filas en el origen: {sum(filas.values())}")

    if argumentos.simular:
        print("\nSimulacro: no se toca el destino.\n")
        print(f"  {'tabla':<30} {'origen':>10} {'destino':>10}")
        print("  " + "-" * 52)
        for tabla in tablas:
            en_destino = "?" if destino is None else str(await _contar(destino, tabla))
            print(f"  {tabla:<30} {filas[tabla]:>10} {en_destino:>10}")
        return 0

    if destino is None:
        return 4

    if not argumentos.si and not _confirmar(tablas, filas):
        print("Cancelado. No se ha tocado nada.")
        return 0

    print("\nVaciando el destino…")
    lista = ", ".join(f'"{tabla}"' for tabla in tablas)
    async with destino.transaction():
        await destino.execute(f"TRUNCATE TABLE {lista} CASCADE")

    # Sin esto, copiar `usuario` antes que `negocio` fallaría por la clave ajena. Con el rol
    # propietario la orden funciona; si no, es mejor saberlo ahora que a mitad de la copia.
    await destino.execute("SET session_replication_role = replica")

    # Y sin esto, un proveedor que corte las consultas largas —o las transacciones ociosas— mataría
    # la copia del histórico a mitad, con un error que habla de otra cosa.
    await origen.execute("SET statement_timeout = 0")
    await origen.execute("SET idle_in_transaction_session_timeout = 0")

    print("Copiando…")
    for tabla in tablas:
        columnas_origen = await _columnas(origen, tabla)
        columnas_destino = await _columnas(destino, tabla)
        if columnas_origen != columnas_destino:
            print(f"  {tabla}: las columnas no coinciden. Se omite.")
            continue
        await _copiar_tabla(origen, destino, tabla, columnas_destino, filas[tabla])

    print("\nComprobando…")
    fallos = 0
    for tabla in tablas:
        aqui = await _contar(destino, tabla)
        if aqui == filas[tabla]:
            print(f"  ✓ {tabla:<28} {aqui}")
        else:
            print(f"  ✗ {tabla:<28} {aqui} (se esperaban {filas[tabla]})")
            fallos += 1

    if fallos:
        print(f"\n{fallos} tabla(s) no cuadran. Revisa antes de dar la copia por buena.")
        return 1

    print("\nLa copia cuadra tabla por tabla.")
    return 0


async def principal() -> int:
    argumentos = _argumentos()

    crudo_origen = argumentos.origen or os.environ.get("DATABASE_URL_ORIGEN") or ""
    if not crudo_origen:
        print("Falta la base de origen: pásala en --origen o en DATABASE_URL_ORIGEN.")
        return 2

    ajustes = obtener_ajustes()
    crudo_destino = argumentos.destino or ajustes.database_url
    if crudo_destino == crudo_origen:
        print("El origen y el destino son la misma base. No se hace nada.")
        return 2

    async with AsyncExitStack() as pila:
        try:
            origen = await pila.enter_async_context(_conexion(normalizar_url_bd(crudo_origen)))
        except FALLOS_DE_CONEXION as error:
            print(f"No se pudo abrir la base de origen: {motivo_legible(error)}")
            return 4

        # El destino se abre aparte porque en un simulacro no pasa nada por no tenerlo: sirve para
        # ver el plan y comprobar que el origen se lee bien antes de que la puerta esté abierta.
        destino: Any | None = None
        try:
            destino = await pila.enter_async_context(_conexion(normalizar_url_bd(crudo_destino)))
        except FALLOS_DE_CONEXION as error:
            if not argumentos.simular:
                print(f"No se pudo abrir la base de destino: {motivo_legible(error)}")
                return 4
            print(f"Aviso: la base de destino no responde ({motivo_legible(error)}).")
            print("Se enseña solo lo que hay en el origen.\n")

        return await _ejecutar(origen, destino, argumentos)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(principal()))
