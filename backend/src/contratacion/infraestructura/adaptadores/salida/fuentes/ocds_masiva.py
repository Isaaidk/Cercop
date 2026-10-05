"""OCDS por **descarga masiva**: el mes entero en un fichero, no en diez mil peticiones.

    .\\.venv\\Scripts\\python.exe scripts\\importar_ocds_masivo.py --anio 2026

POR QUÉ EXISTE. El listado paginado del portal devuelve **diez filas por petición** y no acepta
ningún parámetro de tamaño (se probaron ocho: los ignora todos), así que el año 2026 son 10.363
peticiones contra un origen que responde 429 cada cinco o seis y con una latencia de dos a cuatro
segundos. Medido: ~9 s por página, o sea ~26 horas para el año. El portal publica además los mismos
procedimientos **en bloque**, un ZIP por año y mes: **doce peticiones** y minutos. El contraste de
totales cuadra —`get-totals` del año da 103.628, exactamente lo que cuenta el listado—, y el fichero
trae más por registro, no menos.

QUÉ TRAE QUE EL LISTADO NO. El fichero es el **OCDS estándar** (`tender`, `awards`, `parties`,
`planning`, `contracts`), y de ahí salen dos cosas que el listado deja vacías: el **proveedor
adjudicado** y el **monto**, que en el listado vienen a cero en muchos procesos. También trae las
clasificaciones **CPC** de los ítems, que hoy solo se consiguen leyendo la ficha de cada necesidad a
una petición por necesidad; **no se guardan todavía** (decisión del 2026-10-01: primero la vía, sin
ítems), pero están en el fichero y no habría que volver a pedirlas.

LA TRADUCCIÓN. La tubería de ingesta —mapeos, huella, `upsert`, historial, invalidación de caché— no
se toca: se le entrega una fila **plana con las mismas quince claves** que devuelve el listado, para
que `ocds_mapeos.MAPEOS_POR_DEFECTO` siga valiendo tal cual. Las equivalencias están comprobadas
poniendo las dos filas del mismo `ocid` una al lado de la otra
(`scripts/comparar_ocds_listado_masiva.py`), no leyendo la documentación del estándar:

| Clave plana | De dónde sale en el fichero masivo |
|---|---|
| `ocid` | `ocid` |
| `date` | `date` |
| `title` | `tender.title` |
| `internal_type` | `tender.procurementMethodDetails` |
| `description` | `tender.description` |
| `buyer` | `buyer.name` |
| `region` | `parties[].address.region` de la entidad compradora |
| `locality` | `parties[].address.locality` de la entidad compradora |
| `suppliers` | `awards[].suppliers[].name`, unidos por comas |
| `amount` | el mayor de `awards[].value.amount` |
| `id` | `tender.id` (el identificador del proceso en la fuente) |
| `year`, `month` | los dos primeros trozos de `date` |
| `method` | `tender.procurementMethod` |
| `budget` | `planning.budget.amount` |

LO QUE **NO** ES IGUAL, Y POR QUÉ. `id` en el listado es un número interno (3286295) que el fichero
no publica; se usa `tender.id`, que es el código del proceso y significa lo mismo que la etiqueta
del mapeo. Los importes van con **seis decimales**, como los del listado; no es cosmética:
`_a_decimal` lee `999.999` como miles —el punto separa miles en el formato ecuatoriano—, mientras
que `999.999000` no es ambiguo. Un importe enviado como número podría salir multiplicado por mil.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from contratacion.aplicacion.puertos.fuente import ResultadoExtraccion
from contratacion.dominio.ingesta import Presupuesto
from contratacion.infraestructura.adaptadores.salida.fuentes.ocds import CODIGO, FuenteOcds

BASE = "https://datosabiertos.compraspublicas.gob.ec/PLATAFORMA"
URL_DESCARGA = f"{BASE}/download"
URL_TOTALES = f"{BASE}/get-totals"

MESES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)

# Decimales con los que se escriben los importes, los mismos que publica el listado.
DECIMALES = 6

# Los campos que son dinero. Van aparte porque un cero en ellos significa «todavía no hay», y eso
# importa al combinar publicaciones de meses distintos: ver `combinar`.
CAMPOS_MONETARIOS = ("amount", "budget")


def nombre_del_mes(mes: int) -> str:
    """«septiembre» a partir de 9. Se usa en el nombre del fichero que sirve el portal."""
    return MESES[mes - 1]


def url_del_mes(anio: int, mes: int, tipo: str = "json") -> str:
    """URL del ZIP de un mes. El portal sirve el año por meses, así que `mes` es obligatorio."""
    return f"{URL_DESCARGA}?type={tipo}&year={anio}&month={mes}&method=all"


def url_de_totales(anio: int, mes: int) -> str:
    """URL que dice cuántos procedimientos hay, para contrastar lo que trae el fichero."""
    return f"{URL_TOTALES}?year={anio}&month={mes}&method=all"


def _importe(valor: Any) -> str | None:
    """Importe con seis decimales, o `None` si no hay número que escribir.

    Los seis decimales no son un adorno: `mapeo._a_decimal` interpreta `999.999` como miles —y haría
    el importe mil veces mayor—, mientras que `999.999000` no admite esa lectura.
    """
    if valor is None or isinstance(valor, bool):
        return None
    try:
        return f"{float(valor):.{DECIMALES}f}"
    except (TypeError, ValueError):
        return None


def _tipo_de_proceso(detalle: Any, metodo: Any) -> str | None:
    """El tipo de proceso, sin el convenio que el fichero arrastra detrás.

    En los catálogos electrónicos, `procurementMethodDetails` trae el convenio entero —«Catálogo
    electrónico - Compra directa en el convenio CDI-SERCOP-001-2016, PROVISIÓN DE PRODUCTOS DE
    CONFECCIÓN TEXTIL…»—, mientras que el listado publica solo el tipo. Se recorta en «en el
    convenio», que es exactamente donde el listado deja de escribir: sin ello la columna «Tipo de
    Necesidad» del panel sale con un párrafo, y ese párrafo entra además en el texto de búsqueda.
    """
    texto = str(detalle).strip() if detalle else ""
    if texto:
        return texto.split(" en el convenio")[0].strip() or texto
    return str(metodo) if metodo else None


def _direccion_del_comprador(publicacion: Mapping[str, Any]) -> Mapping[str, Any]:
    """La dirección de la entidad contratante: es de donde el listado saca provincia y cantón."""
    identificador = str((publicacion.get("buyer") or {}).get("id") or "")
    for parte in publicacion.get("parties") or []:
        if identificador and str(parte.get("id")) == identificador:
            direccion = parte.get("address") or {}
            if isinstance(direccion, Mapping):
                return direccion
    # Sin identificador con el que emparejar —ocurre—, la primera parte que traiga dirección es
    # mejor que ninguna: dejar la provincia vacía es peor que arriesgar la de la entidad compradora.
    for parte in publicacion.get("parties") or []:
        direccion = parte.get("address") or {}
        if not isinstance(direccion, Mapping):
            continue
        if direccion.get("region") or direccion.get("locality"):
            return direccion
    return {}


def traducir_publicacion(publicacion: Mapping[str, Any]) -> dict[str, Any]:
    """Una publicación OCDS → la fila plana que espera la tabla de mapeos.

    Se devuelven **todas** las claves, aunque falten datos, para que el mapeo no tenga que adivinar:
    una clave ausente y una clave vacía se comportan igual aguas abajo, pero la fila incompleta no
    se puede comparar con la del listado.
    """
    contrato = publicacion.get("tender") or {}
    planificacion = publicacion.get("planning") or {}
    adjudicaciones = publicacion.get("awards") or []
    fecha = str(publicacion.get("date") or "")

    proveedores = [
        str(proveedor.get("name"))
        for adjudicacion in adjudicaciones
        for proveedor in (adjudicacion.get("suppliers") or [])
        if proveedor.get("name")
    ]
    montos = [
        valor
        for adjudicacion in adjudicaciones
        if (valor := (adjudicacion.get("value") or {}).get("amount")) is not None
    ]
    direccion = _direccion_del_comprador(publicacion)
    presupuesto = (planificacion.get("budget") or {}).get("amount")

    return {
        "ocid": publicacion.get("ocid"),
        "date": fecha or None,
        # `tender.id` y `title` coinciden en la fuente; se usa el primero por ser el identificador
        # del proceso, que es lo que la etiqueta promete.
        "title": contrato.get("title") or contrato.get("id") or publicacion.get("ocid"),
        "internal_type": _tipo_de_proceso(
            contrato.get("procurementMethodDetails"), contrato.get("procurementMethod")
        ),
        "description": contrato.get("description"),
        "buyer": (publicacion.get("buyer") or {}).get("name"),
        "region": direccion.get("region"),
        "locality": direccion.get("locality"),
        "suppliers": ", ".join(proveedores) or None,
        # «0.000000» y no `None` cuando no hay adjudicación: es lo que publica el listado en esas
        # mismas filas, y cambiarlo movería el valor de la columna Monto de todas ellas.
        "amount": _importe(max(montos)) if montos else _importe(0),
        "id": contrato.get("id") or publicacion.get("id"),
        "year": int(fecha[:4]) if len(fecha) >= 4 and fecha[:4].isdigit() else None,
        "month": int(fecha[5:7]) if len(fecha) >= 7 and fecha[5:7].isdigit() else None,
        "method": contrato.get("procurementMethod"),
        "budget": _importe(presupuesto),
    }


def leer_publicaciones(ruta: Path) -> list[dict[str, Any]]:
    """Todas las publicaciones del ZIP. El portal sirve un único JSON con una lista de paquetes."""
    with ZipFile(ruta) as comprimido:
        nombres = [e.filename for e in comprimido.infolist() if e.filename.endswith(".json")]
        if not nombres:
            raise ValueError(f"El fichero {ruta.name} no trae ningún JSON")
        paquetes = json.loads(comprimido.read(nombres[0]).decode("utf-8"))
    if isinstance(paquetes, dict):
        paquetes = [paquetes]
    return [publicacion for paquete in paquetes for publicacion in (paquete.get("releases") or [])]


def traducir_fichero(ruta: Path) -> list[dict[str, Any]]:
    """Todas las filas planas de un ZIP, una por publicación."""
    return [traducir_publicacion(publicacion) for publicacion in leer_publicaciones(ruta)]


def _es_cero(valor: Any) -> bool:
    """¿El valor es un cero escrito como importe? `0`, `0.0`, `0.000000` sí; `0.01` no."""
    return isinstance(valor, str) and not valor.strip("0.")


def combinar(filas: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Junta las filas del mismo procedimiento, campo a campo: el primer dato que no venga vacío.

    Hace falta porque el fichero es un **delta de publicaciones**, no la foto del proceso: de las
    4.634 publicaciones de septiembre, **2.340 no traen `tender`** —son las de adjudicación y
    contrato, cuyo anuncio se publicó en un mes anterior—. Escribirlas seguidas sería destruirse la
    una a la otra: la de septiembre dejaría el título y la descripción en blanco, porque en esa
    publicación no están; y al revés, la de agosto borraría el proveedor y el monto.

    El `date` se queda con el **más antiguo**, que es la fecha de publicación del proceso: es el
    valor con el que se publica en el listado y con el que filtra el panel por fecha.
    """
    combinadas: dict[str, dict[str, Any]] = {}
    for fila in filas:
        clave = str(fila.get("ocid") or "")
        if not clave:
            continue
        actual = combinadas.get(clave)
        if actual is None:
            combinadas[clave] = dict(fila)
            continue
        for campo, valor in fila.items():
            if valor in (None, ""):
                continue
            # Un cero **no es un dato** en los importes: es lo que se publica mientras no hay
            # adjudicación. Ni entra ni deja sitio al importe de verdad, que llega en la publicación
            # de la adjudicación —posterior— y es el que tiene que quedar.
            if campo in CAMPOS_MONETARIOS and _es_cero(valor):
                continue
            if campo == "date":
                actual[campo] = min(str(actual.get(campo) or valor), str(valor))
                continue
            anterior = actual.get(campo)
            if anterior in (None, "") or (campo in CAMPOS_MONETARIOS and _es_cero(anterior)):
                actual[campo] = valor
    return list(combinadas.values())


class FuenteOcdsMasiva(FuenteOcds):
    """Procesos publicados, leídos de los ficheros mensuales en lugar del listado paginado.

    Hereda de `FuenteOcds` la clave natural —el `ocid`— y el criterio de términos, para que la fila
    que se guarde sea indistinguible de la que deja el listado: lo único que cambia es de dónde sale
    el crudo. Los meses que se le pasen se leen y se **combinan por `ocid`**, así que se le pueden
    dar los doce de un año aunque el orden no importe.

    **Siempre se declara parcial**, y es una decisión, no un descuido. El fichero es una foto del
    mes con horas de retraso —el de septiembre trae 4.634 procedimientos y el listado en vivo
    4.798—, así que una vuelta que lo lee **no** cubre el final del listado. Si se declarara
    completa, la marca de agua avanzaría y el ciclo siguiente creería estar al día: lo publicado
    entre la foto y el momento actual no entraría por ningún lado y nadie lo notaría.

    La ventana de la vuelta (`desde`, que el ciclo calcula con la marca de agua) **no se aplica**
    aquí, y es deliberado: la marca de agua habla del final del listado y un fichero de hace meses
    no tiene nada que ver con ella. Aplicarla descartaría casi todo el fichero en silencio. Para
    recortar de verdad se pasa `desde` al constructor, que es una decisión de quien importa.
    """

    codigo = CODIGO

    def __init__(self, rutas: Path | Sequence[Path], *, desde: datetime | None = None) -> None:
        super().__init__(())
        self._rutas = [rutas] if isinstance(rutas, Path) else list(rutas)
        self._desde = desde

    async def extraer(self, desde: datetime, presupuesto: Presupuesto) -> ResultadoExtraccion:
        """Traduce los ficheros y combina sus publicaciones. Gasta una petición por fichero."""
        resultado = ResultadoExtraccion(parcial=True)
        for _ in self._rutas:
            if not presupuesto.consumir():
                resultado.agoto_presupuesto = True
                return resultado
            resultado.peticiones += 1

        filas: list[dict[str, Any]] = []
        for ruta in self._rutas:
            filas.extend(traducir_fichero(ruta))
        for fila in combinar(filas):
            if self._desde is not None and not _es_posterior(fila.get("date"), self._desde):
                continue
            resultado.registros.append(fila)
        return resultado


def _es_posterior(fecha: Any, limite: datetime) -> bool:
    """¿La publicación es de después del límite? Una fecha ilegible se deja pasar.

    Dejarla pasar es lo correcto en este punto: descartarla perdería un registro por un problema de
    formato, y lo que decide si el dato vale es el mapeo, no el filtro de la ventana.
    """
    if not fecha:
        return True
    try:
        momento = datetime.fromisoformat(str(fecha).replace("Z", "+00:00"))
    except ValueError:
        return True
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=UTC)
    return momento >= limite
