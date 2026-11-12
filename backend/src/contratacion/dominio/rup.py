"""Lectura de los certificados que la empresa sube en PDF: el RUP del SERCOP y el RUC del SRI.

El RUP no tiene consulta pública: su lista de CPC solo se ve entrando al SOCE con el usuario de la
empresa («Datos generales → Imprimir RUP»). La empresa lo imprime y lo sube, y muchas veces sube
**junto** el certificado del RUC del SRI (el ejemplo real que se usó para escribir esto trae los dos
en un solo PDF: dos páginas del SRI y una del RUP). Se leen los dos:

- **RUP:** estado (HABILITADO…), categoría, nombre completo, correo, dirección y la tabla «Bienes,
  Obras o Servicios Suministrados» con **cada CPC y su descripción**.
- **RUC (SRI):** razón social, tipo de contribuyente, régimen, contabilidad, dirección completa,
  teléfono, celular, correo y las **actividades económicas con su código CIIU**.

El orden del texto que saca `pypdf` no siempre es el de la página (en el certificado del SRI el
valor sale **antes** que su etiqueta), así que no se lee por posiciones: cada dato tiene su regla,
y el resultado es una **propuesta** que la persona revisa antes de cargar. Nada se guarda aquí.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from contratacion.dominio.verificacion import ruc_valido

_CORREO = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_RUC = re.compile(r"(?<!\d)(\d{13})(?!\d)")
_CEDULA = re.compile(r"(?<!\d)(\d{10})(?!\d)")
_TELEFONO = re.compile(r"(?<!\d)(?:\+?593\s?)?0?\d{8,9}(?!\d)")

# Fila de la tabla de CPC del RUP: el código al **inicio** de la línea y la descripción detrás.
_FILA_CPC = re.compile(r"^\s*(\d{5}(?:\.\d{2}\.\d{1,2})?|\d{5,9})\s+(\S.*)$")
# Fila de actividad del SRI: «• G46491102 - VENTA AL POR MAYOR…».
_FILA_CIIU = re.compile(r"^\s*[•·\-*]?\s*([A-U]\d{4,8})\s*-\s*(.+)$")
# Encabezados que abren y cierran la tabla de CPC del RUP.
_INICIO_CPC = re.compile(
    r"bienes,?\s+obras\s+o\s+servicios|^\s*c[oó]digo\s+producto\s*$|^\s*cpc\b", re.IGNORECASE
)
_FIN_CPC = re.compile(
    r"el presente documento|responsable:|firmado electr|validar documento", re.IGNORECASE
)
# Fin del bloque de actividades del SRI.
_FIN_CIIU = re.compile(r"^\s*(establecimientos|obligaciones tributarias)\s*$", re.IGNORECASE)
# Cabeceras y pies que el SRI repite en cada página y cortan el bloque de actividades.
_RUIDO_PAGINA = re.compile(
    r"^\s*(n[uú]mero ruc|apellidos y nombres|raz[oó]n social|\d+\s*/\s*\d+|www\.sri)|\d{13}",
    re.IGNORECASE,
)
# Una etiqueta del certificado: «Número:», «Correo Electrónico:», «Teléfono(s):». Los valores van
# en mayúsculas, así que exigir minúsculas tras la inicial separa etiqueta de valor.
_ETIQUETA = r"\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ()]+(?:\s[A-ZÁÉÍÓÚÑa-záéíóúñ][a-záéíóúñ()]+)?:|$"

ESTADOS_RUP = {
    "habilitado": "habilitado",
    "pasivo": "pasivo",
    "suspendido": "suspendido",
    "inhabilitado": "suspendido",
}

_TOPE_CPC = 150
_TOPE_CIIU = 40


def _plano(texto: str) -> str:
    base = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in base if not unicodedata.combining(c)).lower()


def _lineas(texto: str) -> list[str]:
    return [" ".join(linea.split()) for linea in texto.splitlines() if linea.strip()]


def _titulo(texto: str) -> str:
    pequenas = {"de", "del", "la", "las", "los", "y", "e", "el"}
    palabras = str(texto or "").strip().lower().split()
    return " ".join(
        p if n and p in pequenas else p[:1].upper() + p[1:] for n, p in enumerate(palabras)
    )


def _tras(texto: str, etiqueta: str, hasta: str = _ETIQUETA) -> str:
    """Valor que sigue a «Etiqueta:» en la **misma** línea, hasta la siguiente etiqueta."""
    hallado = re.search(
        # Solo la etiqueta ignora mayúsculas: la que cierra el valor se distingue precisamente por
        # ir en minúsculas («Número:») frente al valor en mayúsculas («RAMON CAMPANA»).
        rf"(?i:{etiqueta})[ 	]*:[ 	]*(.*?)(?={hasta})",
        texto,
        re.MULTILINE,
    )
    return hallado.group(1).strip(" ,.;") if hallado else ""


def _bloque(lineas: list[str], inicio: re.Pattern[str], fin: re.Pattern[str]) -> list[str]:
    """Las líneas entre el primer encabezado `inicio` y la primera línea que casa con `fin`."""
    dentro = False
    salida: list[str] = []
    for linea in lineas:
        if not dentro:
            if inicio.search(linea):
                dentro = True
            continue
        if fin.search(linea):
            break
        salida.append(linea)
    return salida


def _filas_con_continuacion(
    lineas: list[str], patron: re.Pattern[str], ignorar: re.Pattern[str] | None = None
) -> list[tuple[str, str]]:
    """Filas «código descripción» donde la descripción puede seguir en las líneas de abajo."""
    filas: list[tuple[str, str]] = []
    for linea in lineas:
        if ignorar is not None and ignorar.search(linea):
            continue
        hallada = patron.match(linea)
        if hallada:
            filas.append((hallada.group(1), hallada.group(2).strip()))
        elif filas and re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{3,}", linea):
            codigo, descripcion = filas[-1]
            filas[-1] = (codigo, f"{descripcion} {linea.strip()}")
    return filas


# ------------------------------------------------------------------------------------- CPC


def _cpc(lineas: list[str]) -> list[dict[str, str]]:
    bloque = _bloque(lineas, _INICIO_CPC, _FIN_CPC)
    # Si el encabezado de la tabla fue la línea de «Código Producto», no se repite como fila.
    filas = _filas_con_continuacion(
        bloque, _FILA_CPC, ignorar=re.compile(r"^\s*c[oó]digo\s+producto", re.IGNORECASE)
    )
    vistos: dict[str, str] = {}
    for crudo, descripcion in filas:
        codigo = crudo.replace(".", "")
        if codigo in vistos or not re.search(r"[A-Za-zÁÉÍÓÚÑ]{3,}", descripcion):
            continue
        vistos[codigo] = descripcion[:300]
        if len(vistos) >= _TOPE_CPC:
            break
    return [{"codigo": codigo, "descripcion": texto} for codigo, texto in vistos.items()]


# ------------------------------------------------------------------------------------- CIIU


def _actividades(lineas: list[str]) -> list[dict[str, Any]]:
    """Actividades económicas del SRI, de todas las páginas (el bloque se parte entre páginas)."""
    salida: list[dict[str, Any]] = []
    dentro = False
    actuales: list[str] = []
    for linea in lineas:
        if re.match(r"^\s*actividades econ[oó]micas\s*$", linea, re.IGNORECASE):
            dentro = True
            continue
        if not dentro:
            continue
        if _FIN_CIIU.search(linea):
            dentro = False
            continue
        # El bloque sigue en la página siguiente, detrás de la cabecera que se repite.
        if _RUIDO_PAGINA.search(linea):
            continue
        actuales.append(linea)
    vistos: set[str] = set()
    for codigo, descripcion in _filas_con_continuacion(actuales, _FILA_CIIU):
        if codigo in vistos:
            continue
        vistos.add(codigo)
        salida.append({"ciiu": codigo, "descripcion": descripcion[:400], "principal": not salida})
        if len(salida) >= _TOPE_CIIU:
            break
    return salida


# ------------------------------------------------------------------------------------- datos


def _razon_social(texto: str, lineas: list[str]) -> str:
    # RUP: «certifico, que Ulloa Sandoval Hector Paúl con RUC número …»
    hallada = re.search(r"certifico,?\s+que\s+(.+?)\s+con\s+ruc", texto, re.IGNORECASE)
    if hallada:
        return " ".join(hallada.group(1).split())
    explicita = _tras(texto, r"raz[oó]n social")
    if explicita:
        return explicita
    # SRI: el valor sale en la línea **anterior** a «Apellidos y nombres» o «Razón social».
    for n, linea in enumerate(lineas):
        if re.match(r"^(apellidos y nombres|raz[oó]n social)\b", _plano(linea)) and n:
            candidata = re.sub(r"\d{13}", "", lineas[n - 1]).strip()
            if len(candidata) >= 3 and not re.search(r"certificado|registro", _plano(candidata)):
                return candidata
    return ""


def _valor_debajo(lineas: list[str], etiqueta: str) -> str:
    """En el certificado del SRI el valor sale en la línea siguiente a su etiqueta."""
    for n, linea in enumerate(lineas[:-1]):
        if _plano(linea).strip() == etiqueta:
            return lineas[n + 1].strip()
    return ""


def _direccion(texto: str) -> str:
    calle = _tras(texto, "calle")
    numero = _tras(texto, r"n[uú]mero")
    interseccion = _tras(texto, r"intersecci[oó]n") or _tras(texto, "transversal")
    partes = [calle, numero]
    direccion = " ".join(p for p in partes if p)
    if interseccion:
        direccion = f"{direccion} y {interseccion}" if direccion else interseccion
    if not direccion:
        return ""
    direccion = _titulo(direccion)
    referencia = _tras(texto, "referencia")
    if referencia:
        direccion = f"{direccion} ({referencia.lower()})"
    return direccion[:300]


def _telefono(texto: str) -> str:
    for etiqueta in (r"celular", r"tel[eé]fono domicilio", r"tel[eé]fono\(s\)", r"tel[eé]fono"):
        valor = _tras(texto, etiqueta)
        hallado = _TELEFONO.search(valor)
        if hallado:
            return hallado.group(0)
    return ""


def leer_rup(texto: str) -> dict[str, Any]:
    """Propuesta de perfil con todo lo que traen los certificados del RUP y del RUC."""
    lineas = _lineas(texto)
    plano = _plano(texto)
    es_rup = "registro unico de proveedores" in plano
    es_sri = "registro unico de contribuyentes" in plano

    ruc = next((r for r in _RUC.findall(texto) if ruc_valido(r)), "")

    estado = ""
    hallado_estado = re.search(r"queda\s+(\w+)\s+en el registro", plano) or re.search(
        r"\b(habilitado|inhabilitado|suspendido|pasivo)\b", plano
    )
    if hallado_estado:
        estado = ESTADOS_RUP.get(hallado_estado.group(1), "")

    correo_hallado = _CORREO.search(texto)
    provincia = _tras(texto, "provincias?")
    canton = _tras(texto, r"cant[oó]n")
    canton = re.sub(r"^distrito metropolitano de\s+", "", canton, flags=re.IGNORECASE)

    tipo_texto = _plano(_valor_debajo(lineas, "tipo agente de retencion contribuyente especial"))
    tipo_persona = (
        "natural" if "natural" in tipo_texto else "juridica" if "sociedad" in tipo_texto else ""
    )
    if not tipo_persona and ruc:
        tipo_persona = "natural" if ruc[2] in "012345" else "juridica"

    contabilidad = _valor_debajo(lineas, "jurisdiccion obligado a llevar contabilidad")
    regimen = _valor_debajo(lineas, "regimen")
    categoria = _tras(texto, "categoria")

    identidad: dict[str, Any] = {
        "razon_social": _razon_social(texto, lineas),
        "nombre_comercial": _tras(texto, "nombre comercial"),
        "tipo_persona": tipo_persona,
        "regimen_tributario": _titulo(regimen) if regimen and len(regimen) < 60 else "",
        "estado_rup": estado,
        "email_contacto": correo_hallado.group(0) if correo_hallado else "",
        "telefono": _telefono(texto),
        "direccion": _direccion(texto),
        "ciudad": _titulo(canton),
        "capacidad_ejecucion": f"Categoría RUP: {categoria}" if categoria else "",
    }
    if contabilidad.upper().endswith((" SI", " NO")):
        identidad["obligado_contabilidad"] = contabilidad.upper().endswith(" SI")
    identidad = {clave: valor for clave, valor in identidad.items() if valor not in ("", None)}

    # Representante: el de la sociedad si el certificado lo trae; si es persona natural, ella misma.
    representante: dict[str, Any] | None = None
    nombre_rep = _tras(texto, "representante legal")
    if not nombre_rep and tipo_persona == "natural":
        nombre_rep = _tras(texto, "nombre completo", hasta=r"$") or identidad.get(
            "razon_social", ""
        )
    if len(nombre_rep) >= 5:
        cedula = ""
        for n, linea in enumerate(lineas):
            if "representante" in _plano(linea):
                hallada = _CEDULA.search(" ".join(lineas[n : n + 3]))
                cedula = hallada.group(1) if hallada else ""
                break
        if not cedula and tipo_persona == "natural" and ruc:
            cedula = ruc[:10]
        representante = {
            "tipo": "representante_legal",
            "nombre": _titulo(re.sub(r"\d{10,13}", "", nombre_rep)).strip(" :-,"),
            "cedula": cedula,
            "cargo": "Representante legal" if tipo_persona != "natural" else "Titular",
            "principal": True,
        }

    cobertura = [{"provincia": _titulo(provincia), "canton": _titulo(canton)}] if provincia else []
    cpc = _cpc(lineas)
    actividades = _actividades(lineas)

    avisos: list[str] = []
    if not texto.strip():
        avisos.append(
            "El PDF no trae texto (parece escaneado). Imprime el RUP desde el SOCE como PDF, "
            "no como foto."
        )
    elif not es_rup and not es_sri:
        avisos.append(
            "El documento no parece un certificado del RUP ni del RUC. Revisa lo encontrado."
        )
    if texto.strip() and not cpc:
        avisos.append(
            "No encontré la tabla de CPC del RUP. Si solo subiste el RUC del SRI, sube también "
            "el RUP impreso desde el SOCE."
        )
    if estado and estado != "habilitado":
        avisos.append(f"El RUP figura como {estado}: no podrás ofertar hasta habilitarlo.")

    return {
        "ruc": ruc,
        "documentos": [n for n, ok in (("RUP", es_rup), ("RUC del SRI", es_sri)) if ok],
        "identidad": identidad,
        "representante": representante,
        "cobertura": cobertura,
        "actividades": actividades,
        "cpc": cpc,
        "avisos": avisos,
    }
