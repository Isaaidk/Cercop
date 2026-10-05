"""Informe del estado del caché.

Responde a las cuatro preguntas que deciden si un despliegue aguanta y que no se ven desde el panel
de la aplicación: cuánta memoria se usa, cuánto queda, qué se hace cuando se llena y cuántas
conexiones se están consumiendo.

Las dos últimas importan más de lo que parece en un plan pequeño:

- Un caché con política `noeviction` no falla por lentitud: **deja de aceptar escrituras** cuando se
  llena, y entre esas escrituras van las señales de presencia. El síntoma no es «va despacio», es
  «nadie aparece conectado».
- El número de **conexiones simultáneas** es el techo real de un plan gratuito, y no lo decide el
  tamaño ni la latencia: se agota mucho antes que la memoria.

    cd backend
    .\\.venv\\Scripts\\python.exe scripts\\estado_cache.py

No imprime credenciales ni la cadena de conexión: solo cifras. Código de salida 0 si responde, 1 si
no.
"""

from __future__ import annotations

import asyncio
import sys
from collections import defaultdict
from typing import Any

from redis.asyncio import Redis

from contratacion.infraestructura.config.ajustes import obtener_ajustes

# Nombre legible de cada prefijo de clave. Son los que define `dominio/busqueda.py` y
# `dominio/presencia.py`; si aparece uno que no está aquí, se muestra tal cual en vez de ocultarse:
# una clave con un prefijo desconocido suele ser la señal de que algo se está guardando donde no
# debería.
DESCRIPCION_PREFIJO: dict[str, str] = {
    "generacion": "contadores de generación",
    "res": "páginas de resultados",
    "est": "agregados de las gráficas",
    "cat": "catálogos de filtros",
    "tab": "tableros de estado",
    "presencia": "presencia (señales y canales)",
    "perm": "permisos por usuario",
}

# Tope de claves que se recorren para agrupar por prefijo. Es un informe, no una auditoría:
# recorrer un almacén entero para pintar una tabla que nadie va a mirar fila a fila no se justifica,
# y con `SCAN` el recorrido compite con las peticiones reales.
TOPE_DE_RECORRIDO = 20_000

# Políticas que hacen que el caché se degrade en lugar de romperse. `noeviction`, la que traen
# muchos planes por defecto, es la peligrosa: convierte la falta de memoria en un error de
# escritura.
POLITICAS_SEGURAS = frozenset(
    {
        "allkeys-lru",
        "allkeys-lfu",
        "allkeys-random",
        "volatile-lru",
        "volatile-lfu",
        "volatile-random",
        "volatile-ttl",
    }
)


async def _contar_por_prefijo(cliente: Redis) -> tuple[dict[str, int], bool]:
    """Claves agrupadas por la parte anterior a los dos puntos, y si el recorrido se cortó."""
    conteo: dict[str, int] = defaultdict(int)
    vistas = 0
    truncado = False

    async for clave in cliente.scan_iter(count=200):
        conteo[clave.split(":", 1)[0]] += 1
        vistas += 1
        if vistas >= TOPE_DE_RECORRIDO:
            truncado = True
            break

    return dict(conteo), truncado


def _entero(info: dict[str, Any], clave: str) -> int:
    """Valor numérico del informe, tolerando que falte o no sea un número."""
    try:
        return int(info[clave])
    except (KeyError, TypeError, ValueError):
        return 0


async def principal() -> int:
    ajustes = obtener_ajustes()

    if not ajustes.cache_habilitada:
        print("Caché deshabilitado: no hay REDIS_URL configurada.")
        print("El sistema funciona así, pero cada lectura va a la base de datos y la presencia")
        print("se queda dentro de un solo proceso.")
        return 0

    cliente: Redis = Redis.from_url(ajustes.redis_url, decode_responses=True)

    try:
        crudo: Any = await cliente.info()
        info: dict[str, Any] = dict(crudo)
    except Exception as excepcion:  # noqa: BLE001 - el informe no debe tumbar nada
        print(f"El caché configurado NO responde ({type(excepcion).__name__}).")
        return 1

    try:
        memorias = _entero(info, "maxmemory")
        usada = _entero(info, "used_memory")
        politica = str(info.get("maxmemory_policy", "desconocida"))
        conectadas = _entero(info, "connected_clients")
        maximo_conexiones = _entero(info, "maxclients")
        claves_totales = await cliente.dbsize()
        conteo, truncado = await _contar_por_prefijo(cliente)
    finally:
        await cliente.aclose()

    print(f"Servidor Redis: {info.get('redis_version', '?')} · estado {info.get('role', '?')}")
    print()

    print("Memoria")
    print(f"  usada          {info.get('used_memory_human', '?')}")
    if memorias:
        print(f"  límite         {info.get('maxmemory_human', '?')}")
        porcentaje = (usada / memorias) * 100 if memorias else 0
        print(f"  ocupación      {porcentaje:.1f} %")
    else:
        print("  límite         sin límite configurado")
    print(f"  expulsión      {politica}")
    print()

    print("Conexiones")
    print(f"  en uso         {conectadas}")
    if maximo_conexiones:
        print(f"  máximo         {maximo_conexiones}")
    print()

    print(f"Claves: {claves_totales}")
    if conteo:
        ancho = max(len(clave) for clave in conteo)
        for prefijo, cuantas in sorted(conteo.items(), key=lambda par: -par[1]):
            descripcion = DESCRIPCION_PREFIJO.get(prefijo, "sin descripción")
            print(f"  {prefijo:<{ancho}}  {cuantas:>7}  {descripcion}")
    if truncado:
        print(f"  (recorrido cortado en {TOPE_DE_RECORRIDO} claves; hay más)")
    print()

    avisos: list[str] = []
    if politica not in POLITICAS_SEGURAS:
        avisos.append(
            f"La política de expulsión es «{politica}». Con ella, al llenarse la memoria Redis "
            "rechaza escrituras en lugar de descartar claves, y entre esas escrituras van las "
            "señales de presencia. Se cambia en la configuración de la base, en el panel del "
            "proveedor."
        )
    if maximo_conexiones and conectadas >= maximo_conexiones * 0.8:
        avisos.append(
            f"Se están usando {conectadas} de {maximo_conexiones} conexiones. El flujo de eventos "
            "abre una por panel con el diseño actual, así que este techo llega antes que el de "
            "memoria."
        )

    if avisos:
        print("Avisos")
        for aviso in avisos:
            print(f"  - {aviso}")
    else:
        print("Sin avisos: memoria, política y conexiones están en valores seguros.")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(principal()))
