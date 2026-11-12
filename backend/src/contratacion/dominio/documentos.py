"""Lectura de un TDR y armado de proforma.

El texto que no está en el documento no se inventa. El precio que el usuario no escribió no se
rellena: una proforma sin importe confirmado no sale.
"""

from __future__ import annotations

import itertools
import re
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from contratacion.dominio.errores import DatoInvalido
from contratacion.dominio.palabras import normalizar

AVISO_LECTURA = (
    "Resumen armado solo con los apartados que el documento titula. "
    "Lo que no aparece no se completa."
)
AVISO_PRECIOS = "Cada precio lo escribe quien arma el documento. El sistema no propone importes."

_TITULOS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("objeto", ("objeto de la contratacion", "objeto de contratacion", "objeto")),
    ("antecedentes", ("antecedentes",)),
    ("alcance", ("alcance",)),
    ("actividades", ("actividades", "actividad")),
    ("entregables", ("productos entregables", "entregables", "entregable")),
    ("plazos", ("cronograma", "plazos", "plazo")),
    ("presupuesto", ("presupuesto referencial", "presupuesto")),
    ("requisitos_tecnicos", ("especificaciones tecnicas", "requisitos tecnicos")),
    ("condiciones", ("condiciones de participacion", "condiciones")),
)

_ESTADOS = {"pendiente", "cumplido", "no_aplica"}
_TOPE = 2500

# ── Limpieza del texto que se muestra ──────────────────────────────────────────────────────────
# Los TDR son formularios: traen huecos para rellenar («……», «$.......», «____»), tablas que el PDF
# aplana en una línea, letras espaciadas de los encabezados y palabras partidas por el salto de
# columna. Copiado tal cual, el apartado era ilegible. Esta limpieza solo quita ruido de forma: no
# toca montos, fechas ni nombres, y ante la duda deja el texto como venía.

POR_COMPLETAR = "[por completar]"
_TABLA_DE_ITEMS = "[tabla de ítems y precios del formulario]"
# Una racha de puntos, elipsis o guiones bajos con al menos cuatro «puntos» de peso es un hueco
# del formulario. Tres puntos sueltos («etc...») son una elipsis de verdad y se respetan.
_RACHA_RELLENO = re.compile(r"[.…_](?: ?[.…_])*")
_MARCADORES_SEGUIDOS = re.compile(
    re.escape(POR_COMPLETAR) + r"(?:[\s.,:;/-]*" + re.escape(POR_COMPLETAR) + r")+"
)
# «I T E M»: cuatro o más mayúsculas sueltas separadas por un espacio. Con tres («A Y B») se
# arriesgaba a pegar una enumeración, así que no se toca.
_LETRAS_ESPACIADAS = re.compile(r"(?<!\w)((?:[A-ZÁÉÍÓÚÑ] ){3,}[A-ZÁÉÍÓÚÑ])(?!\w)")
# Palabra partida: «mi smo». La segunda mitad empieza con dos consonantes que ninguna palabra
# castellana usa al inicio («sm», «st», «ns»…), así que no puede ser una palabra por sí sola.
# La segunda mitad va en una búsqueda hacia delante para que cada palabra pueda ser primera mitad
# de la siguiente pareja («la mi smo»).
_PARTIDA = re.compile(r"(?<!\w)([a-záéíóúñ]{1,8}) (?=([a-záéíóúñü]{2,4})(?!\w))")
_VOCALES = set("aeiouáéíóúüy")
_INICIOS_VALIDOS = {
    "bl", "br", "cl", "cr", "dr", "fl", "fr", "gl", "gr", "kl", "kr", "pl", "pr", "tr", "tl",
    "ch", "ll", "ps", "pn", "gn", "sh", "th", "ph", "wh",
}  # fmt: skip
# Siglas y unidades que sí empiezan así y van en minúscula en algunos TDR.
_NO_UNIR = {
    "spa", "show", "slot", "spot", "star", "stop", "skin", "scan", "kva", "btu", "cpu", "gpu",
    "dpi", "hdmi", "vga", "mpa", "kpa", "lcd", "led", "ssd", "smd", "sms",
}  # fmt: skip
_GUIONES = "-\u2013"  # guion y raya corta
_VINETA = re.compile(r"(?<!\S)([-\u2013•·])\s+(?=\S)")
# Vocabulario del encabezado de la tabla de precios que el PDF pega dentro de otro campo
# («VIGENCIA: ITEM CPC DESCRIPCIÓN UNIDAD DE MEDIDA CANTIDAD V.UNITARIO V.TOTAL…»).
_ENCABEZADO_TABLA = {
    "item", "items", "no.", "nro.", "n°", "cpc", "descripcion", "unidad", "de", "medida",
    "cantidad", "v.unitario", "v.total", "v.", "valor", "unitario", "total", "subtotal", "iva",
    "15%", "12%", "precio", "p.unitario", "p.total", "unid.", "u.", "detalle",
}  # fmt: skip
_CLAVES_TABLA = {"cantidad", "subtotal", "v.unitario", "unitario", "v.total"}


def _hueco(encontrado: re.Match[str]) -> str:
    racha = encontrado.group(0)
    peso = racha.count(".") + racha.count("_") + 3 * racha.count("…")
    return f" {POR_COMPLETAR} " if peso >= 4 else racha


def _unir_partida(encontrado: re.Match[str]) -> str:
    primera, segunda = encontrado.group(1), encontrado.group(2)
    inicio = segunda[:2]
    imposible = (
        inicio[0] not in _VOCALES and inicio[1] not in _VOCALES and inicio not in _INICIOS_VALIDOS
    )
    if imposible and segunda not in _NO_UNIR and any(letra in _VOCALES for letra in segunda[2:]):
        return primera
    return encontrado.group(0)


def _sin_encabezado_de_tabla(texto: str) -> str:
    """Una racha de seis o más palabras del encabezado de la tabla de precios se resume en una."""
    palabras = list(re.finditer(r"\S+", texto))
    tramos: list[tuple[int, int]] = []
    inicio = 0
    while inicio < len(palabras):
        fin = inicio
        while fin < len(palabras) and normalizar(palabras[fin].group(0)) in _ENCABEZADO_TABLA:
            fin += 1
        racha = {normalizar(p.group(0)) for p in palabras[inicio:fin]}
        if fin - inicio >= 6 and racha & _CLAVES_TABLA:
            tramos.append((palabras[inicio].start(), palabras[fin - 1].end()))
        inicio = max(fin, inicio + 1)
    for desde, hasta in reversed(tramos):
        texto = texto[:desde] + _TABLA_DE_ITEMS + texto[hasta:]
    return texto


def _vinetas(texto: str) -> str:
    """Cada viñeta en su línea. Un guion solo cuenta como viñeta si abre una frase en mayúscula
    tras un punto, dos puntos o punto y coma: «Quito - Ecuador» es un guion, no una lista."""

    def poner(encontrado: re.Match[str]) -> str:
        signo = encontrado.group(1)
        if signo in _GUIONES:
            if not texto[encontrado.end() : encontrado.end() + 1].isupper():
                return encontrado.group(0)
            previo = texto[: encontrado.start()].rstrip()
            if previo and previo[-1] not in ".:;":
                return encontrado.group(0)
        marca = "-" if signo in _GUIONES else "•"
        return f"\n{marca} " if encontrado.start() > 0 else f"{marca} "

    return _VINETA.sub(poner, texto)


def cortar(texto: str, tope: int) -> str:
    """Recorta en el último fin de frase antes del tope, no a media palabra, y lo señala con «…»."""
    if len(texto) <= tope:
        return texto
    trozo = texto[: max(tope - 2, 1)]
    limite = max(trozo.rfind(signo) for signo in (". ", ".\n", "; ", "\n", "? ", "! "))
    if limite >= len(trozo) // 2:
        corte = trozo[: limite + 1]
    elif " " in trozo:
        corte = trozo[: trozo.rfind(" ")]
    else:
        corte = trozo
    corte = corte.rstrip(" \n,;:(" + _GUIONES)
    # «frase.…» se lee mal y «frase. …» volvería a parecer un hueco del formulario.
    return f"{corte.rstrip('.')}…"


def limpiar_texto(texto: Any, tope: int | None = None) -> str:
    """Texto de un apartado del TDR listo para leerse. Es idempotente: limpiar dos veces no cambia.

    Huecos del formulario → un solo «[por completar]»; «I T E M» → «ITEM»; «mi smo» → «mismo»;
    encabezado de la tabla de precios pegado → una marca; viñetas en su línea; espacios normales.
    """
    plano = " ".join(str(texto or "").split())
    if not plano:
        return ""
    plano = _RACHA_RELLENO.sub(_hueco, plano)
    plano = _MARCADORES_SEGUIDOS.sub(POR_COMPLETAR, plano)
    plano = _LETRAS_ESPACIADAS.sub(lambda m: m.group(1).replace(" ", ""), plano)
    plano = _PARTIDA.sub(_unir_partida, plano)
    plano = _sin_encabezado_de_tabla(plano)
    plano = " ".join(plano.split())
    # Los huecos dejan espacios delante de la puntuación («RUC [por completar] :»).
    plano = re.sub(r"\s+([:;,)])", r"\1", plano)
    plano = re.sub(r"\(\s+", "(", plano)
    plano = re.sub(r"\$\s+(?=\[)", "$", plano)
    plano = _MARCADORES_SEGUIDOS.sub(POR_COMPLETAR, plano)
    plano = _vinetas(plano)
    plano = "\n".join(linea.strip() for linea in plano.split("\n") if linea.strip())
    return cortar(plano, tope) if tope else plano


def _titulo(linea: str) -> str | None:
    plana = normalizar(linea)
    plana = re.sub(r"^[\d.\)\-\s]+", "", plana).strip(" :.-")
    if not plana or len(plana) > 80:
        return None
    for clave, variantes in _TITULOS:
        for variante in variantes:
            if plana == variante or plana.startswith(variante + " "):
                resto = plana[len(variante) :].strip()
                if len(resto) <= 24:
                    return clave
    return None


# Campos del formulario de necesidad de la entidad. Se reconocen por su etiqueta («FORMA DE PAGO:»)
# aunque el PDF llegue aplanado en una sola línea, que es como suelen salir.
_CAMPOS: dict[str, tuple[str, ...]] = {
    "numero": ("numero de proceso", "codigo del proceso", "numero"),
    "objeto": ("objeto de la contratacion", "objeto de contratacion"),
    "cpc": ("descripcion de cpc", "codigo cpc", "cpc"),
    "cantidad": ("cantidad requerida", "cantidad"),
    "especificaciones": (
        "especificaciones tecnicas",
        "caracteristicas tecnicas",
        "caracteristicas",
        "detalle del bien",
        "descripcion del bien",
    ),
    "plazo_entrega": (
        "plazo de entrega",
        "plazo de ejecucion",
        "plazo de la contratacion",
        "plazo",
    ),
    "forma_pago": ("forma de pago", "condiciones de pago"),
    "lugar_entrega": ("lugar de entrega", "lugar de ejecucion", "lugar"),
    "garantia": ("garantia tecnica", "garantia tecnologica", "garantia"),
    "vigencia_proforma": (
        "vigencia de la proforma",
        "validez de la proforma",
        "vigencia de la oferta",
        "validez de la oferta",
    ),
    "presupuesto": (
        "presupuesto referencial",
        "valor referencial",
        "monto referencial",
        "presupuesto",
    ),
    "contacto": ("correo electronico", "correo", "telefono", "contacto"),
}
ETIQUETAS_CAMPO = {
    "objeto": "Objeto de la contratación",
    "cpc": "Descripción de CPC",
    "cantidad": "Cantidad",
    "especificaciones": "Especificaciones técnicas",
    "plazo_entrega": "Plazo de entrega",
    "forma_pago": "Forma de pago",
    "lugar_entrega": "Lugar de entrega",
    "garantia": "Garantía",
    "vigencia_proforma": "Vigencia de la proforma",
    "presupuesto": "Presupuesto referencial",
    "contacto": "Contacto",
}
# Misma longitud que el original: así las posiciones del texto plano valen para el texto leído.
_PLANO = str.maketrans("áéíóúüñÁÉÍÓÚÜÑ", "aeiouunAEIOUUN")
_TOPE_CAMPO = 600
_ALTERNATIVAS = sorted(
    ((variante, clave) for clave, variantes in _CAMPOS.items() for variante in variantes),
    key=lambda par: -len(par[0]),
)
_ETIQUETA_CONOCIDA = re.compile(
    r"(?<![a-z0-9])(" + "|".join(re.escape(v) for v, _ in _ALTERNATIVAS) + r")\s*:"
)
_ETIQUETA_MAYUSCULAS = re.compile(r"[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ ]{2,60}:")
_CLAVE_DE = dict(_ALTERNATIVAS)


def _es_etiqueta(original: str, inicio: int, fin: int) -> bool:
    """Una etiqueta de formulario va en mayúsculas o abre línea; en medio de una frase, no.

    Sin esta regla, «plazo de entrega:» dentro de un párrafo legal («… el plazo de entrega: f)
    personal técnico…») se tomaba por el campo y se copiaba medio artículo a las condiciones de la
    oferta.
    """
    etiqueta = original[inicio : fin - 1].strip()
    return etiqueta.isupper() or inicio == 0 or original[inicio - 1] == "\n"


def extraer_campos(texto: str) -> dict[str, str]:
    """Los campos «ETIQUETA: valor» del formulario. El valor llega hasta la siguiente etiqueta.

    La etiqueta conocida va en mayúsculas o al inicio de línea; otra en mayúsculas corta el
    valor (FECHA, ÁREA REQUIRENTE…) sin guardarse. Si un campo aparece dos veces gana el primero.
    """
    original = str(texto or "")
    plano = original.translate(_PLANO).lower()
    marcas: list[tuple[int, int, str | None]] = [
        (m.start(), m.end(), _CLAVE_DE[m.group(1)])
        for m in _ETIQUETA_CONOCIDA.finditer(plano)
        if _es_etiqueta(original, m.start(), m.end())
    ]
    ocupadas = [(inicio, fin) for inicio, fin, _ in marcas]
    for m in _ETIQUETA_MAYUSCULAS.finditer(original):
        if not any(inicio <= m.start() < fin for inicio, fin in ocupadas):
            marcas.append((m.start(), m.end(), None))
    marcas.sort()
    campos: dict[str, str] = {}
    for indice, (_, fin, clave) in enumerate(marcas):
        if clave is None or clave in campos:
            continue
        siguiente = marcas[indice + 1][0] if indice + 1 < len(marcas) else len(original)
        valor = _NUMERO_SUELTO.sub("", " ".join(original[fin:siguiente].split()))
        valor = limpiar_texto(valor.strip(' "«»“”.;,'), _TOPE_CAMPO)
        if len(valor) >= 2 and valor != POR_COMPLETAR:
            campos[clave] = valor
    return campos


def extraer_secciones(texto: str) -> dict[str, str]:
    """Apartados titulados y campos del formulario. El cuerpo es texto del documento, recortado."""
    secciones = _secciones_tituladas(texto)
    for clave, valor in extraer_campos(texto).items():
        secciones.setdefault(clave, valor)
    return secciones


def _secciones_tituladas(texto: str) -> dict[str, str]:
    """Apartados reconocidos por su título, uno por línea."""
    secciones: dict[str, list[str]] = {}
    actual: str | None = None
    for linea in str(texto or "").splitlines():
        titulo = _titulo(linea)
        if titulo:
            actual = titulo
            secciones.setdefault(actual, [])
            continue
        if actual and linea.strip():
            secciones[actual].append(linea.strip())
    limpias = {clave: limpiar_texto(" ".join(partes), _TOPE) for clave, partes in secciones.items()}
    return {clave: texto for clave, texto in limpias.items() if texto}


_EXTENSIONES = (".pdf", ".doc", ".docx", ".zip", ".rar", ".xls", ".xlsx")
_UTILES = (
    "especificaciones",
    "plazo_entrega",
    "forma_pago",
    "objeto",
    "alcance",
    "entregables",
    "actividades",
    "requisitos_tecnicos",
    "condiciones",
    "plazos",
    "presupuesto",
)


def es_descarga(nombre: str, enlace: str = "") -> bool:
    """Un archivo publicado. El menú del portal (Buscador, Regresar, SNI) no lo es."""
    if "bajararchivo" in f"{nombre} {enlace}".lower():
        return True
    textos = (nombre.strip().lower(), enlace.strip().lower().split("?", 1)[0])
    return any(texto.endswith(extension) for texto in textos for extension in _EXTENSIONES)


def parece_enlace(texto: str) -> bool:
    """El portal a veces publica la dirección del archivo como si fuera su nombre."""
    plano = texto.strip().lower()
    return plano.startswith(("../", "./", "/", "http")) or "?" in plano or "bajararchivo" in plano


def documentos_legibles(documentos: list[Any]) -> list[dict[str, str]]:
    """Lista presentable de los archivos de una ficha: nombre humano y tipo si se conoce.

    El portal guarda como nombre el enlace de descarga cuando la celda no trae texto: enseñarlo tal
    cual da una hilera de direcciones ilegibles. Esos archivos se numeran («Documento 1»); los que
    sí tienen nombre lo conservan.
    """
    salida: list[dict[str, str]] = []
    for posicion, documento in enumerate((d for d in documentos if isinstance(d, dict)), start=1):
        nombre = str(documento.get("nombre") or "").strip()
        enlace = str(documento.get("enlace") or "")
        if not nombre or parece_enlace(nombre):
            etiqueta, tipo = f"Documento {posicion}", ""
        else:
            etiqueta = nombre
            sufijo = nombre.rsplit(".", 1)[-1].lower() if "." in nombre else ""
            tipo = sufijo.upper() if sufijo in {e.lstrip(".") for e in _EXTENSIONES} else ""
        salida.append({"nombre": etiqueta, "tipo": tipo, "tiene_enlace": "si" if enlace else ""})
    return salida


def _numero(valor: Any) -> float:
    try:
        return float(str(valor).replace(",", ".").strip())
    except (TypeError, ValueError):
        return 0.0


def items_pedidos(items: Any) -> list[dict[str, Any]]:
    """Los ítems que la entidad pide cotizar, listos para convertirlos en líneas de la proforma.

    La ficha los trae con CPC, nombre del CPC, descripción, unidad y cantidad (esta, como texto:
    «3.00»). El precio no está: lo escribe quien oferta. Sin ítems, lista vacía.
    """
    salida: list[dict[str, Any]] = []
    for posicion, item in enumerate(items if isinstance(items, list) else [], start=1):
        if not isinstance(item, dict):
            continue
        descripcion = " ".join(str(item.get("descripcion") or "").split())
        nombre_cpc = " ".join(str(item.get("descripcion_cpc") or "").split())
        if not (descripcion or nombre_cpc):
            continue
        salida.append(
            {
                "numero": int(item.get("numero") or posicion),
                "cpc": str(item.get("codigo") or "").strip(),
                "cpc_nombre": nombre_cpc,
                "descripcion": descripcion or nombre_cpc,
                "unidad": str(item.get("unidad") or "").strip(),
                "cantidad": _numero(item.get("cantidad")) or 1.0,
            }
        )
    return salida


def puntaje_secciones(secciones: dict[str, str]) -> int:
    """Cuántos apartados útiles trae el texto. Un informe de necesidad puntúa menos que el TDR."""
    return sum(1 for clave in _UTILES if secciones.get(clave))


def orden_de_lectura(nombres: list[str]) -> list[str]:
    """Un PDF titulado como TDR va primero. El resto de PDF y los textos van detrás."""

    def clave(nombre: str) -> tuple[int, int, str]:
        bajo = nombre.lower()
        if bajo.endswith(".pdf"):
            tipo = 0
        elif bajo.endswith(".txt"):
            tipo = 1
        else:
            tipo = 2
        relevante = 0 if any(pista in bajo for pista in ("tdr", "pliego", "termino")) else 1
        return (tipo, relevante, bajo)

    return sorted(nombres, key=clave)


def resumir_secciones(secciones: dict[str, str]) -> dict[str, Any]:
    """Las cinco preguntas del resumen, solo si el apartado existe.

    Se limpia otra vez porque las lecturas guardadas antes de la limpieza siguen en la base.
    """
    secciones = {clave: limpiar_texto(valor) for clave, valor in (secciones or {}).items()}
    return {
        "fuente": "tdr",
        "necesita": secciones.get("objeto") or secciones.get("alcance") or "",
        "entregar": secciones.get("entregables") or secciones.get("actividades") or "",
        "condiciones": secciones.get("condiciones")
        or secciones.get("requisitos_tecnicos")
        or secciones.get("especificaciones")
        or "",
        "documentos": secciones.get("requisitos_tecnicos") or "",
        "fechas": secciones.get("plazos") or secciones.get("plazo_entrega") or "",
        "presupuesto": secciones.get("presupuesto") or "",
        "pago": secciones.get("forma_pago") or "",
        "lugar": secciones.get("lugar_entrega") or "",
        "garantia": secciones.get("garantia") or "",
        "vigencia": secciones.get("vigencia_proforma") or "",
        "aviso": AVISO_LECTURA,
    }


# Ecuador no cambia de hora: siempre UTC-5. La base guarda UTC.
_HORA_ECUADOR = timezone(timedelta(hours=-5))


def _fecha_legible(valor: Any) -> str:
    """Fecha y hora en hora de Ecuador, por ejemplo `09/11/2026 16:11`."""
    if valor in (None, ""):
        return ""
    if isinstance(valor, str):
        try:
            valor = datetime.fromisoformat(valor)
        except ValueError:
            return str(valor)
    if not isinstance(valor, datetime):
        return str(valor)
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=UTC)
    return str(valor.astimezone(_HORA_ECUADOR).strftime("%d/%m/%Y %H:%M"))


_RUC_EN_CODIGO = re.compile(r"-(\d{13})-")
_TELEFONO = re.compile(r"(?<!\d)(?:\+?593[\s-]?)?\(?0?\d{1,2}\)?[\s-]?\d{3}[\s-]?\d{3,4}(?!\d)")


def datos_entidad(fila: dict[str, Any]) -> dict[str, str]:
    """RUC, dirección y teléfono de quien compra, con lo que la ficha publica.

    El RUC va dentro del código del proceso (`NIC-0360019760001-2026-00028`). La dirección es la
    de entrega más cantón y provincia, sin repetir. El teléfono, si el contacto trae uno.
    """
    ruc = _RUC_EN_CODIGO.search(str(fila.get("codigo") or ""))
    partes: list[str] = []
    for parte in (fila.get("direccion"), fila.get("canton"), fila.get("provincia")):
        texto = " ".join(str(parte or "").split())
        if texto and texto.lower() not in " ".join(partes).lower():
            partes.append(texto)
    telefono = str(fila.get("telefono") or "")
    if not telefono:
        encontrado = _TELEFONO.search(str(fila.get("contacto") or ""))
        telefono = encontrado.group(0).strip() if encontrado else ""
    return {
        "ruc": ruc.group(1) if ruc else "",
        "direccion": ", ".join(partes),
        "telefono": telefono,
    }


def resumir_ficha(fila: dict[str, Any]) -> dict[str, Any]:
    """Resumen de una oportunidad ya guardada, con los campos que la ficha publica.

    Los entregables y las condiciones no están en el listado: viven en el TDR. Por eso van vacíos
    y la interfaz lo dice, en vez de afirmar que el documento no los trae.
    """
    lista = documentos_legibles(list(fila.get("documentos") or []))
    documentos = [documento["nombre"] for documento in lista]
    fechas = " · ".join(
        parte
        for parte in (
            f"Publicación {_fecha_legible(fila.get('fecha_publicacion'))}"
            if fila.get("fecha_publicacion")
            else "",
            f"Límite {_fecha_legible(fila.get('plazo'))}" if fila.get("plazo") else "",
        )
        if parte
    )
    monto = fila.get("presupuesto") or fila.get("monto")
    return {
        "fuente": "ficha",
        "necesita": fila.get("objeto") or "",
        "entregar": "",
        "condiciones": "",
        "documentos": ", ".join(documentos),
        "documentos_lista": lista,
        "items_pedidos": items_pedidos(fila.get("items")),
        "fechas": fechas,
        "presupuesto": "" if monto in (None, "") else str(monto),
        "aviso": (
            "Resumen de la ficha publicada. Los entregables y las condiciones salen del TDR, "
            "no de este listado."
        ),
    }


# Campo del formulario del TDR: «OBJETO DE LA CONTRATACIÓN: …», «DESCRIPCIÓN DE CPC: …». La etiqueta
# va en mayúsculas y termina en dos puntos; el valor llega hasta la siguiente etiqueta.
_ETIQUETA = re.compile(r"[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ ]{2,60}:")
# Datos de identificación del formulario (quién compra, cuándo, con qué número). No son requisitos
# que el oferente cumpla, así que no pasan a la lista ni a la proforma.
_DATOS_DEL_FORMULARIO = {
    "fecha",
    "area requirente",
    "requirente",
    "tipo de producto",
    "tipo de procedimiento",
    "numero",
    "procedimiento de contratacion",
    "cuantia",
    "entidad",
    "ruc",
    "ciudad",
    "lugar",
    "proceso",
    "codigo del proceso",
}
_NUMERO_SUELTO = re.compile(r"\s+R\d{1,3}\s*$")


def _campos_y_frases(cuerpo: str) -> list[str]:
    """Los campos «ETIQUETA: valor» enteros; lo que no tiene etiqueta se parte por frases."""
    cortes = [m.start() for m in _ETIQUETA.finditer(cuerpo)]
    if not cortes:
        return re.split(r"[\n;•]|(?<=\.)\s+", cuerpo)
    bordes = [0, *(c for c in cortes if c > 0), len(cuerpo)]
    salida: list[str] = []
    for inicio, fin in itertools.pairwise(bordes):
        trozo = cuerpo[inicio:fin]
        etiqueta = _ETIQUETA.match(trozo)
        if etiqueta:
            if normalizar(etiqueta.group(0)[:-1]) in _DATOS_DEL_FORMULARIO:
                continue
            salida.append(trozo)
        else:
            salida.extend(re.split(r"[\n;•]|(?<=\.)\s+", trozo))
    return salida


def checklist(secciones: dict[str, str]) -> list[str]:
    """Requisitos verificables: un campo del formulario o una línea del documento, sin metadatos."""
    vistos: list[str] = []
    for clave in ("requisitos_tecnicos", "condiciones", "entregables", "actividades", "objeto"):
        cuerpo = secciones.get(clave) or ""
        for trozo in _campos_y_frases(limpiar_texto(cuerpo)):
            texto = _NUMERO_SUELTO.sub("", " ".join(trozo.split())).strip().lstrip("-•· ")
            # «(de ser el caso)» suelto completa al requisito anterior; no es uno nuevo.
            if vistos and re.fullmatch(r"\([^()]{1,60}\)\.?", texto):
                vistos[-1] = cortar(f"{vistos[-1]} {texto}", 400)
                continue
            if len(texto) < 8 or texto in vistos or texto.strip(" .") == POR_COMPLETAR:
                continue
            vistos.append(cortar(texto, 400))
            if len(vistos) >= 40:
                return vistos
    for clave in (
        "especificaciones",
        "cpc",
        "cantidad",
        "plazo_entrega",
        "forma_pago",
        "lugar_entrega",
        "garantia",
    ):
        valor = limpiar_texto(secciones.get(clave))
        texto = f"{ETIQUETAS_CAMPO[clave]}: {valor}".strip()
        if valor and not any(v.lower().startswith(texto[:30].lower()) for v in vistos):
            vistos.append(cortar(" ".join(texto.split()), 400))
    return vistos[:40]


def exigir_estado(estado: str) -> str:
    if estado not in _ESTADOS:
        raise DatoInvalido("El estado es pendiente, cumplido o no aplicable.")
    return estado


def calcular_proforma(lineas: list[dict[str, Any]], impuesto_porcentaje: float) -> dict[str, Any]:
    """Subtotales a partir de cantidades y precios que ya vienen escritos."""
    if impuesto_porcentaje is None or impuesto_porcentaje < 0 or impuesto_porcentaje > 100:
        raise DatoInvalido("Indica el porcentaje de impuesto, entre 0 y 100.")
    if not lineas:
        raise DatoInvalido("La proforma necesita al menos un producto o servicio.")
    armadas = []
    for linea in lineas:
        descripcion = str(linea.get("descripcion") or "").strip()
        if not descripcion:
            raise DatoInvalido("Cada línea necesita una descripción.")
        if linea.get("precio_unitario") is None or linea.get("cantidad") is None:
            raise DatoInvalido(AVISO_PRECIOS)
        precio = float(linea["precio_unitario"])
        cantidad = float(linea["cantidad"])
        if precio < 0 or cantidad <= 0:
            raise DatoInvalido("La cantidad es mayor que cero y el precio no es negativo.")
        armada: dict[str, Any] = {
            "descripcion": descripcion,
            "cantidad": cantidad,
            "precio_unitario": precio,
            "subtotal": round(cantidad * precio, 2),
        }
        # El CPC viaja con la línea: es la columna que la entidad compara con su pedido.
        cpc = str(linea.get("cpc") or "").strip()[:20]
        if cpc:
            armada["cpc"] = cpc
            armada["cpc_nombre"] = str(linea.get("cpc_nombre") or "").strip()[:200]
        unidad = str(linea.get("unidad") or "").strip()[:30]
        if unidad:
            armada["unidad"] = unidad
        armadas.append(armada)
    subtotal = round(sum(linea["subtotal"] for linea in armadas), 2)
    impuesto = round(subtotal * float(impuesto_porcentaje) / 100, 2)
    return {
        "lineas": armadas,
        "subtotal": subtotal,
        "impuesto": impuesto,
        "impuesto_porcentaje": float(impuesto_porcentaje),
        "total": round(subtotal + impuesto, 2),
        "aviso": AVISO_PRECIOS,
    }


def contrastar(
    requisitos: list[str],
    lineas: list[dict[str, Any]],
    *,
    texto_extra: str = "",
    cumplimiento: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Qué requisito responde la proforma. Mira las líneas, la carta y cada respuesta escrita."""
    texto = normalizar(
        " ".join(str(linea.get("descripcion") or "") for linea in lineas) + " " + texto_extra
    )
    cubiertos: list[str] = []
    faltantes: list[str] = []
    for requisito in requisitos:
        tokens = [token for token in normalizar(requisito).split() if len(token) >= 5]
        aciertos = sum(1 for token in tokens if token in texto)
        if (tokens and aciertos >= max(1, len(tokens) // 3)) or _tiene_respuesta(
            requisito, cumplimiento or []
        ):
            cubiertos.append(requisito)
        else:
            faltantes.append(requisito)
    inconsistencias = []
    if any(float(linea.get("precio_unitario") or 0) == 0 for linea in lineas):
        inconsistencias.append("Hay una línea con precio cero. Confírmalo antes de enviarla.")
    if not lineas:
        inconsistencias.append("La proforma no tiene líneas.")
    return {
        "cubiertos": cubiertos,
        "no_cubiertos": faltantes,
        "faltantes": faltantes,
        "inconsistencias": inconsistencias,
        "observaciones": (
            "Un requisito cuenta como cubierto cuando la proforma lo responde: en una línea, "
            "en la carta o en «Cómo cumples». No sustituye la lectura del TDR."
        ),
    }


def _tiene_respuesta(requisito: str, cumplimiento: list[dict[str, Any]]) -> bool:
    """El requisito tiene una respuesta escrita, aunque no repita sus palabras."""
    buscado = {token for token in normalizar(requisito).split() if len(token) >= 5}
    if not buscado:
        return False
    for fila in cumplimiento:
        if not str(fila.get("como_cumple") or "").strip():
            continue
        propio = {
            token
            for token in normalizar(str(fila.get("requisito") or "")).split()
            if len(token) >= 5
        }
        if len(buscado & propio) >= max(1, len(buscado) // 3):
            return True
    return False
