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
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

from contratacion.dominio.anexos import ACTA, clasificar, elegir_anexos
from contratacion.infraestructura.adaptadores.salida.archivos.tdr import (
    EnlaceNoPermitido,
    TopeExcedido,
    descargar_a,
)
from contratacion.infraestructura.adaptadores.salida.bd.tdr import RepositorioTdr
from contratacion.infraestructura.adaptadores.salida.fuentes.salidas import PoolSalidas
from contratacion.infraestructura.config.ajustes import obtener_ajustes

registro = logging.getLogger(__name__)

_BASE = "https://www.compraspublicas.gob.ec/ProcesoContratacion/compras/NCO/NCORegistroDetalle.cpe"


def _urls() -> list[str]:
    crudas = os.getenv("NCO_PROXY_URLS") or os.getenv("NCO_PROXY_URL") or ""
    return [url.strip() for url in crudas.split(",") if url.strip()]


def _mime(nombre: str) -> str:
    sufijo = Path(nombre).suffix.lower()
    return {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".zip": "application/zip",
    }.get(sufijo, "application/octet-stream")


TAMANO_LOTE = 6


async def atender_lote(
    repositorio: RepositorioTdr, carpeta: Path, *, tamano: int = TAMANO_LOTE
) -> int:
    """Descarga hasta `tamano` pedidos a la vez. Devuelve cuántos atendió (con o sin éxito)."""
    pedidos = await repositorio.tomar_pendientes(tamano)
    if not pedidos:
        return 0
    pool = PoolSalidas.desde_urls(_urls())
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
            mime=_mime(str(pedido.get("nombre") or "")),
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
