"""La ficha de **un** proceso de OCDS, leída de `record?ocid=…`: anexos, monto y aclaraciones.

Es lo que pidió el cliente para armar la proforma de un proceso con oferta: «que traiga los anexos
—TDR, pliegos, actas, solo la última acta— y que se sepa el monto del proceso».

QUÉ TRAE DE VERDAD LA API (comprobado el 2026-11-11 contra la fuente)
--------------------------------------------------------------------
Se pidieron seis `record` reales de tipos distintos —Subasta Inversa Electrónica, Régimen Especial
(repuestos), Licitación (dos), Catálogo electrónico y un proceso todavía en planificación—. Todos
devuelven `{"releases": [<una publicación compilada>], ...}`: **no hay `compiledRelease` ni
`records[]`**, la publicación compilada va dentro de `releases`.

1. **Documentos: ninguno.** Ni `tender.documents`, ni `planning.documents`, ni en `awards` ni en
   `contracts`: la palabra `documents` no aparece en ninguno de los seis, y la única URL que traen
   son las de la web de la entidad (`parties[].contactPoint.url`) y la del catálogo CPC. La página
   del proceso en el portal de datos abiertos (`PLATAFORMA/ocds/<ocid>`) pinta el mismo JSON
   (`window.ocds = …`) y tampoco tiene archivos. Los pliegos, TDR y actas viven en el portal
   transaccional del SERCOP (`compraspublicas.gob.ec/ProcesoContratacion/...`), al que el `ocid` no
   lleva: ese portal abre los procesos por un `idSoliCompra` que OCDS no publica.

   Aun así, este módulo lee los cinco sitios donde el estándar pone documentos (`planning`,
   `tender`, `awards[]`, `contracts[]` y `contracts[].implementation`): son baratos de mirar y, si
   el SERCOP empieza a publicarlos, salen solos sin tocar nada. Mientras tanto la respuesta lo dice
   y manda al buscador del portal con el código del proceso.

2. **Monto: sí, en tres sitios y no siempre en el mismo.**

   - `tender.value.amount`: el presupuesto referencial del proceso (15600 en
     `RE-RA-HEEE-2026-002`, 50139.42 en una licitación, 593664.5 en un catálogo). Falta en las
     subastas inversas.
   - `tender.lots[].value.amount`: lo que traen las subastas en su lugar (59091.14 en
     `SIE-CCQAHDNT-2026-020`, 17375 en `SIE-CCFFAA-2026-004`).
   - `planning.budget.amount`, **anidado y fuera del estándar**: el SERCOP escribe
     `{"budget": {"id": "2026.320…", "amount": {"amount": 15600, "currency": "USD"}}}`, con el
     importe **dentro de otro `amount`**. El estándar lo pone plano (`"amount": 15600`), y por eso
     se aceptan las dos formas. Muchas veces viene solo el `id` de la partida, sin importe.

   El adjudicado está aparte, en `awards[].value.amount` (56125 frente a los 59091.14 del lote).

3. **Aclaraciones: a veces.** Los procesos con preguntas traen `tender.enquiries[]` con la pregunta
   (`description`), la respuesta (`answer`) y sus fechas (`date`, `dateAnswered`). Es el contenido
   del «acta de preguntas y respuestas» que la proforma tiene que respetar, así que se devuelven
   también, de la más reciente a la más antigua.

Una consulta cuesta una petición (~1,3 s) a un servicio ajeno que responde 429 si se le aprieta:
va con su cortacircuitos y compartimento, igual que `historial.py`, y la ficha se recuerda media
hora —los documentos de un proceso cambian poco—.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import unquote, urlsplit

import httpx

from contratacion.aplicacion.hilos import MemoLru
from contratacion.dominio.errores import EstadoInvalido, NoEncontrado
from contratacion.infraestructura.adaptadores.salida.resiliencia import Cortacircuitos, circuito

_BASE = "https://datosabiertos.compraspublicas.gob.ec/PLATAFORMA/api"
_TIMEOUT = httpx.Timeout(20.0, connect=8.0)
_ENCABEZADOS = {"Accept": "application/json", "User-Agent": "Mozilla/5.0 (CercoApp)"}

# Media hora con datos; cinco minutos sin ninguno, porque «sin nada» puede ser un proceso recién
# publicado al que todavía le falta la mitad.
_TTL_SEG = 1800.0
_TTL_VACIO_SEG = 300.0
_MAXIMO_RECORDADOS = 1024
# Datos públicos del portal, por `ocid`: se comparten entre empresas sin riesgo. LRU acotada.
_RECORDADOS: MemoLru[str, tuple[float, dict[str, Any]]] = MemoLru(_MAXIMO_RECORDADOS)

# Aclaraciones que se devuelven como mucho: las últimas son las que corrigen a las anteriores.
MAX_ACLARACIONES = 20

_NO_DISPONIBLE = (
    "No se pudo consultar el proceso en los datos abiertos del SERCOP en este momento. "
    "Inténtalo en unos minutos."
)
_CIRCUITO = {
    "mensaje": (
        "Los datos abiertos del SERCOP no responden ahora. Inténtalo en unos minutos; mientras "
        "tanto puedes abrir el proceso en el portal."
    ),
    "umbral_fallos": 3,
    "enfriamiento_seg": 120.0,
    # Una petición por ficha: ocho a la vez por proceso de API sobran, y quien llega con todas
    # ocupadas espera dos segundos antes de recibir «inténtalo en unos segundos».
    "max_concurrencia": 8,
    "espera_turno_seg": 2.0,
    "limite_seg": 30.0,
}

# Dónde pone el estándar el importe, en el orden en que se prefiere, con lo que se le dice a
# la persona. El primero que traiga un número gana.
ETIQUETAS_FUENTE_MONTO = {
    "tender.value": "Presupuesto referencial del proceso",
    "tender.lots": "Suma del presupuesto de los lotes",
    "planning.budget": "Presupuesto de la planificación",
}


def circuito_procesos() -> Cortacircuitos:
    return circuito("ocds_procesos", **_CIRCUITO)


# --- Lectura pura del `record` --------------------------------------------- #


def publicacion_compilada(record: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """La publicación compilada del proceso.

    El SERCOP la manda en `releases[0]` (comprobado); el estándar la pone en
    `records[0].compiledRelease` o en `compiledRelease`. Se aceptan las tres para no depender de
    cuál use la fuente el día de mañana.
    """
    compilada = record.get("compiledRelease")
    if isinstance(compilada, Mapping):
        return compilada
    for registro in record.get("records") or []:
        compilada = registro.get("compiledRelease") if isinstance(registro, Mapping) else None
        if isinstance(compilada, Mapping):
            return compilada
    publicaciones = [p for p in record.get("releases") or [] if isinstance(p, Mapping)]
    if not publicaciones:
        return None
    # Si viniera más de una, la compilada es la más reciente.
    return max(publicaciones, key=lambda p: str(p.get("date") or ""))


def _numero(valor: Any) -> float | None:
    """Un importe como número, aceptando la forma anidada del SERCOP (`{"amount": {...}}`)."""
    for _ in range(3):
        if isinstance(valor, Mapping):
            valor = valor.get("amount")
    if valor is None or isinstance(valor, bool):
        return None
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    return numero if numero > 0 else None


def _moneda(valor: Any) -> str | None:
    for _ in range(3):
        if not isinstance(valor, Mapping):
            return None
        if valor.get("currency"):
            return str(valor["currency"])
        valor = valor.get("amount")
    return None


def presupuesto_del_proceso(publicacion: Mapping[str, Any]) -> dict[str, Any] | None:
    """El monto del proceso y de dónde sale: `tender.value` → lotes → `planning.budget`."""
    contrato = publicacion.get("tender") or {}
    planificacion = publicacion.get("planning") or {}

    valor = contrato.get("value")
    monto = _numero(valor)
    if monto is not None:
        return _monto(monto, _moneda(valor), "tender.value")

    lotes = [lote.get("value") for lote in contrato.get("lots") or [] if isinstance(lote, Mapping)]
    importes = [m for m in (_numero(v) for v in lotes) if m is not None]
    if importes:
        moneda = next((m for m in (_moneda(v) for v in lotes) if m), None)
        return _monto(round(sum(importes), 2), moneda, "tender.lots")

    presupuesto = planificacion.get("budget")
    monto = _numero(presupuesto)
    if monto is not None:
        return _monto(monto, _moneda(presupuesto), "planning.budget")
    return None


def adjudicado_del_proceso(publicacion: Mapping[str, Any]) -> dict[str, Any] | None:
    """Lo adjudicado (`awards[].value`), sumado si hay varias. Va aparte del monto."""
    valores = [a.get("value") for a in publicacion.get("awards") or [] if isinstance(a, Mapping)]
    importes = [m for m in (_numero(v) for v in valores) if m is not None]
    if not importes:
        return None
    moneda = next((m for m in (_moneda(v) for v in valores) if m), None)
    return {"monto": round(sum(importes), 2), "moneda": moneda or "USD"}


def _monto(monto: float, moneda: str | None, fuente: str) -> dict[str, Any]:
    return {
        "monto": monto,
        "moneda": moneda or "USD",
        "fuente": fuente,
        "etiqueta_fuente": ETIQUETAS_FUENTE_MONTO[fuente],
    }


def _nombre_del_documento(documento: Mapping[str, Any], url: str) -> str:
    """El título; si falta, el nombre del archivo de la URL; si tampoco, el tipo del estándar."""
    titulo = str(documento.get("title") or "").strip()
    if titulo:
        return titulo
    archivo = unquote(urlsplit(url).path.rsplit("/", 1)[-1]).strip()
    if archivo:
        return archivo
    return str(documento.get("documentType") or "Documento").strip()


def documentos_del_proceso(publicacion: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Todos los documentos que publique el proceso, en la forma que espera `elegir_anexos`.

    Solo se aceptan URL http(s): el valor viene de fuera y acaba en un `href`. Una misma URL que
    aparezca en dos etapas se devuelve una vez.
    """
    contrato = publicacion.get("tender") or {}
    planificacion = publicacion.get("planning") or {}
    origenes: list[tuple[str, Any]] = [
        ("planificación", planificacion.get("documents")),
        ("convocatoria", contrato.get("documents")),
    ]
    for adjudicacion in publicacion.get("awards") or []:
        if isinstance(adjudicacion, Mapping):
            origenes.append(("adjudicación", adjudicacion.get("documents")))
    for contratacion in publicacion.get("contracts") or []:
        if isinstance(contratacion, Mapping):
            origenes.append(("contrato", contratacion.get("documents")))
            ejecucion = contratacion.get("implementation") or {}
            if isinstance(ejecucion, Mapping):
                origenes.append(("ejecución", ejecucion.get("documents")))

    vistos: set[str] = set()
    documentos: list[dict[str, Any]] = []
    for etapa, lista in origenes:
        for documento in lista or []:
            if not isinstance(documento, Mapping):
                continue
            url = str(documento.get("url") or "").strip()
            if not url.lower().startswith(("http://", "https://")) or url in vistos:
                continue
            vistos.add(url)
            documentos.append(
                {
                    "nombre": _nombre_del_documento(documento, url),
                    "enlace": url,
                    "fecha": documento.get("datePublished") or documento.get("dateModified"),
                    "tipo_fuente": str(documento.get("documentType") or ""),
                    "formato": documento.get("format"),
                    "descripcion": documento.get("description"),
                    "etapa": etapa,
                }
            )
    return documentos


def aclaraciones_del_proceso(publicacion: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Preguntas y respuestas (`tender.enquiries`), de la más reciente a la más antigua."""
    preguntas = [
        {
            "fecha": consulta.get("date"),
            "pregunta": str(consulta.get("description") or consulta.get("title") or "").strip(),
            "respuesta": str(consulta.get("answer") or "").strip(),
            "fecha_respuesta": consulta.get("dateAnswered"),
        }
        for consulta in (publicacion.get("tender") or {}).get("enquiries") or []
        if isinstance(consulta, Mapping)
    ]
    preguntas = [p for p in preguntas if p["pregunta"] or p["respuesta"]]
    preguntas.sort(key=lambda p: str(p["fecha_respuesta"] or p["fecha"] or ""), reverse=True)
    return preguntas[:MAX_ACLARACIONES]


def ficha_del_record(record: Mapping[str, Any]) -> dict[str, Any] | None:
    """La ficha del proceso a partir del `record`, o `None` si no trae ninguna publicación."""
    publicacion = publicacion_compilada(record)
    if publicacion is None:
        return None
    contrato = publicacion.get("tender") or {}
    return {
        "ocid": publicacion.get("ocid"),
        "codigo": contrato.get("id") or contrato.get("title"),
        "estado": contrato.get("status"),
        "fecha": publicacion.get("date"),
        "documentos": documentos_del_proceso(publicacion),
        "presupuesto": presupuesto_del_proceso(publicacion),
        "adjudicado": adjudicado_del_proceso(publicacion),
        "aclaraciones": aclaraciones_del_proceso(publicacion),
    }


# --- Consulta a la fuente ------------------------------------------------- #


class FichasOcds:
    """Implementa `aplicacion.puertos.anexos.FichasDeProceso` contra la API pública."""

    def __init__(self, *, transporte: httpx.AsyncBaseTransport | None = None) -> None:
        self._transporte = transporte

    async def leer(self, ocid: str) -> dict[str, Any]:
        guardada = _RECORDADOS.get(ocid)
        if guardada:
            ficha = guardada[1]
            vigencia = _TTL_SEG if ficha["documentos"] or ficha["presupuesto"] else _TTL_VACIO_SEG
            if time.monotonic() - guardada[0] < vigencia:
                return ficha

        async with (
            circuito_procesos().proteger(),
            httpx.AsyncClient(
                timeout=_TIMEOUT, headers=_ENCABEZADOS, transport=self._transporte
            ) as cliente,
        ):
            try:
                respuesta = await cliente.get(f"{_BASE}/record", params={"ocid": ocid})
                if respuesta.status_code == 404:
                    raise NoEncontrado("Los datos abiertos del SERCOP no tienen este proceso.")
                respuesta.raise_for_status()
                record = respuesta.json()
            except (httpx.HTTPError, ValueError) as error:
                raise EstadoInvalido(_NO_DISPONIBLE) from error

        nueva = ficha_del_record(record) if isinstance(record, Mapping) else None
        if nueva is None:
            raise NoEncontrado("Los datos abiertos del SERCOP no tienen este proceso.")
        _RECORDADOS[ocid] = (time.monotonic(), nueva)
        return nueva


def olvidar_fichas() -> None:
    """Vacía la memoria de fichas. Lo usan las pruebas."""
    _RECORDADOS.clear()


def obtener_fichas() -> FichasOcds:
    return FichasOcds()
