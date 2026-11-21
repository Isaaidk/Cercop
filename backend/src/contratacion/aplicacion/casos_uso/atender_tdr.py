"""Descarga los TDR pendientes. Lo hace el worker, nunca la API.

El archivo se escribe en disco en trozos. Si pesa más de 25 MB se corta y la fila queda en error.
Si no hay ninguna salida sana, el pedido sigue en pendiente para la vuelta siguiente.

Se atienden **por lotes y en paralelo**, en el orden en que se pidieron. De uno en uno, con cientos
de personas pidiendo a la vez, el último de la fila esperaba la suma de todas las descargas
anteriores. El tope de paralelismo es el de las salidas: más peticiones que eso solo harían que la
fuente respondiera 429.

De las actas solo se baja **la más reciente** (`dominio/anexos.py`). La API ya pide solo esa, pero
en la cola pueden quedar actas viejas pedidas antes de la regla: se cierran sin abrir el portal.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from contratacion.dominio.anexos import ACTA, clasificar, elegir_anexos
from contratacion.dominio.documentos import parece_enlace
from contratacion.infraestructura.adaptadores.salida.archivos.tdr import (
    EXTENSION_DE_MIME,
    MIME_GENERICO,
    EnlaceNoPermitido,
    PortalEnMantenimiento,
    TopeExcedido,
    descargar_a,
    extension_de,
    tipo_de_archivo,
)
from contratacion.infraestructura.adaptadores.salida.bd.tdr import RepositorioTdr
from contratacion.infraestructura.adaptadores.salida.fuentes.portal import estado_portal
from contratacion.infraestructura.adaptadores.salida.fuentes.salidas import PoolSalidas
from contratacion.infraestructura.config.ajustes import obtener_ajustes

registro = logging.getLogger(__name__)

_BASE = "https://www.compraspublicas.gob.ec/ProcesoContratacion/compras/NCO/NCORegistroDetalle.cpe"


def _urls() -> list[str]:
    crudas = os.getenv("NCO_PROXY_URLS") or os.getenv("NCO_PROXY_URL") or ""
    return [url.strip() for url in crudas.split(",") if url.strip()]


_MIME_DE_EXTENSION = {extension: mime for mime, extension in EXTENSION_DE_MIME.items()}
_MIME_DE_EXTENSION[".jpeg"] = "image/jpeg"
_MIME_DE_EXTENSION[".tiff"] = "image/tiff"
_GENERICO = MIME_GENERICO


def _mime(nombre: str) -> str:
    """Tipo por la extensión del nombre. Solo es el último recurso: el nombre del anexo es el texto
    de la ficha y casi nunca trae extensión. Lo que manda es `mime_real`."""
    return _MIME_DE_EXTENSION.get(Path(nombre).suffix.lower(), _GENERICO)


def mime_real(ruta: Path, nombre: str = "", guardado: str = "") -> str:
    """El tipo del archivo por su contenido; si no se reconoce, el guardado y, al final, el nombre.

    Las filas bajadas antes de esta regla tienen el tipo deducido del nombre (casi siempre
    `application/octet-stream`): se corrige al servirlas, sin migrar nada.
    """
    detectado = tipo_de_archivo(ruta)
    if detectado != _GENERICO:
        return detectado
    if guardado and guardado != _GENERICO:
        return guardado
    return _mime(nombre)


# Caracteres que Windows, macOS o el propio navegador no aceptan en un nombre de archivo.
_PROHIBIDOS = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]+')
_ESPACIOS = re.compile(r"\s+")
_LARGO_MAXIMO = 120


def nombre_de_descarga(nombre: str, mime: str, *, respaldo: str = "documento") -> str:
    """Nombre con el que se guarda el anexo: el que le dio la entidad y la extensión **real**.

    - «INFORME DE NECESIDAD» + DOCX → «INFORME DE NECESIDAD.docx».
    - «TDR.pdf» + PDF → «TDR.pdf» (no se duplica la extensión).
    - «Anexo.pdf» + DOCX → «Anexo.docx»: la extensión escrita mentía, se cambia por la real.
    - Un nombre que es en realidad la dirección del portal → `respaldo` + extensión.

    Se quitan los caracteres que un sistema de archivos no admite y se recorta a una longitud
    razonable, sin cortar la extensión.
    """
    limpio = unicodedata.normalize("NFC", str(nombre or "")).strip()
    if not limpio or parece_enlace(limpio):
        limpio = respaldo
    limpio = _ESPACIOS.sub(" ", _PROHIBIDOS.sub(" ", limpio)).strip(" .") or respaldo
    extension = extension_de(mime)
    base, sufijo = os.path.splitext(limpio)
    clave = sufijo.lower()
    if clave in _MIME_DE_EXTENSION:
        # Ya trae una extensión conocida: se respeta si coincide con el contenido, si no se cambia.
        if not extension or _MIME_DE_EXTENSION.get(clave) == _MIME_DE_EXTENSION.get(extension):
            extension = sufijo
        limpio = base.strip(" .") or respaldo
    return f"{limpio[:_LARGO_MAXIMO].rstrip(' .')}{extension}"


# Errores de red con que el worker marca un anexo que no pudo bajar (el nombre de la excepción de
# httpx va primero en el texto guardado). Mismo criterio que `preparar_documentos.py`.
_ERRORES_DE_RED = (
    "HTTP",
    "Connect",
    "Read",
    "Write",
    "Timeout",
    "Remote",
    "Proxy",
    "Pool",
    "Network",
    "TooManyRedirects",
    "Protocol",
)

MENSAJE_SIN_PORTAL = (
    "El portal de compras públicas no respondió a CercoApp en este momento. Puedes abrir el "
    "anexo en el portal desde tu computadora con «Ver en el portal» y guardarlo, o volver a "
    "intentarlo en unos minutos."
)
MENSAJE_MANTENIMIENTO = (
    "El portal de compras públicas está en mantenimiento y no entrega archivos en este momento. "
    "Pulsa «Reintentar» cuando termine."
)


def mensaje_de_error(texto: str | None) -> str:
    """El error guardado de un anexo, dicho para la persona que lo ve en la ficha."""
    texto = str(texto or "")
    if texto.startswith("PortalEnMantenimiento"):
        return MENSAJE_MANTENIMIENTO
    if not texto or texto.startswith(_ERRORES_DE_RED):
        return MENSAJE_SIN_PORTAL
    return texto


_DOMINIO_PORTAL = "compraspublicas.gob.ec"


def enlace_al_portal(enlace: str | None) -> str:
    """Dirección completa del anexo en el portal, para abrirla con la conexión de la persona.

    Navegar al portal desde su navegador sí funciona aunque el servidor no llegue. Solo se devuelven
    direcciones `https` del propio portal: el enlace lo escribe un tercero en la ficha.
    """
    if not enlace:
        return ""
    url = urljoin(_BASE, str(enlace).strip())
    try:
        partes = urlsplit(url)
        anfitrion = (partes.hostname or "").lower()
    except ValueError:
        return ""
    if partes.scheme != "https":
        return ""
    if anfitrion != _DOMINIO_PORTAL and not anfitrion.endswith("." + _DOMINIO_PORTAL):
        return ""
    return url


TAMANO_LOTE = 6


async def atender_lote(
    repositorio: RepositorioTdr, carpeta: Path, *, tamano: int = TAMANO_LOTE
) -> int:
    """Descarga hasta `tamano` pedidos a la vez. Devuelve cuántos atendió (con o sin éxito)."""
    portal = estado_portal()
    # Con el portal en pausa (mantenimiento) no se reserva nada: los pedidos siguen en la fila y
    # se atienden en cuanto la pausa termina, sin gastar su reserva de diez minutos.
    if portal.en_pausa():
        return 0
    pedidos = await repositorio.tomar_pendientes(tamano)
    if not pedidos:
        return 0
    pool = PoolSalidas.desde_urls(_urls(), portal=portal)
    try:
        resultados = await asyncio.gather(
            *(_atender(repositorio, carpeta, pool, pedido) for pedido in pedidos),
            return_exceptions=True,
        )
    finally:
        await pool.cerrar()
    hechos = 0
    for resultado in resultados:
        if isinstance(resultado, BaseException):
            registro.error("No se pudo atender un TDR pendiente.", exc_info=resultado)
        elif resultado:
            hechos += 1
    return hechos


async def atender_uno(repositorio: RepositorioTdr, carpeta: Path) -> bool:
    """Descarga el pedido más antiguo, si hay alguno y hay salida. Devuelve si hizo algo."""
    return await atender_lote(repositorio, carpeta, tamano=1) > 0


async def archivo_local(repositorio: RepositorioTdr, fila: dict[str, Any]) -> Path | None:
    """Ruta del archivo de un pedido listo en **este** servicio, o None si ya no existe.

    Si el archivo no está en el disco (lo bajó el worker en otro contenedor), se trae la copia de
    la base por su huella y se escribe en la misma ruta. La huella se comprueba: lo que se escribe
    es exactamente lo que bajó el worker.
    """
    ruta_cruda = str(fila.get("ruta") or "")
    if not ruta_cruda:
        return None
    ruta = Path(ruta_cruda)
    if ruta.is_file():
        return ruta
    huella = str(fila.get("sha256") or "")
    if not huella or ruta.name != huella:
        return None
    contenido = await repositorio.contenido_archivo(huella)
    if contenido is None or hashlib.sha256(contenido).hexdigest() != huella:
        return None

    def _escribir() -> None:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        temporal = ruta.with_name(f".copia-{huella[:16]}")
        temporal.write_bytes(contenido)
        temporal.replace(ruta)

    await asyncio.to_thread(_escribir)
    return ruta


async def _acta_superada(repositorio: RepositorioTdr, pedido: dict[str, Any]) -> bool:
    """Es un acta y el proceso publica otra más reciente. Solo consulta la base si es un acta."""
    nombre = str(pedido.get("nombre") or "")
    if clasificar(nombre) != ACTA or not pedido.get("registro_id"):
        return False
    elegidos = elegir_anexos(await repositorio.documentos_del_registro(pedido["registro_id"]))
    return bool(elegidos) and nombre not in {str(d.get("nombre") or "") for d in elegidos}


async def _atender(
    repositorio: RepositorioTdr, carpeta: Path, pool: PoolSalidas, pedido: dict[str, Any]
) -> bool:
    enlace = str(pedido.get("url_origen") or "")
    if not enlace:
        await repositorio.marcar_error(pedido["id"], "La ficha no trae enlace de descarga.")
        return True
    if await _acta_superada(repositorio, pedido):
        await repositorio.marcar_error(
            pedido["id"], "Hay un acta más reciente: para la proforma solo se usa la última."
        )
        return True

    salida = pool.elegir()
    if salida is None:
        return False
    # Cuenta para el tope por hora del portal. Si no hay hueco, el pedido queda reservado y vuelve
    # a la fila cuando caduque la reserva (diez minutos).
    if pool.portal is not None and not pool.portal.permitir("TDR"):
        return False
    cliente = salida.limitador._obtener_cliente(120.0)
    try:
        ruta, sha, tamano = await descargar_a(
            cliente,
            urljoin(_BASE, enlace),
            carpeta,
            # El enlace sale de la ficha publicada: se baja solo del portal, nunca de donde diga
            # (doc 38). Las redirecciones se comprueban una a una dentro de `descargar_a`.
            dominios=obtener_ajustes().anexos_dominios_permitidos,
        )
        # Copia en la base: el API no ve el disco del worker (servicios distintos en Railway).
        contenido = await asyncio.to_thread(ruta.read_bytes)
        await repositorio.guardar_archivo(sha, contenido)
        await repositorio.marcar_listo(
            pedido["id"],
            sha256=sha,
            ruta=str(ruta),
            tamano=tamano,
            # El tipo por el contenido, no por el nombre: el nombre es el texto de la ficha.
            mime=await asyncio.to_thread(mime_real, ruta, str(pedido.get("nombre") or "")),
        )
    except PortalEnMantenimiento:
        if pool.portal is not None:
            pool.portal.pausar("ventana de mantenimiento (TDR)")
        # El mensaje empieza por el nombre de la excepción: es lo que `_error_de_bajada` reconoce
        # para explicarlo en pantalla. «Reintentar» lo vuelve a poner en la fila.
        await repositorio.marcar_error(
            pedido["id"], "PortalEnMantenimiento: el portal está en ventana de mantenimiento."
        )
    except TopeExcedido:
        await repositorio.marcar_error(pedido["id"], "El archivo supera 25 MB.")
    except EnlaceNoPermitido as exc:
        registro.warning("Anexo con enlace fuera de los dominios permitidos: %s", exc)
        await repositorio.marcar_error(
            pedido["id"], "El enlace del anexo apunta fuera del portal de compras públicas."
        )
    except httpx.HTTPError as exc:
        await repositorio.marcar_error(pedido["id"], f"{type(exc).__name__}: {exc}")
    return True
