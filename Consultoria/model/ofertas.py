"""
Modelo: Procesos en recepción de ofertas (SOCE / Datos Abiertos OCDS).

El portal clásico (`PC/buscarProceso.cpe`) exige captcha y sesión, por lo que no
es consumible de forma programática. Este módulo construye la misma vista
("procesos publicados y recepción de ofertas") a partir de la API oficial de
Datos Abiertos OCDS:

  * `search_ocds` -> listado de procesos (tipo, código, entidad, objeto, fechas,
    provincia/cantón, monto).
  * `record`      -> detalle con el periodo de recepción de ofertas
    (`tender.tenderPeriod`), estado, dirección y contacto.

Como `record` es lento y el SERCOP limita la tasa de peticiones, el detalle se
consulta sólo para los primeros `analizar` procesos (los más recientes) y se
cachea; el resultado indica cuántos procesos se analizaron.
"""

from __future__ import annotations

import unicodedata
from datetime import datetime
from typing import Any, Iterable

import pandas as pd

from Consultoria.model import sercop

# Columnas mostradas en la tabla y en el Excel.
COLUMNAS_OFERTAS: dict[str, str] = {
    "tipo_proceso": "Tipo de Proceso",
    "codigo": "Código del Proceso",
    "entidad": "Entidad Contratante",
    "provincia_canton": "Provincia - Cantón",
    "objeto_compra": "Objeto de Contratación",
    "estado": "Estado del Proceso",
    "fecha_publicacion": "Fecha de Publicación",
    "inicio_ofertas": "Inicio de Recepción de Ofertas",
    "fecha_limite_ofertas": "Fecha límite de Recepción de Ofertas",
    "dias_restantes": "Días restantes",
    "ofertas_recibidas": "Ofertas recibidas",
    "monto": "Presupuesto Referencial",
    "proveedor": "Proveedor adjudicado",
    "direccion_entrega": "Dirección",
    "contacto": "Contacto",
}

COLUMNAS_EXTRA_OFERTAS: dict[str, str] = {
    "fecha_limite_preguntas": "Fecha límite de preguntas",
    "enlace": "Enlace al detalle",
    "ocid": "OCID",
}

COLUMNAS_TEXTO = [
    "tipo_proceso",
    "codigo",
    "entidad",
    "provincia_canton",
    "objeto_compra",
    "estado",
    "fecha_publicacion",
    "inicio_ofertas",
    "fecha_limite_ofertas",
    "fecha_limite_preguntas",
    "direccion_entrega",
    "contacto",
    "proveedor",
    "enlace",
    "ocid",
]

ORDEN_VALIDO = {
    "fecha_publicacion": "fecha_publicacion_dt",
    "fecha_limite_ofertas": "fecha_limite_dt",
    "entidad": "entidad",
    "provincia": "provincia",
    "canton": "canton",
    "tipo": "tipo_proceso",
    "estado": "estado",
    "monto": "monto_num",
}


def _normalizar(valor: Any) -> str:
    if valor is None:
        return ""
    texto = str(valor).lower()
    return "".join(
        caracter
        for caracter in unicodedata.normalize("NFD", texto)
        if unicodedata.category(caracter) != "Mn"
    ).strip()


def _palabras(palabras_clave: str | Iterable[str] | None) -> list[str]:
    if palabras_clave is None:
        return []
    partes = (
        palabras_clave.split(",")
        if isinstance(palabras_clave, str)
        else list(palabras_clave)
    )
    return [parte.strip() for parte in partes if parte and len(parte.strip()) >= 3]


def _preparar(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza tipos, calcula días restantes y columnas auxiliares."""
    if df.empty:
        return df

    df = df.copy()
    if "ocid" in df.columns:
        df = df.drop_duplicates(subset=["ocid"])

    # El detalle puede faltar si el SERCOP rechazó la consulta: se aseguran columnas.
    for columna in COLUMNAS_TEXTO:
        if columna not in df.columns:
            df[columna] = ""
        df[columna] = df[columna].fillna("").astype(str)

    if "ofertas_recibidas" not in df.columns:
        df["ofertas_recibidas"] = None
    # Entero anulable: evita que se muestre como 6.0 y que NaN rompa el JSON.
    df["ofertas_recibidas"] = pd.to_numeric(df["ofertas_recibidas"], errors="coerce").astype("Int64")

    df["fecha_publicacion_dt"] = pd.to_datetime(
        df.get("fecha_publicacion"), errors="coerce"
    )
    limite = pd.to_datetime(df.get("fecha_limite_ofertas"), errors="coerce")
    df["fecha_limite_dt"] = limite

    ahora = pd.Timestamp(datetime.now())
    df["dias_restantes"] = (limite - ahora).dt.total_seconds() / 86400
    df.loc[limite.isna(), "dias_restantes"] = None

    df["monto_num"] = pd.to_numeric(df.get("monto"), errors="coerce")
    return df


async def obtener_ofertas(
    fecha_inicio: str,
    fecha_fin: str,
    palabras_clave: str | Iterable[str] | None,
    provincia: str | None = None,
    canton: str | None = None,
    estado: str | None = None,
    tipo: str | None = None,
    solo_abiertas: bool = True,
    cierra_en_horas: float | None = None,
    analizar: int = 10,
    max_paginas: int = 3,
    incluir_detalle: bool = False,
) -> tuple[pd.DataFrame, list[str], int]:
    """
    Devuelve (dataframe, avisos, procesos_analizados).

    `incluir_detalle` consulta el endpoint `record` (lento y limitado por el
    SERCOP) para obtener estado, fechas de recepción de ofertas y nº de ofertas.
    Se fuerza automáticamente cuando algún filtro lo necesita.
    """
    palabras = _palabras(palabras_clave)
    if not palabras:
        return pd.DataFrame(), ["Ingrese al menos una palabra clave de 3 caracteres."], 0

    necesita_detalle = bool(
        incluir_detalle or estado or solo_abiertas or cierra_en_horas is not None
    )

    base = await sercop.obtener_procesos_ocds(
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        palabras_clave=palabras,
        provincia=provincia,
        canton=canton,
        estado=None,  # el estado se filtra al final, ya con el detalle
        tipo=tipo,
        max_paginas=max_paginas,
        incluir_detalle=necesita_detalle,
        limite_detalle=max(1, min(analizar, 60)),
    )
    avisos = list(base.attrs.get("avisos", []))

    if base.empty:
        return base, avisos, 0

    df = _preparar(base)

    # Un proceso está "analizado" cuando el detalle aportó algún dato suyo.
    marca_detalle = (
        (df["estado"].str.len() > 0)
        | (df["inicio_ofertas"].str.len() > 0)
        | (df["fecha_limite_ofertas"].str.len() > 0)
    )
    analizados = int(marca_detalle.sum())

    if not necesita_detalle and not avisos:
        avisos.append(
            "El listado se muestra sin el detalle de cada proceso: active «Consultar "
            "detalle de ofertas» para ver estado, fechas de recepción de ofertas y "
            "número de ofertas recibidas."
        )

    if estado:
        df = df[df["estado"].map(_normalizar) == _normalizar(estado)]

    if solo_abiertas:
        df = df[df["dias_restantes"].fillna(-1) >= 0]

    if cierra_en_horas is not None:
        limite_dias = float(cierra_en_horas) / 24
        df = df[
            (df["dias_restantes"].fillna(-1) >= 0) & (df["dias_restantes"] <= limite_dias)
        ]

    df = df.reset_index(drop=True)
    df.attrs["avisos"] = avisos
    df.attrs["analizados"] = analizados
    return df, avisos, analizados


def ordenar(df: pd.DataFrame, orden: str = "fecha_publicacion", dir_orden: str = "desc") -> pd.DataFrame:
    if df.empty:
        return df
    columna = ORDEN_VALIDO.get(orden, "fecha_publicacion_dt")
    ascendente = str(dir_orden).lower() != "desc"
    ordenado = df.sort_values(
        by=columna, ascending=ascendente, na_position="last", kind="stable"
    )
    ordenado.attrs = dict(df.attrs)
    return ordenado


def paginar(df: pd.DataFrame, pagina: int = 1, por_pagina: int = 25) -> tuple[pd.DataFrame, int, int]:
    pagina = max(1, int(pagina or 1))
    por_pagina = max(1, min(int(por_pagina or 25), 500))
    total = len(df)
    total_paginas = max(1, -(-total // por_pagina))
    inicio = (pagina - 1) * por_pagina
    return df.iloc[inicio : inicio + por_pagina], total, total_paginas


def a_registros(df: pd.DataFrame, columnas: list[str]) -> list[dict]:
    if df.empty:
        return []
    disponibles = [columna for columna in columnas if columna in df.columns]
    salida = df[disponibles].copy()
    # `astype(object)` evita que los NaN vuelvan como NaN al reemplazarlos por None
    # (en columnas float pandas los reconvierte y rompen la serialización JSON).
    salida = salida.astype(object).where(pd.notnull(salida), None)
    return salida.to_dict(orient="records")


def columnas_json() -> list[str]:
    return list(COLUMNAS_OFERTAS.keys()) + ["provincia", "canton"] + list(COLUMNAS_EXTRA_OFERTAS.keys())


def df_exportable(df: pd.DataFrame) -> pd.DataFrame:
    columnas = {**COLUMNAS_OFERTAS, **COLUMNAS_EXTRA_OFERTAS}
    disponibles = [columna for columna in columnas if columna in df.columns]
    export = df[disponibles].copy()
    export["dias_restantes"] = export["dias_restantes"].apply(
        lambda valor: None if valor is None or pd.isna(valor) else round(float(valor), 1)
    )
    return export.rename(columns={columna: columnas[columna] for columna in disponibles})


def catalogo(df: pd.DataFrame) -> dict:
    """Tipos, provincias, cantones y estados presentes en los resultados."""
    if df.empty:
        return {"tipos": [], "provincias": [], "cantones": [], "estados": []}
    return {
        "tipos": sorted(x for x in df["tipo_proceso"].unique() if x),
        "provincias": sorted(x for x in df["provincia"].unique() if x),
        "cantones": sorted(x for x in df["canton"].unique() if x),
        "estados": sorted(x for x in df["estado"].unique() if x),
    }
