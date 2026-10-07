"""Comprueba que la aritmética del despliegue sostiene mil usuarios concurrentes.

    # Con la máquina de 4 GB (el escalón de entrada del documento de capacidad)
    .\\.venv\\Scripts\\python.exe scripts\\verificar_despliegue.py

    # Con la de 8 GB
    .\\.venv\\Scripts\\python.exe scripts\\verificar_despliegue.py --ram-gb 8

No arranca nada ni toca la base: lee `deploy/docker-compose.yml` y `.env` (o `.env.example`) y
comprueba las cuentas que deciden si mil paneles caben a la vez. Existe porque **ninguna de esas
cuentas falla sola**: un `max_connections` pequeño deja al API sin poder abrir conexiones y el
síntoma es un error de espera agotada en una petición cualquiera, y unos registros de Docker sin
tope llenan el disco en silencio hasta que el servidor entero se cae.

Las comprobaciones, y por qué cada una:

1. **Conexiones de base.** Cada proceso de API —y el worker— abre hasta
   `BD_POOL_SIZE + BD_MAX_OVERFLOW`. La suma de todos tiene que caber en `max_connections`. Es el
   techo aritmético del sistema y el que primero se rompe al añadir procesos.
2. **El `API_WORKERS` que se cree el `.env` es el que usa el `compose`.** Si el archivo dice 8 y el
   `compose` tiene un `4` escrito a mano, el despliegue tendrá cuatro procesos y nadie lo sabrá.
3. **Memoria.** `shared_buffers` + los procesos de API + el límite de Redis + el sistema tienen que
   caber en la máquina. Postgres no puede quedarse sin memoria: es el que no se puede reiniciar.
4. **`shm_size` en PostgreSQL.** Con los 64 MB por defecto, un `CREATE INDEX` grande falla con
   «could not resize shared memory segment», y falla **al desplegar**, no en desarrollo.
5. **`stop_grace_period` en la base y en Redis.** Diez segundos por defecto no bastan para cerrar
   limpio: PostgreSQL tendría que hacer recuperación al arrancar y Redis perdería el último segundo.
6. **Tope a los registros de Docker.** El conductor `json-file` no tiene límite por defecto y el API
   escribe una línea por petición. Sin tope, el disco se llena y el servidor se cae entero.
7. **Descriptores de fichero.** Cada panel abierto mantiene una conexión al flujo de eventos.
8. **Presupuesto de `work_mem`.** Es por operación **y por conexión**, así que el número que parece
   pequeño se multiplica rápido. Lo que se comprueba no es un caso patológico —todas las conexiones
   ordenando a la vez— sino que `work_mem` quepa en el presupuesto que se le da a la memoria
   transitoria de la base: **un 40 % de la máquina**, repartido entre las conexiones. El peor caso
   teórico se imprime como información, porque es el número que explica por qué el asesino por
   memoria aparece sin avisar.
9. **Si el API confía en `X-Forwarded-For`, el puerto no puede estar abierto a todo el mundo.**
   Es la condición que hace segura la cabecera, y la que se rompe al cambiar una línea por
   comodidad.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, "src")

import yaml

from contratacion.infraestructura.config.ajustes import Ajustes

RAIZ = Path(__file__).resolve().parents[2]
COMPOSE = RAIZ / "deploy" / "docker-compose.yml"

# Memoria que se da por ocupada por cada proceso de API, medida en el despliegue de desarrollo
# (`RSS` de un uvicorn con SQLAlchemy, FastAPI y el cliente de Redis en marcha).
MEMORIA_POR_PROCESO_MB = 150
# Y lo que ocupa Caddy, Docker y el sistema operativo en una máquina de este tamaño.
MEMORIA_DEL_SISTEMA_MB = 400
# Cuántas operaciones simultáneas se suponen por conexión activa al estimar el peor caso de
# `work_mem`. Una consulta con dos ordenaciones y una tabla temporal es lo normal.
OPERACIONES_POR_CONEXION = 3
# Conexiones propias del pool que se dan por buenas **por proceso**. Es el `BD_POOL_SIZE` de
# `.env.example` y el que sostiene los números del documento de capacidad (con 120 ms de ida y
# vuelta, diez conexiones por proceso son ~83 consultas por segundo y proceso). No es un techo duro:
# por debajo el sistema no falla, atiende menos a la vez, y por eso se avisa en lugar de fallar.
POOL_ESPERADO_POR_PROCESO = 10

fallos: list[str] = []


def _comprobar(condicion: bool, mensaje: str) -> None:
    if condicion:
        print(f"  ok   · {mensaje}")
    else:
        print(f"  FALLA· {mensaje}")
        fallos.append(mensaje)


def _avisar(condicion: bool, si_cumple: str, si_no: str) -> None:
    """Como `_comprobar`, pero sin contar como fallo: hay configuraciones pequeñas y deliberadas."""
    if condicion:
        print(f"  ok   · {si_cumple}")
    else:
        print(f"  aviso· {si_no}")


def _a_bytes(texto: str) -> int:
    """Convierte `1GB`, `512mb` o `16384` en bytes."""
    limpio = str(texto).strip().lower()
    unidades = {"kb": 1024, "mb": 1024**2, "gb": 1024**3, "": 1}
    for sufijo, factor in unidades.items():
        if sufijo and limpio.endswith(sufijo):
            return int(float(limpio[: -len(sufijo)]) * factor)
    return int(float(limpio))


def _mb(texto: str) -> int:
    return _a_bytes(texto) // (1024**2)


def _leer_env(ruta: Path) -> dict[str, str]:
    """Lee un `.env` a un diccionario. Ignora comentarios y líneas sin `=`."""
    valores: dict[str, str] = {}
    if not ruta.exists():
        return valores
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        limpia = linea.strip()
        if not limpia or limpia.startswith("#") or "=" not in limpia:
            continue
        clave, _, valor = limpia.partition("=")
        valores[clave.strip()] = valor.strip()
    return valores


def _resolver(texto: Any, entorno: dict[str, str], nombre: str, por_defecto: int | str) -> str:
    """Resuelve una entrada del `compose` del tipo `${VARIABLE:-valor}`.

    Se lee del `.env` si está, si no del entorno del proceso, y si no del valor por defecto escrito
    en el propio `compose`. Es el orden que usa `docker compose --env-file .env`: el archivo pisa al
    entorno.
    """
    crudo = str(texto)
    # `os.environ` **no** se consulta con `in` y corchetes por separado: es el mismo valor y así se
    # lee una sola vez.
    if entorno.get(nombre):
        return entorno[nombre]
    if os.environ.get(nombre):
        return os.environ[nombre]
    encontrado = re.search(r"\$\{" + re.escape(nombre) + r":-([^}]*)\}", crudo)
    if encontrado:
        return encontrado.group(1)
    return str(por_defecto)


def _valor_de_ajuste(nombre: str) -> int:
    """Valor por defecto de un ajuste de la aplicación, leído de donde está escrito.

    Se lee del modelo y no se copia aquí a propósito: un `10` repetido en dos sitios es la forma
    habitual de que la comprobación diga que todo está bien mientras el despliegue usa otro número.
    """
    campo = Ajustes.model_fields[nombre]
    return int(campo.default)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aritmética de capacidad del despliegue.")
    parser.add_argument(
        "--ram-gb", type=int, default=4, help="Memoria de la máquina (por defecto 4)."
    )
    parser.add_argument("--env", type=Path, default=None, help="Archivo de variables a leer.")
    argumentos = parser.parse_args(argv)

    entorno = _leer_env(argumentos.env or (RAIZ / ".env"))
    if not entorno:
        entorno = _leer_env(RAIZ / ".env.example")
    compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    servicios = compose["services"]

    api = servicios["api"]
    bd = servicios["bd"]
    cache = servicios["cache"]
    ram_mb = argumentos.ram_gb * 1024

    print("=" * 70)
    print("1. Conexiones a PostgreSQL: la suma de los pools tiene que caber")
    print("=" * 70)
    max_conexiones = int(_resolver(bd["command"], entorno, "BD_MAX_CONNECTIONS", 200))
    procesos = int(_resolver(api["command"], entorno, "API_WORKERS", 4))
    pool = int(_resolver("", entorno, "BD_POOL_SIZE", _valor_de_ajuste("bd_pool_size")))
    desborde = int(_resolver("", entorno, "BD_MAX_OVERFLOW", _valor_de_ajuste("bd_max_overflow")))
    por_proceso = pool + desborde
    # El worker de ingesta usa los mismos ajustes y abre su propio pool.
    necesarias = (procesos + 1) * por_proceso
    print(f"  max_connections={max_conexiones} · API_WORKERS={procesos} · pool={pool}+{desborde}")
    print(f"  conexiones necesarias: ({procesos} + 1) x {por_proceso} = {necesarias}")
    _comprobar(
        necesarias <= max_conexiones,
        f"los procesos caben en max_connections ({necesarias} <= {max_conexiones}, "
        f"margen {max_conexiones - necesarias})",
    )
    _comprobar(
        procesos >= 1 and pool >= 1,
        f"la configuración tiene sentido: {procesos} proceso(s) de {por_proceso} conexiones",
    )
    # Y no solo hay que caber: también hay que llegar. Un pool copiado de la máquina de desarrollo
    # —donde la base es un agrupador gestionado que admite quince clientes, y allí 4 + 2 es lo
    # correcto— cabe de sobra en 200 y sin embargo deja al despliegue con la mitad de la
    # concurrencia para la que está dimensionado el resto.
    _avisar(
        pool >= POOL_ESPERADO_POR_PROCESO,
        f"el pool por proceso es el previsto ({pool} >= {POOL_ESPERADO_POR_PROCESO})",
        f"el pool por proceso se queda corto para este despliegue ({pool} < "
        f"{POOL_ESPERADO_POR_PROCESO}): si el archivo viene de la máquina de desarrollo, allí el "
        "tope son quince clientes y este no es el caso",
    )

    print()
    print("=" * 70)
    print("2. El API_WORKERS del .env es el que usa el compose")
    print("=" * 70)
    en_compose = [str(x) for x in api["command"]]
    trabajadores_compose = en_compose[en_compose.index("--workers") + 1]
    print(f"  compose: {trabajadores_compose} · resuelto del entorno: {procesos}")
    _comprobar(
        str(procesos) in trabajadores_compose,
        "el compose toma los procesos del entorno y no de un número escrito a mano",
    )

    print()
    print("=" * 70)
    print("3. Memoria: `shared_buffers` + procesos + Redis + sistema")
    print("=" * 70)
    shared = _mb(_resolver(bd["command"], entorno, "BD_SHARED_BUFFERS", "1GB"))
    cache_mb = _mb(_resolver(cache["command"], entorno, "CACHE_MAXMEMORY", "512mb"))
    procesos_mb = procesos * MEMORIA_POR_PROCESO_MB
    # PostgreSQL no es solo `shared_buffers`: cada conexión tiene su memoria de trabajo y el
    # recopilador automático también cuenta.
    postgres_mb = shared + 300
    total = postgres_mb + procesos_mb + cache_mb + MEMORIA_DEL_SISTEMA_MB
    print(
        f"  PostgreSQL {postgres_mb} MB · API {procesos_mb} MB · Redis {cache_mb} MB · sistema "
        f"{MEMORIA_DEL_SISTEMA_MB} MB"
    )
    print(f"  total estimado: {total} MB de {ram_mb} MB ({total * 100 // ram_mb} %)")
    _comprobar(total <= ram_mb, f"el reparto cabe en {argumentos.ram_gb} GB")
    _comprobar(
        total <= ram_mb * 80 // 100,
        f"queda holgura para picos (se usa el {total * 100 // ram_mb} %, el tope es 80 %)",
    )

    print()
    print("=" * 70)
    print("4. Lo que impide que el despliegue se caiga solo")
    print("=" * 70)
    work_mem = _mb(_resolver(bd["command"], entorno, "BD_WORK_MEM", "16MB"))
    _comprobar(
        "shm_size" in bd and _mb(bd["shm_size"]) >= 256,
        f"PostgreSQL tiene /dev/shm ampliado ({bd.get('shm_size')}, no los 64 MB por defecto)",
    )
    _comprobar(
        _mb(bd["shm_size"]) >= work_mem * 8,
        f"/dev/shm da para el paralelismo ({bd.get('shm_size')} >= 8 x work_mem)",
    )
    for nombre in ("bd", "cache"):
        _comprobar(
            "stop_grace_period" in servicios[nombre],
            f"{nombre} tiene tiempo para cerrar limpio "
            f"({servicios[nombre].get('stop_grace_period')})",
        )
    for nombre, servicio in servicios.items():
        opciones = (servicio.get("logging") or {}).get("options") or {}
        _comprobar(
            bool(opciones.get("max-size")),
            f"{nombre} tiene tope en los registros de Docker "
            f"({opciones.get('max-size') or 'sin tope'})",
        )
    for nombre in ("api", "proxy"):
        nofile = (servicios[nombre].get("ulimits") or {}).get("nofile") or {}
        _comprobar(
            int(nofile.get("soft", 0)) >= 65536,
            f"{nombre} admite mil conexiones abiertas (nofile={nofile.get('soft')})",
        )

    print()
    print("=" * 70)
    print("5. Presupuesto de work_mem: es por operación y por conexión")
    print("=" * 70)
    activas = necesarias
    presupuesto = ram_mb * 40 // 100
    cabe_por_conexion = presupuesto // activas
    print(
        f"  presupuesto de trabajo transitorio: 40 % de {ram_mb} MB = {presupuesto} MB "
        f"entre {activas} conexiones = {cabe_por_conexion} MB cada una"
    )
    print(f"  work_mem configurado: {work_mem} MB")
    _comprobar(
        work_mem <= cabe_por_conexion,
        f"work_mem cabe en el presupuesto ({work_mem} MB <= {cabe_por_conexion} MB); "
        "si no, bajarlo con BD_WORK_MEM",
    )
    patologico = work_mem * activas * OPERACIONES_POR_CONEXION
    print(
        f"  ·  si **todas** las conexiones ordenaran a la vez con {OPERACIONES_POR_CONEXION} "
        f"operaciones: {patologico} MB de {ram_mb} MB "
        f"({patologico * 100 // ram_mb} %). No se comprueba: ese caso no ocurre, y es el que "
        "explica los asesinatos por memoria"
    )

    print()
    print("=" * 70)
    print("6. Redis y la cabecera del cliente")
    print("=" * 70)
    orden = [str(x) for x in cache["command"]]
    _comprobar(
        "--maxmemory" in orden, "Redis tiene límite de memoria (la expulsión solo actúa con él)"
    )
    _comprobar(
        "--maxmemory-policy" in orden and "noeviction" not in orden,
        "Redis puede expulsar en lugar de fallar las escrituras",
    )
    confia = (
        "--forwarded-allow-ips" in en_compose
        and en_compose[en_compose.index("--forwarded-allow-ips") + 1].strip('"') == "*"
    )
    publicados = [str(p) for p in api.get("ports", [])]
    solo_local = all(p.startswith("127.0.0.1:") for p in publicados) and bool(publicados)
    print(f"  confía en X-Forwarded-For: {confia} · puerto del API: {publicados}")
    _comprobar(
        not confia or solo_local,
        "confiar en la cabecera del cliente es seguro porque el API solo escucha en `127.0.0.1`",
    )

    print()
    if fallos:
        print(f"{len(fallos)} comprobación(es) fallidas:")
        for fallo in fallos:
            print(f"  - {fallo}")
        return 1
    print("Todas las comprobaciones pasaron.")
    print()
    print("Recuerda: esto es aritmética de diseño, no una medición. La escalera de mil usuarios se")
    print(
        "corre con `carga/panel.js` contra este despliegue, que es donde el número significa algo."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
