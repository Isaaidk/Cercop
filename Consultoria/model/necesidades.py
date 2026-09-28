"""
Modelo: Necesidades de Contratación y Recepción de Proformas (SERCOP - NCO).

Fuente oficial (pública) usada por el portal del SERCOP en la vista
"Necesidades de Contratación y Recepción de Proformas":

    https://www.compraspublicas.gob.ec/ProcesoContratacion/compras/NCO/NCORetornaRegistros.cpe?lot=1

Ese endpoint devuelve un JSON tipo DataTables con el listado vigente de
necesidades (Ínfimas Cuantías / Contratación) y exactamente los campos que se
necesitan para la tabla solicitada:

    tipo_necesidad, codigo_contratacion, fecha_publicacion, provincia, canton,
    objeto_contratacion, estado, fecha_limite_propuesta, url (entidad),
    direccion_entrega, contacto

IMPORTANTE: el endpoint ignora los parámetros de paginación/filtrado
(serverSide de DataTables lo resuelve el navegador con la data completa), por
lo que aquí se descarga una sola vez, se normaliza, se cachea en memoria
(TTL) y todos los filtros se aplican localmente con Pandas.
"""

from __future__ import annotations

import asyncio
import html as html_lib
import logging
import re
import time
import unicodedata
from datetime import datetime
from typing import Any, Iterable

import httpx
import pandas as pd

logging.basicConfig(level=logging.INFO)

NCO_ENDPOINT = (
    "https://www.compraspublicas.gob.ec/ProcesoContratacion/compras/NCO/"
    "NCORetornaRegistros.cpe"
)
NCO_DETALLE = (
    "https://www.compraspublicas.gob.ec/ProcesoContratacion/compras/NCO/"
    "NCORegistroDetalle.cpe"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "X-Requested-With": "XMLHttpRequest",
    "Referer": (
        "https://www.compraspublicas.gob.ec/ProcesoContratacion/compras/NCO/"
        "FrmNCOListado.cpe"
    ),
}

# Tiempo de vida del caché en segundos (el listado se publica en tiempo real,
# 5 minutos es un balance razonable entre frescura y carga al SERCOP).
CACHE_TTL = 300

_cache: dict[str, Any] = {"ts": 0.0, "df": None}
_lock = asyncio.Lock()

# Orden y nombres exactos de las columnas solicitadas para la tabla / Excel.
COLUMNAS_SALIDA: dict[str, str] = {
    "tipo_necesidad": "Tipo de Necesidad",
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

COLUMNAS_EXTRA = {
    "enlace": "Enlace al detalle",
    "funcionario": "Funcionario Encargado",
    "email": "Email",
    "telefono": "Teléfono",
    "dias_restantes": "Días restantes",
}


# --------------------------------------------------------------------------- #
# Utilidades de limpieza
# --------------------------------------------------------------------------- #
def _texto(valor: Any) -> str:
    """Normaliza nulos, entidades HTML y espacios sobrantes."""
    if valor is None:
        return ""
    texto = html_lib.unescape(str(valor))
    return re.sub(r"\s+", " ", texto).strip()


def _limpiar_html(valor: Any) -> str:
    """Convierte el HTML embebido del portal (<br/>, <b>…) en texto plano."""
    crudo = _texto(valor)
    if not crudo:
        return ""
    crudo = re.sub(r"<\s*br\s*/?\s*>", " | ", crudo, flags=re.I)
    crudo = re.sub(r"<[^>]+>", " ", crudo)
    return re.sub(r"\s+", " ", crudo).strip(" |").strip()


def normalizar_busqueda(valor: Any) -> str:
    """Minúsculas y sin acentos, para búsquedas tolerantes a tildes."""
    texto = _texto(valor).lower()
    return "".join(
        caracter
        for caracter in unicodedata.normalize("NFD", texto)
        if unicodedata.category(caracter) != "Mn"
    )


def _parse_fecha(valor: Any) -> datetime | None:
    texto = _texto(valor)
    if not texto:
        return None
    for formato in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto, formato)
        except ValueError:
            continue
    return None


def _extraer_enlace(url_html: Any) -> tuple[str, str]:
    """
    El campo `url` viene como HTML:
        <a href=../NCO/NCORegistroDetalle.cpe?&id=XXX,&op=0>ENTIDAD</a>
    Devuelve (enlace_absoluto, texto_visible).
    """
    crudo = _texto(url_html)
    if not crudo:
        return "", ""

    coincidencia = re.search(r"href\s*=\s*(['\"]?)(.*?)\1\s*>(.*?)</a>", crudo, re.S)
    if not coincidencia:
        return "", _texto(crudo)

    href = coincidencia.group(2).strip()
    texto = _texto(re.sub(r"<[^>]+>", " ", coincidencia.group(3)))

    if href.startswith("./"):
        href = href[2:]
    if href.startswith("../"):
        href = href[3:]
    if not href.lower().startswith("http"):
        href = (
            "https://www.compraspublicas.gob.ec/ProcesoContratacion/compras/"
            + href.lstrip("/")
        )
    return href, texto


def _separar_provincia_canton(provincia: str, canton: str) -> tuple[str, str]:
    """
    `provincia` llega como "AZUAY - CUENCA" y `canton` como "CUENCA".
    Devuelve (provincia_simple, canton).
    """
    provincia_simple = provincia
    if " - " in provincia:
        provincia_simple = provincia.split(" - ", 1)[0].strip()
    canton_final = canton.strip() or (
        provincia.split(" - ", 1)[1].strip() if " - " in provincia else ""
    )
    return provincia_simple, canton_final


# --------------------------------------------------------------------------- #
# Descarga y normalización
# --------------------------------------------------------------------------- #
def _normalizar_registro(registro: dict) -> dict:
    fecha_publicacion = _parse_fecha(registro.get("fecha_publicacion"))
    fecha_limite = _parse_fecha(registro.get("fecha_limite_propuesta"))
    enlace, entidad_enlace = _extraer_enlace(registro.get("url"))

    provincia_canton = _texto(registro.get("provincia"))
    provincia, canton = _separar_provincia_canton(
        provincia_canton, _texto(registro.get("canton"))
    )

    entidad = _texto(registro.get("razon_social")) or entidad_enlace
    funcionario = _texto(registro.get("funcionario_encargado"))
    email = _texto(registro.get("email_encargado"))
    telefono = _texto(registro.get("telefono_encargado"))

    contacto_partes = []
    if funcionario:
        contacto_partes.append(f"Funcionario Encargado: {funcionario}")
    if email:
        contacto_partes.append(f"Email: {email}")
    if telefono:
        contacto_partes.append(f"Teléfono: {telefono}")
    contacto = _limpiar_html(registro.get("contacto")) or " | ".join(contacto_partes)

    dias_restantes = None
    if fecha_limite is not None:
        dias_restantes = round(
            (fecha_limite - datetime.now()).total_seconds() / 86400, 2
        )

    return {
        "tipo_necesidad": _texto(registro.get("tipo_necesidad")),
        "codigo": _texto(registro.get("codigo_contratacion")),
        "fecha_publicacion": (
            fecha_publicacion.strftime("%Y-%m-%d %H:%M") if fecha_publicacion else ""
        ),
        "fecha_publicacion_dt": fecha_publicacion,
        "provincia_canton": provincia_canton,
        "provincia": provincia,
        "canton": canton,
        "objeto_compra": _texto(registro.get("objeto_contratacion")),
        "estado": _texto(registro.get("estado")),
        "fecha_limite_proformas": (
            fecha_limite.strftime("%Y-%m-%d %H:%M") if fecha_limite else ""
        ),
        "fecha_limite_dt": fecha_limite,
        "entidad": entidad,
        "enlace": enlace,
        "direccion_entrega": _texto(registro.get("direccion_entrega")),
        "contacto": contacto,
        "funcionario": funcionario,
        "email": email,
        "telefono": telefono,
        "dias_restantes": dias_restantes,
        "cantidad": _texto(registro.get("cantidad")),
        "valor_unitario": _texto(registro.get("valor_unitario")),
        "seq_tipo_necesidad": _texto(registro.get("seq_tipo_necesidad")),
        "seq_estado": _texto(registro.get("seq_estado")),
        "id_necesidad": _texto(registro.get("tcom_necesidad_contratacion_id")),
    }


async def _descargar_crudo() -> list[dict]:
    async with httpx.AsyncClient(timeout=120.0, headers=HEADERS, follow_redirects=True) as client:
        respuesta = await client.get(NCO_ENDPOINT, params={"lot": 1})
        respuesta.raise_for_status()
        payload = respuesta.json()
    return payload.get("data") or []


async def obtener_necesidades(forzar: bool = False) -> pd.DataFrame:
    """
    Devuelve el DataFrame normalizado de necesidades de contratación,
    reutilizando el caché en memoria mientras no expire el TTL.
    """
    ahora = time.time()
    if (
        not forzar
        and _cache["df"] is not None
        and (ahora - _cache["ts"]) < CACHE_TTL
    ):
        return _cache["df"]

    async with _lock:
        # Otra corrutina pudo haber llenado el caché mientras esperábamos.
        ahora = time.time()
        if (
            not forzar
            and _cache["df"] is not None
            and (ahora - _cache["ts"]) < CACHE_TTL
        ):
            return _cache["df"]

        try:
            registros = await _descargar_crudo()
        except Exception as exc:  # noqa: BLE001 - se registra y se degrada con gracia
            logging.error("Error descargando necesidades del SERCOP: %s", exc)
            if _cache["df"] is not None:
                logging.warning("Se usa el caché previo de necesidades.")
                return _cache["df"]
            return pd.DataFrame(columns=list(_normalizar_registro({}).keys()))

        filas = [_normalizar_registro(registro) for registro in registros]
        df = pd.DataFrame(filas)

        if not df.empty:
            df["_busqueda"] = df.apply(
                lambda fila: normalizar_busqueda(
                    " ".join(
                        [
                            fila["codigo"],
                            fila["objeto_compra"],
                            fila["entidad"],
                            fila["provincia_canton"],
                            fila["tipo_necesidad"],
                            fila["estado"],
                        ]
                    )
                ),
                axis=1,
            )

        _cache["df"] = df
        _cache["ts"] = time.time()
        logging.info("Necesidades SERCOP cargadas: %s registros.", len(df))
        return df


# --------------------------------------------------------------------------- #
# Filtrado, ordenamiento y paginación (local)
# --------------------------------------------------------------------------- #
def _normalizar_palabras(palabras_clave: str | Iterable[str] | None) -> list[str]:
    if palabras_clave is None:
        return []
    if isinstance(palabras_clave, str):
        partes = re.split(r"[,\n;]", palabras_clave)
    else:
        partes = list(palabras_clave)
    return [normalizar_busqueda(parte) for parte in partes if normalizar_busqueda(parte)]


def aplicar_filtros(
    df: pd.DataFrame,
    palabras_clave: str | Iterable[str] | None = None,
    modo: str = "todas",
    provincia: str | None = None,
    canton: str | None = None,
    estado: str | None = None,
    tipo: str | None = None,
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    por_vencer_horas: float | None = None,
    solo_vigentes: bool = False,
) -> pd.DataFrame:
    """Aplica todos los filtros del dashboard sobre el DataFrame cacheado."""
    if df.empty:
        return df

    filtrado = df

    palabras = _normalizar_palabras(palabras_clave)
    if palabras:
        if modo == "cualquiera":
            mascara = pd.Series(False, index=filtrado.index)
            for palabra in palabras:
                mascara = mascara | filtrado["_busqueda"].str.contains(
                    palabra, regex=False, na=False
                )
        else:  # "todas" (AND) por defecto
            mascara = pd.Series(True, index=filtrado.index)
            for palabra in palabras:
                mascara = mascara & filtrado["_busqueda"].str.contains(
                    palabra, regex=False, na=False
                )
        filtrado = filtrado[mascara]

    if provincia:
        filtrado = filtrado[
            filtrado["provincia"].map(normalizar_busqueda)
            == normalizar_busqueda(provincia)
        ]

    if canton:
        filtrado = filtrado[
            filtrado["canton"].map(normalizar_busqueda).str.contains(
                normalizar_busqueda(canton), regex=False, na=False
            )
        ]

    if estado:
        filtrado = filtrado[
            filtrado["estado"].map(normalizar_busqueda) == normalizar_busqueda(estado)
        ]

    if tipo:
        filtrado = filtrado[
            filtrado["tipo_necesidad"].map(normalizar_busqueda)
            == normalizar_busqueda(tipo)
        ]

    if fecha_desde:
        desde = pd.to_datetime(fecha_desde, errors="coerce")
        if desde is not None and not pd.isna(desde):
            filtrado = filtrado[
                filtrado["fecha_publicacion_dt"] >= desde.normalize()
            ]

    if fecha_hasta:
        hasta = pd.to_datetime(fecha_hasta, errors="coerce")
        if hasta is not None and not pd.isna(hasta):
            filtrado = filtrado[
                filtrado["fecha_publicacion_dt"]
                < (hasta.normalize() + pd.Timedelta(days=1))
            ]

    if solo_vigentes and "dias_restantes" in filtrado.columns:
        filtrado = filtrado[filtrado["dias_restantes"].fillna(-1) >= 0]

    if por_vencer_horas is not None and "dias_restantes" in filtrado.columns:
        limite_dias = por_vencer_horas / 24
        filtrado = filtrado[
            (filtrado["dias_restantes"].fillna(1e9) >= 0)
            & (filtrado["dias_restantes"] <= limite_dias)
        ]

    return filtrado


ORDEN_VALIDO = {
    "fecha_publicacion": "fecha_publicacion_dt",
    "fecha_limite_proformas": "fecha_limite_dt",
    "codigo": "codigo",
    "entidad": "entidad",
    "provincia": "provincia",
    "canton": "canton",
    "estado": "estado",
    "tipo": "tipo_necesidad",
    "objeto": "objeto_compra",
}


def ordenar(df: pd.DataFrame, orden: str = "fecha_publicacion", dir_orden: str = "desc") -> pd.DataFrame:
    columna = ORDEN_VALIDO.get(orden, "fecha_publicacion_dt")
    ascendente = str(dir_orden).lower() != "desc"
    return df.sort_values(
        by=columna, ascending=ascendente, na_position="last", kind="stable"
    )


def paginar(df: pd.DataFrame, pagina: int = 1, por_pagina: int = 25) -> tuple[pd.DataFrame, int, int]:
    pagina = max(1, int(pagina or 1))
    por_pagina = max(1, min(int(por_pagina or 25), 500))
    total = len(df)
    total_paginas = max(1, -(-total // por_pagina))  # techo
    inicio = (pagina - 1) * por_pagina
    return df.iloc[inicio : inicio + por_pagina], total, total_paginas


def construir_filtros(df: pd.DataFrame) -> dict:
    """Catálogo de opciones disponibles para los selects del frontend."""
    if df.empty:
        return {
            "provincias": [],
            "cantones": [],
            "estados": [],
            "tipos": [],
            "total": 0,
            "fecha_min": None,
            "fecha_max": None,
        }

    provincias = (
        df.groupby("provincia")["codigo"].count().sort_index()
        .reset_index(name="total")
        .to_dict(orient="records")
    )
    cantones = (
        df.groupby(["provincia", "canton"])["codigo"].count().sort_index()
        .reset_index(name="total")
        .to_dict(orient="records")
    )
    fechas = df["fecha_publicacion_dt"].dropna()

    return {
        "provincias": provincias,
        "cantones": cantones,
        "estados": sorted(x for x in df["estado"].unique() if x),
        "tipos": sorted(x for x in df["tipo_necesidad"].unique() if x),
        "total": int(len(df)),
        "fecha_min": fechas.min().strftime("%Y-%m-%d") if not fechas.empty else None,
        "fecha_max": fechas.max().strftime("%Y-%m-%d") if not fechas.empty else None,
        "actualizado": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def a_registros(df: pd.DataFrame) -> list[dict]:
    """Convierte el DataFrame al JSON que consume Vue (sin columnas internas)."""
    if df.empty:
        return []

    # `provincia` y `canton` se envían por separado para poder filtrarlos en la UI.
    columnas = list(COLUMNAS_SALIDA.keys()) + ["provincia", "canton"] + list(COLUMNAS_EXTRA.keys())
    disponibles = [columna for columna in columnas if columna in df.columns]
    salida = df[disponibles].copy()
    # `astype(object)` evita que los NaN vuelvan como NaN al reemplazarlos por None
    # (en columnas float pandas los reconvierte y rompen la serialización JSON).
    salida = salida.astype(object).where(pd.notnull(salida), None)
    return salida.to_dict(orient="records")


def df_exportable(df: pd.DataFrame) -> pd.DataFrame:
    """DataFrame con los encabezados legibles para el Excel."""
    registros = a_registros(df)
    columnas = {**COLUMNAS_SALIDA, **COLUMNAS_EXTRA}
    export = pd.DataFrame(registros)
    existentes = [columna for columna in columnas if columna in export.columns]
    export = export[existentes]
    return export.rename(columns={clave: columnas[clave] for clave in existentes})


# --------------------------------------------------------------------------- #
# Estadísticas para las gráficas
# --------------------------------------------------------------------------- #
RANGOS_VENCIMIENTO: list[tuple[float, float | None, str]] = [
    (0, 1, "Vence en 24 h"),
    (1, 3, "1 a 3 días"),
    (3, 7, "3 a 7 días"),
    (7, 15, "1 a 2 semanas"),
    (15, None, "Más de 2 semanas"),
]


def _distribucion(serie: pd.Series, etiqueta_vacia: str = "Sin dato") -> list[dict]:
    conteo = serie.fillna("").replace("", etiqueta_vacia).value_counts()
    total = int(conteo.sum())
    return [
        {
            "etiqueta": str(clave),
            "total": int(valor),
            "porcentaje": round(valor * 100 / total, 2) if total else 0,
        }
        for clave, valor in conteo.items()
    ]


def construir_estadisticas(
    df: pd.DataFrame, top: int = 12, dias_serie: int = 30
) -> dict:
    """
    Agregados para las gráficas del dashboard: cantones, provincias, estado,
    tipo, evolución diaria de publicaciones y vencimientos de proformas.
    """
    if df.empty:
        return {
            "total": 0,
            "cantones_distintos": 0,
            "provincias_distintas": 0,
            "por_vencer_24h": 0,
            "por_canton": [],
            "por_provincia": [],
            "por_estado": [],
            "por_tipo": [],
            "por_dia": [],
            "vencimientos": [],
            "actualizado": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    top = max(3, min(int(top or 12), 40))

    # Cantón: se añade la provincia sólo cuando el nombre se repite.
    repetidos = (
        df.groupby("canton")["provincia"].nunique().loc[lambda serie: serie > 1].index
    )
    etiquetas_canton = df.apply(
        lambda fila: (
            f"{fila['canton']} ({fila['provincia']})"
            if fila["canton"] in repetidos
            else fila["canton"]
        ),
        axis=1,
    )

    conteo_cantones = etiquetas_canton.value_counts()
    total = int(conteo_cantones.sum())
    principales = conteo_cantones.head(top)
    filas_canton = [
        {
            "etiqueta": str(canton),
            "total": int(valor),
            "porcentaje": round(valor * 100 / total, 2) if total else 0,
        }
        for canton, valor in principales.items()
    ]
    resto = int(conteo_cantones.iloc[top:].sum())
    if resto:
        filas_canton.append(
            {
                "etiqueta": f"Otros {conteo_cantones.iloc[top:].size} cantones",
                "total": resto,
                "porcentaje": round(resto * 100 / total, 2) if total else 0,
            }
        )

    fecha_max = df["fecha_publicacion_dt"].max()
    serie = df.dropna(subset=["fecha_publicacion_dt"]).copy()
    if fecha_max is not None and not pd.isna(fecha_max):
        inicio = fecha_max.normalize() - pd.Timedelta(days=dias_serie - 1)
        serie = serie[serie["fecha_publicacion_dt"] >= inicio]
        conteo_dias = (
            serie["fecha_publicacion_dt"].dt.strftime("%Y-%m-%d").value_counts().sort_index()
        )
        por_dia = [
            {"fecha": str(fecha), "total": int(cantidad)}
            for fecha, cantidad in conteo_dias.items()
        ]
    else:
        por_dia = []

    dias = df["dias_restantes"]
    vencimientos = []
    for minimo, maximo, etiqueta in RANGOS_VENCIMIENTO:
        if maximo is None:
            cantidad = int((dias >= minimo).sum())
        else:
            cantidad = int(((dias >= minimo) & (dias < maximo)).sum())
        vencimientos.append({"etiqueta": etiqueta, "total": cantidad})
    vencidos = int((dias < 0).sum())
    if vencidos:
        vencimientos.append({"etiqueta": "Plazo vencido", "total": vencidos})

    return {
        "total": total,
        "cantones_distintos": int(df["canton"].replace("", pd.NA).nunique()),
        "provincias_distintas": int(df["provincia"].replace("", pd.NA).nunique()),
        "por_vencer_24h": int(((dias >= 0) & (dias <= 1)).sum()),
        "por_canton": filas_canton,
        "por_provincia": _distribucion(df["provincia"])[:top],
        "por_estado": _distribucion(df["estado"]),
        "por_tipo": _distribucion(df["tipo_necesidad"]),
        "por_dia": por_dia,
        "vencimientos": [fila for fila in vencimientos if fila["total"]],
        "top": top,
        "dias_serie": dias_serie,
        "actualizado": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
