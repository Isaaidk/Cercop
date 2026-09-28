"""
Modelo: Procesos de contratación publicados (API de Datos Abiertos - OCDS).

Endpoints oficiales:

    GET /PLATAFORMA/api/search_ocds?year=&search=&page=&buyer=&supplier=
    GET /PLATAFORMA/api/record?ocid=

`search_ocds` entrega el listado (tipo, código, fecha, provincia, cantón,
objeto, entidad y monto) y `record` entrega el detalle (estado, periodo de
entrega de proformas, dirección y contacto de la entidad), por lo que el
detalle sólo se consulta cuando el usuario lo pide o para la página visible.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Iterable

import httpx
import pandas as pd

logging.basicConfig(level=logging.INFO)

API_URL = "https://datosabiertos.compraspublicas.gob.ec/PLATAFORMA/api"
SEARCH_URL = f"{API_URL}/search_ocds"
RECORD_URL = f"{API_URL}/record"
# Se mantiene el nombre histórico del módulo por compatibilidad.
BASE_URL = SEARCH_URL
PORTAL_DETALLE = (
    "https://datosabiertos.compraspublicas.gob.ec/PLATAFORMA/datos-abiertos/proceso/"
)

TIMEOUT = 60.0
# El SERCOP limita la tasa de peticiones (HTTP 429): las llamadas se serializan,
# se espacian en el tiempo y se reintentan con espera creciente.
MAX_CONCURRENCIA_API = 2
REINTENTOS_API = 4
INTERVALO_MINIMO = 0.6  # segundos entre llamadas consecutivas a la API
ESPERA_BASE = 1.5
# El detalle (`record`) es aún más sensible al límite de tasa.
MAX_CONCURRENCIA_DETALLE = 2
REINTENTOS_DETALLE = 4

# Encabezados solicitados para la tabla / Excel.
COLUMNAS_OCDS = {
    "tipo_proceso": "Tipo de Necesidad",
    "codigo": "Código Necesidad de Contratación",
    "fecha_publicacion": "Fecha de Publicación",
    "provincia_canton": "Provincia - Cantón",
    "objeto_compra": "Descripción del Objeto de compra",
    "estado": "Estado de la Necesidad",
    "fecha_limite_proformas": "Fecha límite para la entrega de proformas",
    "entidad": "Entidad Contratante",
    "direccion_entrega": "Dirección de Entrega",
    "contacto": "Contacto",
}

COLUMNAS_EXTRA_OCDS = {
    "enlace": "Enlace al detalle",
    "proveedor": "Proveedor adjudicado",
    "monto": "Monto",
    "ocid": "OCID",
}

# Equivalencia aproximada entre el estado OCDS y el vocabulario del portal NCO.
ESTADOS_OCDS = {
    "active": "En Curso",
    "planned": "En Curso",
    "complete": "Finalizada",
    "cancelled": "Cancelada",
    "unsuccessful": "Desierto",
    "withdrawn": "Cancelada",
}


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #
def _texto(valor: Any) -> str:
    return "" if valor is None else str(valor).strip()


async def _get_json(client: httpx.AsyncClient, url: str, params: dict) -> dict:
    respuesta = await client.get(url, params=params)
    respuesta.raise_for_status()
    return respuesta.json()


def _buscar_party(parties: Iterable[dict], rol: str) -> dict:
    for party in parties or []:
        if rol in (party.get("roles") or []):
            return party
    return {}


# --------------------------------------------------------------------------- #
# Control de tasa: el SERCOP responde 429 ante ráfagas de peticiones.
# --------------------------------------------------------------------------- #
_semaforo_api = asyncio.Semaphore(MAX_CONCURRENCIA_API)
_lock_api = asyncio.Lock()
_ultima_llamada = 0.0
_cooldown_hasta = 0.0


def _marcar_cooldown(segundos: float) -> None:
    """Suspende globalmente las llamadas durante `segundos` tras un 429/5xx."""
    global _cooldown_hasta
    _cooldown_hasta = max(_cooldown_hasta, time.monotonic() + segundos)


async def _esperar_turno() -> None:
    """Serializa y espacia las peticiones para no exceder el límite del SERCOP."""
    global _ultima_llamada

    async with _lock_api:
        momento = time.monotonic()

        # Cooldown activo tras un 429.
        if _cooldown_hasta > momento:
            await asyncio.sleep(_cooldown_hasta - momento)
            momento = time.monotonic()

        # Espaciado mínimo entre llamadas consecutivas.
        espera = INTERVALO_MINIMO - (momento - _ultima_llamada)
        if espera > 0:
            await asyncio.sleep(espera)
        _ultima_llamada = time.monotonic()


def _espera_sugerida(respuesta: httpx.Response, intento: int) -> float:
    """Espera entre reintentos: usa `Retry-After` del SERCOP o backoff exponencial."""
    cabecera = respuesta.headers.get("Retry-After")
    if cabecera:
        try:
            return max(1.0, min(float(cabecera), 30.0))
        except ValueError:
            pass
    return min(ESPERA_BASE * (2 ** (intento - 1)), 30.0)


async def _solicitar_json(
    url: str,
    params: dict,
    intentos: int = REINTENTOS_API,
    etiqueta: str = "",
) -> dict | None:
    """
    GET con reintentos y control de tasa.

    Devuelve el JSON o `None` si todos los intentos fallaron (el llamador decide
    cómo reportarlo).
    """
    async with _semaforo_api:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            for intento in range(1, intentos + 1):
                await _esperar_turno()
                try:
                    return await _get_json(client, url, params)
                except httpx.HTTPStatusError as exc:
                    codigo = exc.response.status_code
                    if codigo not in (429, 500, 502, 503, 504) or intento == intentos:
                        logging.error("Error SERCOP %s (%s): %s", codigo, etiqueta, exc)
                        return None
                    espera = _espera_sugerida(exc.response, intento)
                    if codigo == 429:
                        _marcar_cooldown(espera)
                    logging.warning(
                        "SERCOP respondió %s en %s; reintentando en %.1fs (%s/%s).",
                        codigo, etiqueta or params.get("search"), espera, intento, intentos,
                    )
                    await asyncio.sleep(espera)
                except Exception as exc:  # noqa: BLE001
                    logging.error("Error consultando SERCOP (%s): %s", etiqueta, exc)
                    return None
    return None


# DEFINICIÓN 1: Solo se encarga de hablar con el SERCOP y traer datos crudos por año
async def extraer_datos_por_anio(year: int, palabra_clave: str) -> list:
    """Extrae la data cruda de un año específico desde la API del gobierno."""
    resultado = await buscar_ocds(year, palabra_clave, page=1)
    return resultado.get("data", [])


# Caché en memoria: evita volver a pedir la misma página al cambiar de filtro.
_cache_paginas: dict[tuple, tuple[float, dict]] = {}
CACHE_TTL = 600
MAX_ENTRADAS_CACHE = 500


async def buscar_ocds(
    year: int,
    palabra_clave: str,
    page: int = 1,
    buyer: str | None = None,
    supplier: str | None = None,
) -> dict:
    """Devuelve una página cruda de resultados del SERCOP (endpoint search_ocds)."""
    clave = (year, palabra_clave.strip().lower(), page, buyer, supplier)
    ahora = time.monotonic()

    guardado = _cache_paginas.get(clave)
    if guardado and (ahora - guardado[0]) < CACHE_TTL:
        return guardado[1]

    params: dict[str, Any] = {"year": year, "search": palabra_clave, "page": page}
    if buyer:
        params["buyer"] = buyer
    if supplier:
        params["supplier"] = supplier

    payload = await _solicitar_json(
        SEARCH_URL, params, etiqueta=f"{year} · {palabra_clave} · pág. {page}"
    )
    if payload is None:
        # `_error` permite al controlador avisar que la lista puede estar incompleta.
        return {"data": [], "total": 0, "pages": 0, "_error": True}

    if payload.get("data"):
        if len(_cache_paginas) >= MAX_ENTRADAS_CACHE:
            _cache_paginas.clear()
        _cache_paginas[clave] = (time.monotonic(), payload)
    return payload


# --------------------------------------------------------------------------- #
# Detalle de un proceso (endpoint record): estado, proformas, dirección, contacto
# --------------------------------------------------------------------------- #
_cache_detalles: dict[str, tuple[float, dict]] = {}
CACHE_TTL_DETALLES = 900


def _normalizar_detalle(ocid: str, payload: dict) -> dict:
    releases = payload.get("releases") or []
    release = releases[0] if releases else {}
    tender = release.get("tender") or {}
    parties = release.get("parties") or []
    awards = release.get("awards") or []

    periodo = tender.get("tenderPeriod") or {}
    fecha_limite = periodo.get("endDate") or periodo.get("startDate")
    inicio_ofertas = periodo.get("startDate")

    comprador = _buscar_party(parties, "buyer") or _buscar_party(parties, "procuringEntity")
    direccion = comprador.get("address") or {}
    contacto_punto = comprador.get("contactPoint") or {}

    direccion_completa = ", ".join(
        parte
        for parte in [
            _texto(direccion.get("streetAddress")),
            _texto(direccion.get("locality")),
            _texto(direccion.get("region")),
        ]
        if parte
    )

    contacto_partes = []
    if _texto(contacto_punto.get("name")):
        contacto_partes.append(f"Funcionario Encargado: {_texto(contacto_punto.get('name'))}")
    if _texto(contacto_punto.get("email")):
        contacto_partes.append(f"Email: {_texto(contacto_punto.get('email'))}")
    if _texto(contacto_punto.get("telephone")):
        contacto_partes.append(f"Teléfono: {_texto(contacto_punto.get('telephone'))}")

    proveedor = ""
    monto = None
    if awards:
        premio = awards[0]
        proveedores = premio.get("suppliers") or []
        if proveedores:
            proveedor = _texto(proveedores[0].get("name"))
            if proveedor.lower() in {"null", "none", "nan"}:
                proveedor = ""
        monto = (premio.get("value") or {}).get("amount")

    if not monto:
        items = tender.get("items") or []
        if items:
            monto = (items[0].get("unit") or {}).get("value", {}).get("amount")

    return {
        "ocid": ocid,
        "estado": ESTADOS_OCDS.get(_texto(tender.get("status")).lower(), ""),
        "fecha_limite_proformas": _texto(fecha_limite)[:16].replace("T", " "),
        "inicio_ofertas": _texto(inicio_ofertas)[:16].replace("T", " "),
        "fecha_limite_ofertas": _texto(periodo.get("endDate"))[:16].replace("T", " "),
        "fecha_limite_preguntas": _texto((tender.get("enquiryPeriod") or {}).get("endDate"))[:16].replace("T", " "),
        "ofertas_recibidas": tender.get("numberOfTenderers"),
        "direccion_entrega": direccion_completa,
        "contacto": " | ".join(contacto_partes),
        "provincia": _texto(direccion.get("region")),
        "canton": _texto(direccion.get("locality")),
        "proveedor": proveedor,
        "monto": monto,
        "tender_status": _texto(tender.get("status")),
    }


async def obtener_detalle_ocds(ocid: str, intentos: int = REINTENTOS_DETALLE) -> dict:
    """
    Detalle de un proceso puntual (estado, proformas, dirección, contacto).

    Usa el mismo control de tasa que el listado (el SERCOP responde 429 ante
    ráfagas) y cachea el resultado para no repetir la consulta.
    """
    ahora = time.monotonic()
    guardado = _cache_detalles.get(ocid)
    if guardado and (ahora - guardado[0]) < CACHE_TTL_DETALLES:
        return guardado[1]

    payload = await _solicitar_json(RECORD_URL, {"ocid": ocid}, intentos, etiqueta=ocid)
    if not payload:
        return {}

    detalle = _normalizar_detalle(ocid, payload)
    if len(_cache_detalles) >= MAX_ENTRADAS_CACHE:
        _cache_detalles.clear()
    _cache_detalles[ocid] = (time.monotonic(), detalle)
    return detalle


async def enriquecer_con_detalle(registros: list[dict], limite: int = 25) -> list[dict]:
    """
    Completa estado / fecha límite de proformas / dirección / contacto de los
    primeros `limite` registros usando el endpoint `record` en paralelo.
    """
    if not registros:
        return registros

    semaforo = asyncio.Semaphore(MAX_CONCURRENCIA_DETALLE)

    async def enriquecer(registro: dict) -> None:
        async with semaforo:
            detalle = await obtener_detalle_ocds(registro["ocid"])
        if detalle:
            for clave, valor in detalle.items():
                if valor not in (None, ""):
                    registro[clave] = valor
            registro["detalle_disponible"] = True

    await asyncio.gather(*(enriquecer(registro) for registro in registros[:limite]))
    return registros

def _normalizar_registro_ocds(item: dict) -> dict:
    region = _texto(item.get("region"))
    localidad = _texto(item.get("locality"))
    provincia_canton = " - ".join(parte for parte in [region, localidad] if parte)

    fecha = pd.to_datetime(item.get("date"), errors="coerce", utc=True)
    if fecha is not pd.NaT:
        fecha = fecha.tz_convert("America/Guayaquil").tz_localize(None)

    ocid = _texto(item.get("ocid"))
    return {
        "ocid": ocid,
        "tipo_proceso": _texto(item.get("internal_type")),
        "codigo": _texto(item.get("title")) or ocid,
        "fecha_publicacion": fecha.strftime("%Y-%m-%d %H:%M") if fecha is not pd.NaT else "",
        "fecha_publicacion_dt": None if fecha is pd.NaT else fecha,
        "provincia_canton": provincia_canton,
        "provincia": region,
        "canton": localidad,
        "objeto_compra": _texto(item.get("description")),
        "estado": "",
        "fecha_limite_proformas": "",
        "entidad": _texto(item.get("buyer")),
        "direccion_entrega": "",
        "contacto": "",
        "proveedor": _texto(item.get("suppliers")),
        "monto": item.get("amount") or item.get("budget"),
        "enlace": f"{PORTAL_DETALLE}{ocid}" if ocid else "",
        "detalle_disponible": False,
    }


def _normalizar_palabras(palabras_clave: str | Iterable[str] | None) -> list[str]:
    if palabras_clave is None:
        return []
    if isinstance(palabras_clave, str):
        partes = palabras_clave.split(",")
    else:
        partes = list(palabras_clave)
    return [parte.strip() for parte in partes if parte and len(parte.strip()) >= 3]


async def obtener_procesos_ocds(
    fecha_inicio: str,
    fecha_fin: str,
    palabras_clave: str | Iterable[str] | None,
    provincia: str | None = None,
    canton: str | None = None,
    estado: str | None = None,
    tipo: str | None = None,
    max_paginas: int = 6,
    incluir_detalle: bool = False,
    limite_detalle: int = 25,
) -> pd.DataFrame:
    """
    Descarga (paginando) los procesos de los años involucrados, filtra por
    fechas, provincia, cantón, tipo y estado, y devuelve un DataFrame
    homogéneo con las columnas de la tabla solicitada.
    """
    anio_inicio = int(fecha_inicio.split("-")[0])
    anio_fin = int(fecha_fin.split("-")[0])
    palabras = _normalizar_palabras(palabras_clave)

    if not palabras:
        return pd.DataFrame()

    tareas = [
        buscar_ocds(anio, palabra, pagina)
        for anio in range(anio_inicio, anio_fin + 1)
        for palabra in palabras
        for pagina in range(1, max(1, max_paginas) + 1)
    ]
    resultados = await asyncio.gather(*tareas)

    avisos: list[str] = []
    crudos: dict[str, dict] = {}
    for resultado in resultados:
        if resultado.get("_error"):
            avisos.append(
                "El SERCOP rechazó o no respondió a algunas consultas (límite de peticiones); "
                "los resultados podrían estar incompletos. Intente nuevamente en unos segundos."
            )
            continue
        for item in resultado.get("data") or []:
            ocid = _texto(item.get("ocid"))
            if ocid and ocid not in crudos:
                crudos[ocid] = item

    if not crudos:
        vacio = pd.DataFrame()
        vacio.attrs["avisos"] = avisos
        return vacio

    df = pd.DataFrame([_normalizar_registro_ocds(item) for item in crudos.values()])

    inicio = pd.to_datetime(fecha_inicio, errors="coerce")
    fin = pd.to_datetime(f"{fecha_fin} 23:59:59", errors="coerce")
    df = df[df["fecha_publicacion_dt"].notna()]
    if inicio is not None and not pd.isna(inicio):
        df = df[df["fecha_publicacion_dt"] >= inicio]
    if fin is not None and not pd.isna(fin):
        df = df[df["fecha_publicacion_dt"] <= fin]

    if provincia:
        df = df[df["provincia"].str.upper() == provincia.strip().upper()]
    if canton:
        df = df[df["canton"].str.upper() == canton.strip().upper()]
    if tipo:
        df = df[df["tipo_proceso"].str.upper() == tipo.strip().upper()]

    df = df.sort_values("fecha_publicacion_dt", ascending=False).reset_index(drop=True)

    if incluir_detalle and not df.empty:
        df = pd.DataFrame(await enriquecer_con_detalle(df.to_dict(orient="records"), limite_detalle))

    if estado:
        df = df[df["estado"].str.upper() == estado.strip().upper()]

    df = df.reset_index(drop=True)
    df.attrs["avisos"] = avisos
    return df


def exportar_ocds(df: pd.DataFrame) -> pd.DataFrame:
    """DataFrame con los encabezados legibles para el Excel."""
    columnas = {**COLUMNAS_OCDS, **COLUMNAS_EXTRA_OCDS}
    disponibles = [columna for columna in columnas if columna in df.columns]
    return df[disponibles].rename(columns={c: columnas[c] for c in disponibles})


# DEFINICIÓN 2: Se encarga de la lógica de negocio, unir, cruzar y filtrar por mes/día
async def obtener_contrataciones(fecha_inicio: str, fecha_fin: str, palabra_clave: str):
    """Orquesta la extracción, une los años necesarios y filtra el rango exacto de fechas."""
    anio_inicio = int(fecha_inicio.split("-")[0])
    anio_fin = int(fecha_fin.split("-")[0])
    
    # 1. Recolectar datos crudos usando la Definición 1
    todos_los_registros = []
    for year in range(anio_inicio, anio_fin + 1):
        registros_del_anio = await extraer_datos_por_anio(year, palabra_clave)
        todos_los_registros.extend(registros_del_anio)
        
    if not todos_los_registros:
        return pd.DataFrame()

    # 2. Transformar a Pandas
    df = pd.DataFrame(todos_los_registros)
    
    # 3. Mapeo de columnas
    columnas_ocds = {
        "ocid": "ID_Proceso",
        "date": "Fecha",
        "title": "Titulo",
        "internal_type": "Tipo_Contrato",
        "buyerName": "Entidad_Compradora",
        "single_provider": "Proveedor",
        "amount": "Monto",                 # <-- Agrega esto
        "tender.value.amount": "Monto"
    }
    
    columnas_existentes = {k: v for k, v in columnas_ocds.items() if k in df.columns}
    df_limpio = df[list(columnas_existentes.keys())].rename(columns=columnas_existentes)
    
    # 4. Cruce y filtro exacto de fechas
    df_limpio['Fecha'] = pd.to_datetime(df_limpio['Fecha'], utc=True).dt.tz_convert('America/Guayaquil').dt.tz_localize(None)    
    fecha_inicio_dt = pd.to_datetime(fecha_inicio)
    fecha_fin_dt = pd.to_datetime(f"{fecha_fin} 23:59:59") 
    
    mascara = (df_limpio['Fecha'] >= fecha_inicio_dt) & (df_limpio['Fecha'] <= fecha_fin_dt)
    df_filtrado = df_limpio.loc[mascara].copy()
    
    df_filtrado['Fecha'] = df_filtrado['Fecha'].dt.strftime('%Y-%m-%d')
    df_filtrado.fillna("No especificado", inplace=True)
    
    return df_filtrado