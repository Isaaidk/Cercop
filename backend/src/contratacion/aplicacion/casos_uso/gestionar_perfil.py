"""Leer y editar el perfil con el que se rellena un TDR.

Leer lo puede hacer cualquiera de la empresa: el borrador de oferta se arma con esos datos. Editar
exige `empresa.editar_perfil`, que tienen el dueño y el superadministrador.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Any
from uuid import UUID

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.casos_uso.gestionar_cpc import sembrar_cpc
from contratacion.aplicacion.hilos import en_hilo
from contratacion.aplicacion.puertos.cpc import RepositorioCpc
from contratacion.aplicacion.puertos.perfil import (
    ConsultaRuc,
    ExtractorTextoPdf,
    HistorialContratos,
    RepositorioPerfil,
)
from contratacion.dominio.consulta_ruc import propuesta_desde_sri
from contratacion.dominio.errores import DatoInvalido, NoEncontrado
from contratacion.dominio.perfil import (
    TIPOS_CONTACTO,
    TIPOS_CONTRATACION,
    TIPOS_OFERTA,
    TIPOS_PERSONA,
    TIPOS_PROCEDIMIENTO,
    exigir_opcion,
    exigir_ruc,
)
from contratacion.dominio.rup import ESTADOS_RUP, leer_rup
from contratacion.dominio.verificacion import ruc_valido


async def ver_perfil(actor: Actor, *, repositorio: RepositorioPerfil) -> dict[str, Any]:
    return await repositorio.leer(actor.negocio_id)


async def guardar_identidad(
    actor: Actor, *, repositorio: RepositorioPerfil, campos: dict[str, Any]
) -> dict[str, Any]:
    actor.exigir_permiso("empresa.editar_perfil")
    persona = campos.get("tipo_persona")
    if persona is not None:
        if not str(persona).strip():
            campos["tipo_persona"] = None
        else:
            campos["tipo_persona"] = exigir_opcion(persona, TIPOS_PERSONA, "Tipo de persona")
    if "ruc" in campos:
        campos["ruc"] = exigir_ruc(campos["ruc"])
    if "fecha_inicio_actividades" in campos:
        campos["fecha_inicio_actividades"] = _fecha(campos["fecha_inicio_actividades"])
    minimo = campos.get("presupuesto_min")
    maximo = campos.get("presupuesto_max")
    if minimo is not None and maximo is not None and float(minimo) > float(maximo):
        raise DatoInvalido("El presupuesto mínimo no puede ser mayor que el máximo.")
    if "capacidad_ejecucion" in campos and campos["capacidad_ejecucion"] is not None:
        campos["capacidad_ejecucion"] = str(campos["capacidad_ejecucion"]).strip()
    await repositorio.guardar_identidad(actor.negocio_id, campos)
    return await repositorio.leer(actor.negocio_id)


def _fecha(valor: Any) -> date | None:
    """La base guarda una fecha; el navegador manda texto `AAAA-MM-DD`. Vacío es «sin fecha»."""
    if valor in (None, ""):
        return None
    if isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(str(valor)[:10])
    except ValueError as error:
        raise DatoInvalido("La fecha de inicio de actividades debe ser AAAA-MM-DD.") from error


async def consultar_ruc(actor: Actor, *, ruc: str, sri: ConsultaRuc) -> dict[str, Any]:
    """Lo que el SRI publica de un RUC, como propuesta para el perfil. No guarda nada."""
    actor.exigir_permiso("empresa.editar_perfil")
    limpio = str(ruc or "").strip()
    if not ruc_valido(limpio):
        raise DatoInvalido(
            "El RUC debe tener 13 dígitos, con provincia válida y establecimiento distinto de 000."
        )
    contribuyente, establecimientos = await sri.consultar(limpio)
    return propuesta_desde_sri(contribuyente, establecimientos)


async def consultar_ruc_publico(ruc: str, *, sri: ConsultaRuc) -> dict[str, Any]:
    """La misma propuesta que `consultar_ruc`, para el formulario de registro, sin sesión.

    Es el respaldo de la consulta que el navegador hace al SRI directamente. Lo que devuelve es lo
    que el SRI ya publica para cualquiera que escriba el RUC en su página, así que no expone nada
    nuevo; el freno por IP de `proteccion.py` evita que se use como pasarela gratuita al SRI.
    """
    limpio = str(ruc or "").strip()
    if not ruc_valido(limpio):
        raise DatoInvalido(
            "El RUC debe tener 13 dígitos, con provincia válida y establecimiento distinto de 000."
        )
    contribuyente, establecimientos = await sri.consultar(limpio)
    return propuesta_desde_sri(contribuyente, establecimientos)


# Lo único que el registro puede sembrar en el perfil: lo que el SRI publica. Correo, teléfono y
# RUC van por los datos de la empresa del propio registro, que ya los valida.
_IDENTIDAD_SEMBRABLE = (
    "razon_social",
    "nombre_comercial",
    "tipo_persona",
    "regimen_tributario",
    "obligado_contabilidad",
    "fecha_inicio_actividades",
    "direccion",
    "ciudad",
)
_LARGO_MAXIMO = 300
_COBERTURAS_MAXIMAS = 24
_EXPERIENCIAS_MAXIMAS = 12


def _texto(valor: Any, largo: int = _LARGO_MAXIMO) -> str:
    return str(valor or "").strip()[:largo]


def _identidad_sembrable(identidad: dict[str, Any]) -> dict[str, Any]:
    campos: dict[str, Any] = {}
    for clave in _IDENTIDAD_SEMBRABLE:
        valor = identidad.get(clave)
        if valor in (None, ""):
            continue
        try:
            if clave == "obligado_contabilidad":
                campos[clave] = bool(valor)
            elif clave == "tipo_persona":
                campos[clave] = exigir_opcion(valor, TIPOS_PERSONA, "Tipo de persona")
            elif clave == "fecha_inicio_actividades":
                campos[clave] = _fecha(valor)
            else:
                campos[clave] = _texto(valor)
        except DatoInvalido:
            continue
    return campos


async def sembrar_perfil(
    negocio_id: UUID, *, repositorio: RepositorioPerfil, propuesta: dict[str, Any]
) -> None:
    """Deja el perfil de una empresa recién registrada con lo que el SRI publica de su RUC.

    No hay actor: la empresa se acaba de crear en esta misma petición y nadie más puede escribir
    en ella todavía. Todo se filtra por lista blanca y se recorta, porque llega de un formulario
    abierto; lo que no encaje se descarta en silencio en lugar de tumbar un registro ya hecho.
    """
    identidad = _identidad_sembrable(propuesta.get("identidad") or {})
    if identidad:
        await repositorio.guardar_identidad(negocio_id, identidad)

    representante = propuesta.get("representante") or {}
    nombre = _texto(representante.get("nombre"), 160)
    if nombre:
        await repositorio.agregar(
            negocio_id,
            "contactos",
            {
                "tipo": "representante_legal",
                "nombre": nombre,
                "cedula": _texto(representante.get("cedula"), 20) or None,
                "cargo": _texto(representante.get("cargo"), 120) or "Representante legal",
                "principal": True,
            },
        )

    vistas: set[tuple[str, str]] = set()
    for fila in (propuesta.get("cobertura") or [])[:_COBERTURAS_MAXIMAS]:
        if not isinstance(fila, dict):
            continue
        clave = (_texto(fila.get("provincia"), 80), _texto(fila.get("canton"), 80))
        if not clave[0] or clave in vistas:
            continue
        vistas.add(clave)
        await repositorio.agregar(
            negocio_id, "cobertura", {"provincia": clave[0], "canton": clave[1]}
        )

    actividad = _texto(propuesta.get("actividad"), 200)
    if actividad:
        await repositorio.agregar(negocio_id, "actividades", {"ciiu": actividad, "principal": True})

    # Contratos que los datos abiertos atribuyen al RUC: experiencia que la empresa puede declarar.
    for fila in (propuesta.get("experiencia") or [])[:_EXPERIENCIAS_MAXIMAS]:
        if not isinstance(fila, dict) or not _texto(fila.get("entidad")):
            continue
        campos: dict[str, Any] = {
            "entidad": _texto(fila.get("entidad"), 300),
            "objeto": _texto(fila.get("objeto"), 300) or None,
            "cpc": _texto(fila.get("cpc"), 20) or None,
        }
        monto = fila.get("monto")
        if isinstance(monto, int | float) and monto >= 0:
            campos["monto"] = float(monto)
        anio = fila.get("anio")
        if isinstance(anio, int) and 1990 <= anio <= 2100:
            campos["anio"] = anio
        tipo = fila.get("tipo_contratacion")
        if tipo in TIPOS_CONTRATACION:
            campos["tipo_contratacion"] = tipo
        await repositorio.agregar(
            negocio_id,
            "experiencia",
            {clave: valor for clave, valor in campos.items() if valor is not None},
        )


async def leer_rup_pdf(
    actor: Actor, *, contenido: bytes, extraer_texto: ExtractorTextoPdf
) -> dict[str, Any]:
    """Lo que trae el certificado del RUP en PDF, como propuesta. No guarda nada.

    El RUP no tiene consulta pública; la empresa lo imprime desde el SOCE y lo sube. Leer un PDF es
    trabajo de CPU, así que va a un hilo para no frenar al resto de peticiones.
    """
    actor.exigir_permiso("empresa.editar_perfil")
    if not contenido.startswith(b"%PDF"):
        raise DatoInvalido("Sube el RUP en PDF (el que se imprime desde el SOCE).")
    texto = await en_hilo(extraer_texto, contenido)
    return leer_rup(texto)


# Texto que llega del OCR del navegador (`frontend/src/utils/ocr.js`): un RUP escaneado o una foto.
TEXTO_OCR_MINIMO = 20
TEXTO_OCR_MAXIMO = 200_000
AVISO_OCR = (
    "Leído de una imagen (OCR): revisa los códigos CPC, el RUC y el correo antes de cargarlos; "
    "el reconocimiento puede confundir letras y números (O y 0, I y 1)."
)

# Espacios que no son el espacio normal: NBSP, finos, ideográfico y los de ancho cero.
_ESPACIOS_RAROS = re.compile(r"[\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000\t\f\v]")
_ANCHO_CERO = re.compile(r"[\u200b-\u200d\u2060\ufeff]")
_COMILLAS = str.maketrans(
    {
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u201f": '"',
        "\u2033": '"',
        "\u2018": "'",
        "\u2019": "'",
    }
)
_GUIONES = re.compile(r"[\u2010-\u2015\u2212]")
# «|» pegado a una letra es una I mal leída («|NSTRUMENTOS», «MUS|CALES»); suelto es el borde de
# una tabla y sobra.
_BARRA_EN_PALABRA = re.compile(r"(?<=[A-Za-zÁÉÍÓÚÑáéíóúñ])\||\|(?=[A-Za-zÁÉÍÓÚÑáéíóúñ])")
# Actividad del SRI con viñeta cuya letra de sección salió como cifra: «• 646491102 - VENTA…».
# Solo con viñeta y guion, que es la forma de la lista del SRI: la tabla de CPC del RUP no los
# lleva, así que un CPC que empiece por 6, 8, 0 o 5 no se toca.
_CIIU_CON_CIFRA = re.compile(r"^[•·*«»°©®]\s*([0568])(\d{5,8}\s*-\s)", re.MULTILINE)
_LETRA_DE_CIFRA = {"6": "G", "8": "B", "0": "O", "5": "S"}
# «@» que el OCR leyó como «Q», «QM», «©» o «®», a veces con espacios alrededor.
_ARROBA_MAL_LEIDA = re.compile(
    r"(?<![\w.@])([a-z0-9][a-z0-9._+-]*) ?(?:QM?|©|®|\(a\)) ?"
    r"([a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*\.(?:ec|com|net|org|edu|gob|info|biz))\b"
)


def normalizar_texto_ocr(texto: str) -> str:
    """Quita el ruido típico del OCR sin cambiar la forma del texto: un renglón sigue siendo uno.

    Es deliberadamente ligera: corrige lo que no puede ser otra cosa (espacios raros, comillas
    tipográficas, guiones largos, «|» por «I», la letra de sección de una actividad CIIU leída como
    cifra, la arroba mal leída de un correo). **No** corrige cifras dentro de un código: un CPC
    «7321O» (O por 0) no se adivina, porque cambiar letras por números a ciegas inventaría códigos;
    esa fila se pierde y por eso la respuesta lleva `AVISO_OCR` para que la persona revise.
    """
    limpio = unicodedata.normalize("NFC", texto.replace("\r\n", "\n").replace("\r", "\n"))
    limpio = _ANCHO_CERO.sub("", limpio)
    limpio = _ESPACIOS_RAROS.sub(" ", limpio).translate(_COMILLAS)
    limpio = _GUIONES.sub("-", limpio)
    limpio = _BARRA_EN_PALABRA.sub("I", limpio).replace("|", " ")
    lineas = [" ".join(linea.split()) for linea in limpio.split("\n")]
    limpio = "\n".join(linea for linea in lineas if linea)
    limpio = _CIIU_CON_CIFRA.sub(lambda m: f"• {_LETRA_DE_CIFRA[m.group(1)]}{m.group(2)}", limpio)
    if "@" not in limpio:
        limpio = _ARROBA_MAL_LEIDA.sub(r"\1@\2", limpio)
    return limpio


def _leer_rup_ocr(texto: str) -> dict[str, Any]:
    resultado = leer_rup(normalizar_texto_ocr(texto))
    resultado["avisos"] = [*resultado["avisos"], AVISO_OCR]
    return resultado


async def leer_rup_texto(actor: Actor, *, texto: str) -> dict[str, Any]:
    """Lo mismo que `leer_rup_pdf`, con el texto que el navegador ya sacó por OCR. No guarda nada.

    El OCR corre en el navegador (pesa demasiado para hacerlo aquí con cientos de usuarios); al
    servidor solo llega el texto, así que no pasa por `pypdf`. Las expresiones regulares sobre
    hasta 200.000 caracteres también son CPU, y van a un hilo como la lectura del PDF.
    """
    actor.exigir_permiso("empresa.editar_perfil")
    limpio = str(texto or "").strip()
    if len(limpio) < TEXTO_OCR_MINIMO:
        raise DatoInvalido(
            "No llegó texto suficiente del documento. Prueba con una foto más nítida y de frente."
        )
    if len(limpio) > TEXTO_OCR_MAXIMO:
        raise DatoInvalido("El texto es demasiado largo para un certificado del RUP.")
    return await en_hilo(_leer_rup_ocr, limpio)


# Lo que se puede cargar en la identidad desde los certificados del RUP y del RUC.
_IDENTIDAD_DEL_RUP = frozenset(
    {
        "razon_social",
        "nombre_comercial",
        "tipo_persona",
        "regimen_tributario",
        "obligado_contabilidad",
        "estado_rup",
        "email_contacto",
        "telefono",
        "direccion",
        "ciudad",
        "capacidad_ejecucion",
    }
)


def _tipo_por_cpc(codigo: str) -> str:
    """Secciones 0-4 del CPC son bienes; 5-9, servicios (la construcción es la 5)."""
    return "producto" if codigo[:1] in "01234" else "servicio"


async def aplicar_rup(
    actor: Actor,
    *,
    repositorio: RepositorioPerfil,
    cpc: RepositorioCpc,
    propuesta: dict[str, Any],
) -> dict[str, int]:
    """Carga en el perfil lo elegido del RUP: datos, representante y cada CPC con su descripción.

    Cada CPC entra en dos sitios: en la lista de CPC vigilados (radar, alertas y búsqueda de
    ínfimas) y en «Qué ofreces», con su descripción, que es lo que se usa al llenar un TDR. Lo que
    ya estaba no se duplica.
    """
    actor.exigir_permiso("empresa.editar_perfil")
    actual = await repositorio.leer(actor.negocio_id)

    identidad: dict[str, Any] = {}
    for clave, valor in (propuesta.get("identidad") or {}).items():
        if clave not in _IDENTIDAD_DEL_RUP:
            continue
        if clave == "obligado_contabilidad":
            if isinstance(valor, bool):
                identidad[clave] = valor
            continue
        if not str(valor or "").strip():
            continue
        if clave == "estado_rup" and valor not in set(ESTADOS_RUP.values()):
            continue
        if clave == "tipo_persona" and valor not in TIPOS_PERSONA:
            continue
        identidad[clave] = _texto(valor)
    if identidad:
        await repositorio.guardar_identidad(actor.negocio_id, identidad)

    contactos = 0
    representante = propuesta.get("representante") or {}
    nombre = _texto(representante.get("nombre"), 160)
    ya = {str(c.get("nombre") or "").strip().lower() for c in actual.get("contactos") or []}
    if nombre and nombre.lower() not in ya:
        await repositorio.agregar(
            actor.negocio_id,
            "contactos",
            {
                "tipo": "representante_legal",
                "nombre": nombre,
                "cedula": _texto(representante.get("cedula"), 20) or None,
                "cargo": "Representante legal",
                "principal": True,
            },
        )
        contactos = 1

    filas = [
        (str(fila.get("codigo") or "").strip(), _texto(fila.get("descripcion"), 300))
        for fila in (propuesta.get("cpc") or [])[:150]
        if isinstance(fila, dict)
    ]
    filas = [(codigo, descripcion) for codigo, descripcion in filas if codigo.isdigit()]
    vigilados = await sembrar_cpc(
        negocio_id=actor.negocio_id,
        usuario_id=actor.usuario_id,
        textos=[codigo for codigo, _ in filas],
        repositorio=cpc,
    )

    existentes = {str(o.get("descripcion") or "").strip() for o in actual.get("ofertas") or []} | {
        str(o.get("nombre") or "").strip().lower() for o in actual.get("ofertas") or []
    }
    ofertas = 0
    for codigo, descripcion in filas:
        if not descripcion or f"CPC {codigo}" in existentes or descripcion.lower() in existentes:
            continue
        await repositorio.agregar(
            actor.negocio_id,
            "ofertas",
            {"tipo": _tipo_por_cpc(codigo), "nombre": descripcion, "descripcion": f"CPC {codigo}"},
        )
        ofertas += 1

    # Actividades económicas del SRI, con su código CIIU.
    ciiu_ya = {str(a.get("ciiu") or "").strip().upper() for a in actual.get("actividades") or []}
    actividades = 0
    for fila in (propuesta.get("actividades") or [])[:40]:
        codigo = _texto(fila.get("ciiu"), 20).upper() if isinstance(fila, dict) else ""
        if not codigo or codigo in ciiu_ya:
            continue
        ciiu_ya.add(codigo)
        await repositorio.agregar(
            actor.negocio_id,
            "actividades",
            {
                "ciiu": codigo,
                "descripcion": _texto(fila.get("descripcion"), 400),
                "principal": bool(fila.get("principal")) and not actual.get("actividades"),
            },
        )
        actividades += 1

    # Dónde entrega: la provincia y el cantón del domicilio.
    lugares_ya = {
        (str(c.get("provincia") or "").lower(), str(c.get("canton") or "").lower())
        for c in actual.get("cobertura") or []
    }
    coberturas = 0
    for fila in (propuesta.get("cobertura") or [])[:24]:
        if not isinstance(fila, dict):
            continue
        lugar = (_texto(fila.get("provincia"), 80), _texto(fila.get("canton"), 80))
        if not lugar[0] or (lugar[0].lower(), lugar[1].lower()) in lugares_ya:
            continue
        lugares_ya.add((lugar[0].lower(), lugar[1].lower()))
        await repositorio.agregar(
            actor.negocio_id, "cobertura", {"provincia": lugar[0], "canton": lugar[1]}
        )
        coberturas += 1

    return {
        "datos": len(identidad),
        "contactos": contactos,
        "cpc_vigilados": vigilados,
        "ofertas": ofertas,
        "actividades": actividades,
        "cobertura": coberturas,
    }


async def consultar_historial(
    actor: Actor, *, ruc: str, razon_social: str, historial: HistorialContratos
) -> dict[str, Any]:
    """CPC y contratos que los datos abiertos atribuyen a ese RUC, como propuesta para el perfil.

    No guarda nada. Aproxima el RUP, que no tiene consulta pública: ver `dominio.historial`.
    """
    actor.exigir_permiso("empresa.editar_perfil")
    limpio = str(ruc or "").strip()
    if not ruc_valido(limpio):
        raise DatoInvalido(
            "El RUC debe tener 13 dígitos, con provincia válida y establecimiento distinto de 000."
        )
    if len(str(razon_social or "").strip()) < 3:
        raise DatoInvalido("Falta la razón social para buscar tus contratos.")
    return await historial.consultar(limpio, str(razon_social).strip())


async def agregar_fila(
    actor: Actor,
    *,
    repositorio: RepositorioPerfil,
    coleccion: str,
    campos: dict[str, Any],
) -> dict[str, Any]:
    actor.exigir_permiso("empresa.editar_perfil")
    _validar_fila(coleccion, campos)
    return await repositorio.agregar(actor.negocio_id, coleccion, campos)


async def quitar_fila(
    actor: Actor,
    *,
    repositorio: RepositorioPerfil,
    coleccion: str,
    fila_id: UUID,
) -> None:
    actor.exigir_permiso("empresa.editar_perfil")
    if not await repositorio.quitar(actor.negocio_id, coleccion, fila_id):
        raise NoEncontrado("No está en el perfil de esta empresa.")


def _validar_fila(coleccion: str, campos: dict[str, Any]) -> None:
    if coleccion == "dedicaciones":
        campos["tipo_contratacion"] = exigir_opcion(
            campos.get("tipo_contratacion", ""), TIPOS_CONTRATACION, "Tipo de contratación"
        )
        campos["tipo_procedimiento"] = exigir_opcion(
            campos.get("tipo_procedimiento", ""), TIPOS_PROCEDIMIENTO, "Tipo de procedimiento"
        )
    elif coleccion == "contactos":
        campos["tipo"] = exigir_opcion(campos.get("tipo", ""), TIPOS_CONTACTO, "Tipo de contacto")
    elif coleccion == "ofertas":
        campos["tipo"] = exigir_opcion(campos.get("tipo", ""), TIPOS_OFERTA, "Tipo de oferta")
        if not str(campos.get("nombre") or "").strip():
            raise DatoInvalido("El producto o servicio necesita un nombre.")
    elif coleccion == "palabras":
        texto = str(campos.get("texto") or "").strip()
        if len(texto) < 3:
            raise DatoInvalido("La palabra clave comercial necesita al menos 3 caracteres.")
        campos["texto"] = texto
    elif coleccion == "actividades" and not str(campos.get("ciiu") or "").strip():
        raise DatoInvalido("La actividad económica necesita un código o un nombre.")
    elif coleccion == "cobertura" and not str(campos.get("provincia") or "").strip():
        raise DatoInvalido("La cobertura necesita una provincia.")
    elif coleccion == "experiencia" and campos.get("tipo_contratacion"):
        campos["tipo_contratacion"] = exigir_opcion(
            campos["tipo_contratacion"], TIPOS_CONTRATACION, "Tipo de contratación"
        )
