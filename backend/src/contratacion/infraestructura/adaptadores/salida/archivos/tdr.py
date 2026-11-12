"""Archivo temporal de un TDR. No entra en la base.

Se escribe en trozos de 64 KB, con un tope de 25 MB, y el nombre final es el sha256. Dos pedidos
del mismo archivo comparten el fichero. A las 24 horas se puede borrar: la fila guarda `expira_en`
y esta carpeta se poda al guardar uno nuevo.

Solo se baja de los dominios permitidos (`ANEXOS_DOMINIOS_PERMITIDOS`, por defecto el portal de
compras públicas), y las redirecciones se siguen a mano para comprobar cada salto. Antes se seguían
solas y el enlace se tomaba tal cual de la ficha: un enlace absoluto, o una redirección, hacia
una dirección interna (`169.254.169.254`, `localhost`, la red privada del despliegue) hacía que el
worker la pidiera y guardara la respuesta como si fuera un TDR, que luego cualquiera podía
descargar (SSRF; auditoría de seguridad, doc 38).
"""

from __future__ import annotations

import hashlib
import ipaddress
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

TOPE_BYTES = 25 * 1024 * 1024
TROZO = 64 * 1024
TOPE_CARPETA = 2 * 1024 * 1024 * 1024
MAX_REDIRECCIONES = 5


class TopeExcedido(Exception):
    """El archivo pesa más de lo que se acepta en memoria de disco para un TDR."""


class EnlaceNoPermitido(Exception):
    """El enlace, o una redirección suya, apunta fuera de los dominios permitidos."""


def enlace_permitido(url: str, dominios: Iterable[str]) -> bool:
    """¿Se puede pedir esta dirección?

    Solo `http` o `https`, sin usuario ni clave en la dirección, con un nombre de dominio (nunca una
    IP escrita a mano) que sea uno de los permitidos o un subdominio suyo. Se compara el nombre
    completo y no un sufijo cualquiera: `compraspublicas.gob.ec.atacante.com` no pasa.
    """
    try:
        partes = urlsplit(url)
        anfitrion = (partes.hostname or "").lower().rstrip(".")
        _ = partes.port  # Un puerto mal escrito lanza aquí y se rechaza.
    except ValueError:
        return False
    if partes.scheme.lower() not in {"http", "https"} or not anfitrion:
        return False
    if partes.username or partes.password:
        return False
    try:
        ipaddress.ip_address(anfitrion)
    except ValueError:
        pass
    else:
        return False
    for dominio in dominios:
        limpio = dominio.strip().lower().rstrip(".")
        if limpio and (anfitrion == limpio or anfitrion.endswith("." + limpio)):
            return True
    return False


async def descargar_a(
    cliente: httpx.AsyncClient,
    url: str,
    carpeta: Path,
    *,
    dominios: Iterable[str] | None = None,
) -> tuple[Path, str, int]:
    """Baja `url` a `carpeta` y devuelve ruta, sha256 y tamaño.

    El temporal se renombra solo al terminar. Si se pasa del tope, se borra y no queda un archivo
    a medias con el nombre definitivo.

    Con `dominios`, la dirección y cada redirección tienen que estar dentro de ellos, o se lanza
    `EnlaceNoPermitido` sin haber pedido nada fuera.
    """
    permitidos = tuple(dominios) if dominios is not None else None
    carpeta.mkdir(parents=True, exist_ok=True)
    temporal = carpeta / f".parcial-{hashlib.sha256(url.encode()).hexdigest()[:16]}"
    resumen = hashlib.sha256()
    total = 0
    actual = url
    try:
        for _ in range(MAX_REDIRECCIONES + 1):
            if permitidos is not None and not enlace_permitido(actual, permitidos):
                raise EnlaceNoPermitido(_anfitrion(actual))
            async with cliente.stream("GET", actual, follow_redirects=False) as respuesta:
                if respuesta.is_redirect:
                    destino = respuesta.headers.get("location") or ""
                    if not destino:
                        respuesta.raise_for_status()
                    actual = urljoin(actual, destino)
                    continue
                respuesta.raise_for_status()
                with temporal.open("wb") as archivo:
                    async for trozo in respuesta.aiter_bytes(TROZO):
                        total += len(trozo)
                        if total > TOPE_BYTES:
                            raise TopeExcedido(str(total))
                        resumen.update(trozo)
                        archivo.write(trozo)
                break
        else:
            raise httpx.TooManyRedirects(
                f"Más de {MAX_REDIRECCIONES} redirecciones", request=httpx.Request("GET", actual)
            )
        sha = resumen.hexdigest()
        destino_final = carpeta / sha
        if not destino_final.exists():
            temporal.replace(destino_final)
        else:
            temporal.unlink(missing_ok=True)
        _podar(carpeta)
        return destino_final, sha, total
    except Exception:
        temporal.unlink(missing_ok=True)
        raise


def _anfitrion(url: str) -> str:
    """Solo el dominio, para el mensaje: la dirección entera puede llevar datos."""
    try:
        return urlsplit(url).hostname or "(sin dominio)"
    except ValueError:
        return "(dirección ilegible)"


def _podar(carpeta: Path) -> None:
    """Si la carpeta pasa de 2 GB, borra los archivos más viejos hasta volver al tope."""
    archivos = [
        ruta for ruta in carpeta.iterdir() if ruta.is_file() and not ruta.name.startswith(".")
    ]
    ocupado = sum(ruta.stat().st_size for ruta in archivos)
    if ocupado <= TOPE_CARPETA:
        return
    for ruta in sorted(archivos, key=lambda item: item.stat().st_mtime):
        if ocupado <= TOPE_CARPETA:
            break
        peso = ruta.stat().st_size
        ruta.unlink(missing_ok=True)
        ocupado -= peso
