"""Subir un TDR, resumirlo, armar la proforma y contestar con datos guardados."""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.casos_uso.atender_tdr import archivo_local
from contratacion.aplicacion.casos_uso.ver_mercado import ver_entidades, ver_proveedores
from contratacion.aplicacion.casos_uso.ver_radar import ver_radar
from contratacion.aplicacion.creditos_actor import creditos_de
from contratacion.aplicacion.hilos import CacheLru, en_hilo
from contratacion.aplicacion.puertos.cpc import RepositorioCpc
from contratacion.dominio.acceso import Vista, fuentes_para_vistas
from contratacion.dominio.anexos import (
    ACTA,
    CONTEXTO,
    OTRO,
    PRIORIDAD,
    combinar_secciones,
    contexto_de_anexos,
    elegir_anexos,
    recorte_de_contexto,
)
from contratacion.dominio.creditos import COSTO_PREGUNTA
from contratacion.dominio.documentos import (
    AVISO_PRECIOS,
    calcular_proforma,
    checklist,
    contrastar,
    datos_entidad,
    es_descarga,
    exigir_estado,
    extraer_secciones,
    parece_enlace,
    puntaje_secciones,
    resumir_ficha,
    resumir_secciones,
)
from contratacion.dominio.entidad import completar_entidad, datos_entidad_de_texto
from contratacion.dominio.errores import (
    DatoInvalido,
    EstadoInvalido,
    NoEncontrado,
    SinCreditos,
    SinPermiso,
)
from contratacion.dominio.oferta import datos_empresa
from contratacion.dominio.palabras import normalizar
from contratacion.dominio.presupuesto import (
    ETIQUETAS_FUENTE,
    dinero,
    elegir_presupuesto,
    exigir_dentro_del_presupuesto,
    extraer_presupuesto,
    normalizar_presupuesto,
    presupuesto_de_ficha,
)
from contratacion.dominio.titulos import titulo_libre, titulo_repetido
from contratacion.infraestructura.adaptadores.salida.bd.creditos import RepositorioCreditos
from contratacion.infraestructura.adaptadores.salida.bd.documentos import RepositorioDocumentos
from contratacion.infraestructura.adaptadores.salida.bd.mercado import RepositorioMercado
from contratacion.infraestructura.adaptadores.salida.bd.perfil import RepositorioPerfil
from contratacion.infraestructura.adaptadores.salida.bd.radar import RepositorioRadar
from contratacion.infraestructura.adaptadores.salida.bd.tdr import RepositorioTdr
from contratacion.infraestructura.adaptadores.salida.ia import ModeloIa
from contratacion.infraestructura.adaptadores.salida.texto_anexos import (
    FormatoNoLegible,
    texto_de_archivo,
)

_TOPE_BYTES = 8 * 1024 * 1024
_HORA_EC = timezone(timedelta(hours=-5))
_PARAR = {
    "que",
    "cuales",
    "cual",
    "las",
    "los",
    "me",
    "tengo",
    "han",
    "este",
    "esta",
    "una",
    "uno",
    "de",
    "la",
    "el",
    "en",
    "por",
    "mis",
    "mi",
    "del",
    "al",
    "con",
    "sus",
    "hay",
    "como",
    "para",
    "sobre",
    "solicita",
    "pide",
    "nuevo",
    "nueva",
    "nuevas",
    "nuevos",
}
_INTENTO = {
    "entidades",
    "entidad",
    "compran",
    "compra",
    "proveedores",
    "proveedor",
    "ganado",
    "ganaron",
    "procesos",
    "similares",
    "oportunidades",
    "oportunidad",
    "requisitos",
    "requisito",
    "faltan",
    "falta",
    "documentos",
    "documento",
}


def _fuentes(vistas: frozenset[Vista]) -> tuple[str, ...]:
    fuentes = fuentes_para_vistas(vistas)
    if not fuentes:
        raise SinPermiso("No hay una vista activa para consultar procesos.")
    return fuentes


def texto_subido(nombre: str, contenido: bytes) -> str:
    """El texto de un archivo subido: PDF, Word (.docx), Excel (.xlsx), ZIP con ellos o texto."""
    if len(contenido) > _TOPE_BYTES:
        raise DatoInvalido("El archivo pasa de 8 MB.")
    if not nombre.lower().endswith((".pdf", ".txt", ".docx", ".xlsx", ".zip", ".csv")):
        raise DatoInvalido("Sube un PDF, un Word (.docx), un Excel (.xlsx), un ZIP o un texto.")
    texto = texto_de_archivo(nombre, contenido)
    if not texto.strip():
        raise DatoInvalido(
            "El archivo no trae texto seleccionable. Un escaneo no se puede leer así."
        )
    return texto


def _secciones_de_subida(
    nombre: str, contenido: bytes
) -> tuple[dict[str, str], list[str], dict[str, Any] | None, dict[str, str]]:
    """Apartados, requisitos y presupuesto de un archivo subido. Es CPU pura: va en un hilo.

    El presupuesto se busca en el texto entero, no en los apartados: estos se recortan y la cifra
    suele estar en una tabla o un párrafo sin título. Un `.txt` puede venir del OCR del navegador.
    """
    texto = texto_subido(nombre, contenido)
    secciones = extraer_secciones(texto)
    requisitos = checklist(secciones)
    # El texto entero también queda como contexto: lo que no tiene título igual sirve a la IA.
    contexto = contexto_de_anexos(
        [({"etiqueta_tipo": "Documento subido", "nombre": nombre}, texto)]
    )
    if contexto:
        secciones[CONTEXTO] = contexto
    # RUC, dirección y teléfono de la entidad: sin código del proceso, el TDR es la única fuente.
    return (
        secciones,
        requisitos,
        extraer_presupuesto(texto),
        datos_entidad_de_texto(texto),
    )


def _con_presupuesto(resultado: dict[str, Any], presupuesto: dict[str, Any] | None) -> None:
    """`presupuesto` (o `None`) y `presupuesto_fuente` en la respuesta; el resumen lo enseña."""
    resultado["presupuesto"] = presupuesto
    resultado["presupuesto_fuente"] = presupuesto["etiqueta_fuente"] if presupuesto else ""
    resumen = resultado.get("resumen")
    if presupuesto and isinstance(resumen, dict) and not resumen.get("presupuesto"):
        resumen["presupuesto"] = dinero(float(presupuesto["valor"]))


async def leer_documento(
    actor: Actor,
    *,
    documentos: RepositorioDocumentos,
    nombre: str,
    contenido: bytes,
    registro_id: UUID | None = None,
) -> dict[str, Any]:
    secciones, textos, presupuesto, entidad = await en_hilo(_secciones_de_subida, nombre, contenido)
    resultado = await guardar_lectura_de(
        actor,
        documentos=documentos,
        nombre=nombre,
        secciones=secciones,
        textos=textos,
        registro_id=registro_id,
    )
    _con_presupuesto(resultado, presupuesto)
    resultado["entidad_datos"] = entidad
    return resultado


_SIN_APARTADOS = (
    "No reconocí apartados titulados (objeto, alcance, entregables, plazos, requisitos). "
    "El archivo se leyó, pero no trae esos títulos."
)


async def guardar_lectura_de(
    actor: Actor,
    *,
    documentos: RepositorioDocumentos,
    nombre: str,
    secciones: dict[str, str],
    textos: list[str],
    registro_id: UUID | None = None,
) -> dict[str, Any]:
    """Guarda lo leído para la empresa con su lista de requisitos. No vuelve a leer el PDF."""
    if not secciones:
        raise DatoInvalido(_SIN_APARTADOS)
    lectura = await documentos.guardar_lectura_con_requisitos(
        negocio_id=actor.negocio_id,
        usuario_id=actor.usuario_id,
        nombre=nombre,
        registro_id=registro_id,
        secciones=secciones,
        textos=textos,
    )
    return {
        "lectura_id": lectura["id"],
        "nombre": nombre,
        "secciones": secciones,
        "resumen": resumir_secciones(secciones),
        "requisitos": textos,
    }


# Lo que se lee de un archivo del portal es igual para todas las empresas: el mismo TDR lo piden
# decenas de proveedores. La llave es la huella del archivo, así que se lee una sola vez.
_LEIDOS = CacheLru(256)


# Nombre, apartados, requisitos, presupuesto, datos de la entidad (RUC, dirección, teléfono…) y el
# texto del archivo recortado, que va al contexto de la proforma aunque no traiga apartados.
Leido = tuple[str, dict[str, str], list[str], dict[str, Any] | None, dict[str, str], str]

_EXTENSION_POR_FORMATO = ((b"%PDF", ".pdf"), (b"PK", ".docx"))


def _nombre_de_lectura(nombre: str, contenido: bytes) -> str:
    if nombre.lower().endswith((".pdf", ".docx", ".xlsx", ".zip", ".txt", ".csv")):
        return nombre
    for firma, extension in _EXTENSION_POR_FORMATO:
        if contenido.startswith(firma):
            return f"terminos{extension}"
    return nombre


def _leer_del_disco(ruta: str, nombre: str, huella: str | None) -> Leido | None:
    """Abre el archivo bajado (PDF, Word, Excel, ZIP o texto) y saca apartados, requisitos,
    presupuesto, datos de la entidad y su texto. Va en un hilo: es CPU."""
    contenido = Path(ruta).read_bytes()
    llave = huella or hashlib.sha256(contenido).hexdigest()
    conocido = _LEIDOS.obtener(llave)
    if conocido is not None and len(conocido) > 5:
        return cast(Leido, conocido)
    if len(contenido) > _TOPE_BYTES * 3:
        raise FormatoNoLegible("El anexo pasa de 24 MB y no se lee aquí.")
    nombre_lectura = _nombre_de_lectura(nombre, contenido)
    texto = texto_de_archivo(nombre_lectura, contenido)
    if not texto.strip():
        raise DatoInvalido(
            "El archivo no trae texto seleccionable. Si es un escaneo, súbelo en el recuadro: "
            "el panel lo lee con OCR."
        )
    secciones = extraer_secciones(texto)
    leido = (
        nombre_lectura,
        secciones,
        checklist(secciones),
        extraer_presupuesto(texto),
        datos_entidad_de_texto(texto),
        recorte_de_contexto(texto),
    )
    _LEIDOS.guardar(llave, leido)
    return leido


def _publicados(ficha: dict[str, Any]) -> list[dict[str, Any]]:
    documentos = ficha.get("documentos") or []
    if isinstance(documentos, str):
        documentos = json.loads(documentos)
    return [documento for documento in documentos if isinstance(documento, dict)]


def _error_de_bajada(texto: str) -> str:
    if texto.startswith(("HTTP", "Connect", "Read", "Timeout", "Remote")):
        return "No se pudo bajar el TDR desde el portal. Vuelve a intentarlo."
    return texto or "No se pudo bajar el TDR."


def _nombre_fila(documento: dict[str, Any]) -> str:
    """La cola de TDR va por `(registro_id, nombre)`; sin nombre, el repositorio usa «tdr»."""
    return str(documento.get("nombre") or "tdr")


def _anexos_del_proceso(ficha: dict[str, Any]) -> list[dict[str, Any]]:
    """Los anexos que sirven para la proforma: TDR, pliegos, especificaciones y **solo la última
    acta** (`dominio/anexos.py`). Las actas anteriores no se piden ni se leen: la última ya las
    corrige, y cada archivo de menos es una petición de menos al portal."""
    return elegir_anexos(
        documento
        for documento in _publicados(ficha)
        if es_descarga(str(documento.get("nombre") or ""), str(documento.get("enlace") or ""))
    )


# Cuánto se espera a un anexo con tipo (TDR, pliego, acta…) que sigue en la cola antes de leer sin
# él. Sin tope, un archivo que el portal tarda en soltar dejaría a la persona sin nada que leer.
_ESPERA_ANEXO = timedelta(seconds=90)


def _hay_que_esperar(fila: dict[str, Any], anexo: dict[str, Any] | None) -> bool:
    """El anexo con tipo sigue pendiente y se pidió hace poco: conviene leerlo junto con el resto.

    Los de tipo «otro» no se esperan: en las ínfimas suelen ser archivos sin nombre y, como antes,
    basta con que uno se pueda leer.
    """
    if fila.get("estado") != "pendiente" or anexo is None or anexo.get("tipo") == OTRO:
        return False
    pedido = fila.get("pedido_en")
    if not isinstance(pedido, datetime):
        return True
    if pedido.tzinfo is None:
        pedido = pedido.replace(tzinfo=UTC)
    return datetime.now(UTC) - pedido < _ESPERA_ANEXO


def _con_fuente(presupuesto: dict[str, Any] | None, tipo: str) -> dict[str, Any] | None:
    """La caché guarda el presupuesto por archivo; su fuente depende del anexo que lo trajo."""
    if presupuesto is None:
        return None
    return {**presupuesto, "fuente": tipo, "etiqueta_fuente": ETIQUETAS_FUENTE.get(tipo, tipo)}


def _nombre_visible(anexo: dict[str, Any], posicion: int) -> str:
    nombre = str(anexo.get("nombre") or "").strip()
    return f"Documento {posicion}" if not nombre or parece_enlace(nombre) else nombre


def _anexos_presentables(
    anexos: list[dict[str, Any]],
    filas: dict[str, dict[str, Any]],
    leidos: set[str],
    sin_leer: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """La lista que enseña el panel: nombre legible, tipo, estado y el id para descargarlo.

    `sin_leer` dice, por anexo bajado que no se pudo leer, el porqué (escaneo, .doc antiguo, .rar):
    así la persona sabe qué archivo falta en el contexto y qué hacer con él.
    """
    salida = []
    for posicion, anexo in enumerate(anexos, start=1):
        fila = filas.get(_nombre_fila(anexo)) or {}
        motivo = (sin_leer or {}).get(_nombre_fila(anexo), "")
        salida.append(
            {
                "nombre": _nombre_visible(anexo, posicion),
                "tipo": anexo["tipo"],
                "etiqueta_tipo": anexo["etiqueta_tipo"],
                "fecha": str(anexo.get("fecha") or "")[:10],
                "estado": "sin_texto" if motivo else str(fila.get("estado") or "sin_pedir"),
                "motivo": motivo,
                "documento_id": fila.get("id") if fila.get("estado") == "listo" else None,
                "leido": _nombre_fila(anexo) in leidos,
            }
        )
    return salida


async def preparar_desde_codigo(
    actor: Actor,
    vistas: frozenset[Vista],
    *,
    documentos: RepositorioDocumentos,
    tdr: RepositorioTdr,
    codigo: str,
    reintentar: bool = False,
) -> dict[str, Any]:
    """Pide los anexos del código y, si ya están en disco, los lee como si el usuario los subiera.

    Se piden y se leen el TDR, los pliegos, las especificaciones y **solo el acta más reciente**; su
    texto se combina en una sola lectura (lo que el acta corrige manda y se marca «Según acta del
    …»). El presupuesto sale del acta, la ficha o el texto, en ese orden (`dominio/presupuesto`).

    La API no abre el portal: deja el pedido y el worker lo baja. Mientras tanto responde
    `preparando` para que el panel vuelva a preguntar.
    """
    actor.exigir_permiso("tdr.ver")
    ficha = await documentos.ficha_publicada(fuentes=_fuentes(vistas), codigo=codigo)
    if ficha is None:
        raise NoEncontrado("No hay un proceso con ese código en las vistas activas.")
    anexos = _anexos_del_proceso(ficha)
    if not anexos:
        raise DatoInvalido("Esta oportunidad no publica documentos para bajar.")
    por_nombre = {_nombre_fila(anexo): anexo for anexo in anexos}
    registro_id = ficha["id"]
    items_leidos = ficha.get("items_recogidos_en") is not None
    if not items_leidos:
        await documentos.pedir_items(registro_id)
    if reintentar:
        with contextlib.suppress(Exception):
            await tdr.auditar(actor.negocio_id, actor.usuario_id, registro_id)

    async def elegidas() -> list[dict[str, Any]]:
        # Las actas viejas que se pidieron antes de esta regla siguen en la cola: no se leen.
        return [fila for fila in await tdr.listar(registro_id) if str(fila["nombre"]) in por_nombre]

    # Se pide solo lo que no está pedido: la mayoría de las veces el archivo ya existe y la
    # petición no escribe nada.
    filas = await elegidas()
    conocidos = {str(fila["nombre"]) for fila in filas}
    faltan = [anexo for anexo in anexos if _nombre_fila(anexo) not in conocidos]
    for documento in faltan:
        await tdr.pedir(registro_id, documento)
    if faltan:
        filas = await elegidas()
    if reintentar:
        for fila in filas:
            if fila["estado"] == "error":
                await tdr.reabrir(fila["id"])
        filas = await elegidas()

    leidos: list[tuple[dict[str, Any], Leido, int]] = []
    fallo: DatoInvalido | None = None
    sin_leer: dict[str, str] = {}
    reabierto = False
    for fila in filas:
        if fila["estado"] != "listo":
            continue
        ruta = await archivo_local(tdr, fila)
        if ruta is None:
            await tdr.reabrir(fila["id"])
            reabierto = True
            continue
        huella = fila.get("sha256")
        # Con la huella conocida, un archivo ya leído se sirve de la caché sin tocar el disco ni
        # pasar por un hilo: es el caso de casi todas las peticiones.
        leido = _LEIDOS.obtener(huella) if huella else None
        if leido is not None and len(leido) < 6:
            leido = None  # leído antes de guardar el texto del anexo: se vuelve a leer
        try:
            if leido is None:
                leido = await en_hilo(_leer_del_disco, str(ruta), str(fila["nombre"]), huella)
        except DatoInvalido as exc:
            fallo = exc
            sin_leer[str(fila["nombre"])] = str(exc)
            continue
        if leido is None:
            continue
        anexo = por_nombre[str(fila["nombre"])]
        puntos = puntaje_secciones(leido[1])
        # Todos los anexos cuentan: el que no trae apartados titulados (un formulario, una tabla de
        # ítems, un anexo sin títulos) igual aporta su texto, su presupuesto y los datos de la
        # entidad al contexto de la proforma. Solo se descarta lo que no trae nada.
        if not (leido[1] or leido[3] or leido[4] or leido[5]):
            continue
        leidos.append((anexo, cast(Leido, leido), puntos))

    esperando = any(_hay_que_esperar(fila, por_nombre.get(str(fila["nombre"]))) for fila in filas)
    pendientes = reabierto or any(fila["estado"] == "pendiente" for fila in filas)
    # Con un anexo con apartados se arma ya; si ninguno los trae, se espera a que bajen todos y se
    # arma con el texto que haya.
    if leidos and not esperando and (any(p > 0 for _, _, p in leidos) or not pendientes):
        return await _guardar_lo_leido(
            actor,
            documentos=documentos,
            ficha=ficha,
            anexos=anexos,
            filas=filas,
            leidos=leidos,
            items_leidos=items_leidos,
            sin_leer=sin_leer,
        )

    if esperando or reabierto or any(fila["estado"] == "pendiente" for fila in filas):
        return {
            "estado": "preparando",
            "registro_id": registro_id,
            "codigo": ficha["codigo"],
            "items_leidos": items_leidos,
        }
    if fallo is not None:
        raise fallo
    errores = [fila for fila in filas if fila["estado"] == "error"]
    if errores:
        raise DatoInvalido(_error_de_bajada(str(errores[0].get("error") or "")))
    raise DatoInvalido("El proceso no publica un PDF que se pueda leer. Súbelo en el recuadro.")


async def _guardar_lo_leido(
    actor: Actor,
    *,
    documentos: RepositorioDocumentos,
    ficha: dict[str, Any],
    anexos: list[dict[str, Any]],
    filas: list[dict[str, Any]],
    leidos: list[tuple[dict[str, Any], Leido, int]],
    items_leidos: bool,
    sin_leer: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Combina lo leído de cada anexo, lo guarda como una lectura y arma la respuesta del panel.

    Manda el anexo con más apartados útiles (como antes, cuando se leía uno solo); detrás van los
    demás por tipo (TDR, pliego, especificaciones, otros) y al final el acta, que corrige.
    """
    principal = max(
        (par for par in leidos if par[0]["tipo"] != ACTA),
        key=lambda par: (par[2], -PRIORIDAD[par[0]["tipo"]]),
        default=leidos[0],
    )
    resto = sorted(
        (par for par in leidos if par is not principal),
        key=lambda par: PRIORIDAD[par[0]["tipo"]],
    )
    ordenados = [principal, *resto]
    secciones, cambios = combinar_secciones((anexo, leido[1]) for anexo, leido, _ in ordenados)
    # El texto de todos los anexos (no solo sus apartados titulados), para la IA y para consultar.
    posiciones = {_nombre_fila(anexo): n for n, anexo in enumerate(anexos, start=1)}
    contexto = contexto_de_anexos(
        (
            {
                **anexo,
                "nombre_visible": _nombre_visible(anexo, posiciones.get(_nombre_fila(anexo), 0)),
            },
            leido[5] if len(leido) > 5 else "",
        )
        for anexo, leido, _ in ordenados
    )
    if contexto:
        secciones[CONTEXTO] = contexto
    presupuesto = elegir_presupuesto(
        [
            presupuesto_de_ficha(ficha),
            *(_con_fuente(leido[3], anexo["tipo"]) for anexo, leido, _ in ordenados),
        ]
    )
    resultado = await guardar_lectura_de(
        actor,
        documentos=documentos,
        nombre=principal[1][0],
        secciones=secciones,
        textos=checklist(secciones),
        registro_id=ficha["id"],
    )
    ficha_resumen = resumir_ficha(ficha)
    for clave in ("fechas", "presupuesto", "necesita"):
        if not resultado["resumen"].get(clave):
            resultado["resumen"][clave] = ficha_resumen[clave]
    _con_presupuesto(resultado, presupuesto)
    resultado["documentos_lista"] = ficha_resumen["documentos_lista"]
    resultado["anexos"] = _anexos_presentables(
        anexos,
        {str(fila["nombre"]): fila for fila in filas},
        {_nombre_fila(anexo) for anexo, _, _ in leidos},
        sin_leer,
    )
    resultado["cambios_acta"] = cambios
    resultado["items_pedidos"] = ficha_resumen["items_pedidos"]
    resultado["items_leidos"] = items_leidos
    resultado["estado"] = "listo"
    resultado["codigo"] = ficha["codigo"]
    resultado["entidad"] = ficha.get("entidad") or ""
    # La ficha manda (el RUC del código es seguro); los anexos completan lo que la ficha no trae:
    # dirección, teléfono y correo suelen estar solo en el membrete del TDR.
    resultado["entidad_datos"] = completar_entidad(
        datos_entidad(ficha),
        *(leido[4] if len(leido) > 4 else {} for _, leido, _ in ordenados),
    )
    resultado["registro_id"] = ficha["id"]
    return resultado


async def estado_desde_codigo(
    actor: Actor,
    vistas: frozenset[Vista],
    *,
    documentos: RepositorioDocumentos,
    tdr: RepositorioTdr,
    codigo: str,
) -> dict[str, Any]:
    """Cómo va la bajada de los anexos, sin leer ningún archivo.

    El panel pregunta esto cada pocos segundos mientras espera. Son dos consultas indexadas: no abre
    el PDF ni escribe nada, así que cientos de personas esperando no cargan ni la base ni la CPU. El
    PDF se lee una sola vez, cuando el estado dice `listo`. Cuenta solo los anexos elegidos, y dice
    `listo` con la misma regla que `preparar_desde_codigo`: si no, el panel pediría leer y
    recibiría otra vez `preparando`.
    """
    actor.exigir_permiso("tdr.ver")
    ficha = await documentos.ficha_publicada(fuentes=_fuentes(vistas), codigo=codigo)
    if ficha is None:
        raise NoEncontrado("No hay un proceso con ese código en las vistas activas.")
    por_nombre = {_nombre_fila(anexo): anexo for anexo in _anexos_del_proceso(ficha)}
    filas = [fila for fila in await tdr.listar(ficha["id"]) if str(fila["nombre"]) in por_nombre]
    pendientes = [fila for fila in filas if fila["estado"] == "pendiente"]
    esperando = any(_hay_que_esperar(fila, por_nombre.get(str(fila["nombre"]))) for fila in filas)
    if any(fila["estado"] == "listo" for fila in filas) and not esperando:
        estado = "listo"
    elif pendientes or not filas:
        estado = "preparando"
    else:
        estado = "error"
    respuesta: dict[str, Any] = {
        "estado": estado,
        "codigo": ficha["codigo"],
        "archivos": len(filas),
        "pendientes": len(pendientes),
        "items_listos": ficha.get("items_recogidos_en") is not None,
    }
    if estado == "preparando":
        respuesta["en_cola"] = await tdr.contar_pendientes()
    if estado == "error":
        respuesta["mensaje"] = _error_de_bajada(str(filas[0].get("error") or ""))
    return respuesta


async def resumir_proceso(
    actor: Actor,
    vistas: frozenset[Vista],
    *,
    documentos: RepositorioDocumentos,
    codigo: str = "",
    lectura_id: UUID | None = None,
) -> dict[str, Any]:
    if lectura_id is not None:
        lectura = await documentos.lectura(negocio_id=actor.negocio_id, lectura_id=lectura_id)
        if lectura is None:
            raise NoEncontrado("Esa lectura no está en la empresa.")
        return {"resumen": resumir_secciones(dict(lectura["secciones"] or {})), "origen": "tdr"}
    ficha = await documentos.ficha_publicada(fuentes=_fuentes(vistas), codigo=codigo)
    if ficha is None:
        raise NoEncontrado("No hay un proceso con ese código en las vistas activas.")
    return {"resumen": resumir_ficha(ficha), "origen": "ficha", "codigo": ficha["codigo"]}


async def marcar_requisito(
    actor: Actor,
    *,
    documentos: RepositorioDocumentos,
    requisito_id: UUID,
    estado: str,
) -> dict[str, Any]:
    if not await documentos.marcar(
        negocio_id=actor.negocio_id, requisito_id=requisito_id, estado=exigir_estado(estado)
    ):
        raise NoEncontrado("Ese requisito no está en la empresa.")
    return {"id": requisito_id, "estado": estado}


async def _con_empresa(
    actor: Actor, extras: dict[str, Any], perfil: RepositorioPerfil | None
) -> dict[str, Any]:
    """El membrete sale del perfil cuando el navegador no lo trae: sin RUC no hay oferta válida.

    Lo que el usuario escribió en el formulario manda sobre el perfil.
    """
    if perfil is None:
        return extras
    escrito = {k: v for k, v in dict(extras.get("empresa") or {}).items() if v}
    return {**extras, "empresa": {**datos_empresa(await perfil.leer(actor.negocio_id)), **escrito}}


async def titulos_usados(actor: Actor, *, documentos: RepositorioDocumentos) -> dict[str, Any]:
    """Los títulos de proforma que la empresa ya usó: el panel avisa antes de guardar."""
    return {"titulos": await documentos.titulos_de_proformas(actor.negocio_id)}


async def crear_proforma(
    actor: Actor,
    *,
    documentos: RepositorioDocumentos,
    campos: dict[str, Any],
    tipo: str,
    perfil: RepositorioPerfil | None = None,
) -> dict[str, Any]:
    cifras = calcular_proforma(
        list(campos.get("lineas") or []), float(campos["impuesto_porcentaje"])
    )
    titulo = " ".join(
        str(campos.get("titulo") or ("Cotización" if tipo == "cotizacion" else "Proforma")).split()
    )
    existentes = await documentos.titulos_de_proformas(actor.negocio_id)
    # El título distingue una proforma de otra en «Mis ofertas» y en lo enviado: no se repite.
    if titulo_repetido(titulo, existentes):
        raise EstadoInvalido(
            f"Ya tienes una proforma con el título «{titulo}». Cámbialo, por ejemplo: "
            f"«{titulo_libre(titulo, existentes)}»."
        )
    extras = _extras(await _con_empresa(actor, _extras(campos.get("extras")), perfil))
    entidad = await _entidad_completa(actor, documentos, campos.get("registro_id"), extras)
    if entidad:
        extras["entidad"] = entidad
    presupuesto = await _presupuesto_de(documentos, campos.get("registro_id"), extras)
    # Una proforma por encima del presupuesto no se puede adjudicar: no se guarda.
    uso = exigir_dentro_del_presupuesto(cifras, cifras["lineas"], presupuesto)
    if presupuesto:
        extras["presupuesto"] = presupuesto
    guardada = await documentos.guardar_proforma(
        negocio_id=actor.negocio_id,
        campos={
            "usuario_id": actor.usuario_id,
            "registro_id": campos.get("registro_id"),
            "tipo": tipo,
            "titulo": titulo,
            "entidad": campos.get("entidad") or "",
            "objeto": campos.get("objeto") or "",
            "contacto": campos.get("contacto") or "",
            "impuesto_porcentaje": cifras["impuesto_porcentaje"],
            "lineas": cifras["lineas"],
            "cifras": cifras,
            "extras": extras,
        },
    )
    return {
        **guardada,
        "cifras": cifras,
        "aviso": AVISO_PRECIOS,
        "presupuesto": presupuesto,
        "uso_presupuesto": uso,
    }


async def _entidad_completa(
    actor: Actor, documentos: RepositorioDocumentos, registro_id: Any, extras: dict[str, Any]
) -> dict[str, str]:
    """RUC, dirección, teléfono y correo de la entidad para imprimir en la proforma.

    Manda lo que la persona dejó en el formulario; lo que falte se completa con la ficha de la
    ínfima (el RUC va en su código, la dirección de entrega con cantón y provincia) y después con
    el texto de sus anexos (membrete y pie del TDR, pliego, acta). Así el PDF no sale con «RUC»,
    «Dirección» y «Teléfono» vacíos aunque el formulario no se haya llenado.
    """
    del_formulario = dict(extras.get("entidad") or {})
    if not registro_id:
        return completar_entidad(del_formulario)
    try:
        datos = await documentos.datos_de_entidad(
            negocio_id=actor.negocio_id, registro_id=UUID(str(registro_id))
        )
    except (ValueError, TypeError):
        return completar_entidad(del_formulario)
    return completar_entidad(
        del_formulario,
        datos_entidad(datos),
        datos_entidad_de_texto(str(datos.get("contexto_anexos") or "")),
        # El contacto de la ficha trae el correo del funcionario encargado.
        datos_entidad_de_texto(str(datos.get("contacto") or "")),
    )


async def proforma_guardada(
    actor: Actor, *, documentos: RepositorioDocumentos, proforma_id: UUID
) -> dict[str, Any] | None:
    """La proforma guardada, con los datos de la entidad completos.

    Las guardadas antes de conservar `entidad` no la traen: se completa al leerla, con la ficha y
    los anexos, para que su PDF y su Word no salgan con el RUC, la dirección y el teléfono vacíos.
    """
    documento = await documentos.proforma(negocio_id=actor.negocio_id, proforma_id=proforma_id)
    if documento is None or documento.get("tipo") == "ficha":
        return documento
    extras = dict(documento.get("extras") or {})
    actual = dict(extras.get("entidad") or {})
    if all(actual.get(campo) for campo in ("ruc", "direccion", "telefono")):
        return documento
    with contextlib.suppress(Exception):  # completar es un extra: nunca impide ver la proforma
        entidad = await _entidad_completa(actor, documentos, documento.get("registro_id"), extras)
        if entidad:
            extras["entidad"] = entidad
            documento = {**documento, "extras": extras}
    return documento


async def _presupuesto_de(
    documentos: RepositorioDocumentos, registro_id: Any, extras: dict[str, Any]
) -> dict[str, Any] | None:
    """El presupuesto contra el que se mide la proforma.

    El navegador manda el que le dio la lectura del proceso (TDR, acta o ficha). Si la proforma es
    de un proceso guardado, la ficha se vuelve a leer aquí: así un presupuesto publicado no depende
    de lo que el navegador envíe. Entre los dos manda la fuente más fiable
    (`dominio/presupuesto.py::PRIORIDAD_FUENTE`).
    """
    del_navegador = normalizar_presupuesto(extras.get("presupuesto"))
    de_la_ficha = None
    if registro_id:
        with contextlib.suppress(ValueError, TypeError):
            datos = await documentos.datos_de_presupuesto(UUID(str(registro_id)))
            de_la_ficha = presupuesto_de_ficha(datos) if datos else None
    return elegir_presupuesto([de_la_ficha, del_navegador])


_CAMPOS_ENTIDAD = ("ruc", "direccion", "telefono", "correo")

_CLAVES_EXTRAS = (
    "empresa",
    "carta",
    "condiciones",
    "experiencia",
    "personal",
    "equipo",
    "cumplimiento",
    "fecha",
    "origen",
    "codigo",
    "presupuesto",
)


def _extras(valor: Any) -> dict[str, Any]:
    """Solo las claves que se imprimen, y con tope: es texto libre que viene del navegador."""
    if not isinstance(valor, dict):
        return {}
    extras = {clave: valor[clave] for clave in _CLAVES_EXTRAS if valor.get(clave)}
    # RUC, dirección y teléfono de la entidad, Nº de proforma y código de necesidad: el PDF los
    # imprime. Antes no estaban en la lista y se perdían al guardar: la proforma salía sin ellos.
    entidad = (
        {
            campo: " ".join(str((valor.get("entidad") or {}).get(campo) or "").split())[:300]
            for campo in _CAMPOS_ENTIDAD
        }
        if isinstance(valor.get("entidad"), dict)
        else {}
    )
    if any(entidad.values()):
        extras["entidad"] = {campo: texto for campo, texto in entidad.items() if texto}
    for clave in ("numero", "necesidad"):
        texto = " ".join(str(valor.get(clave) or "").split())[:120]
        if texto:
            extras[clave] = texto
    if valor.get("integridad") is False:
        extras["integridad"] = False
    if "presupuesto" in extras:
        presupuesto = normalizar_presupuesto(extras["presupuesto"])
        if presupuesto:
            extras["presupuesto"] = presupuesto
        else:
            extras.pop("presupuesto")
    if len(json.dumps(extras, ensure_ascii=False, default=str)) > 60_000:
        raise DatoInvalido("La oferta es demasiado larga. Acorta la carta o los requisitos.")
    extras.setdefault("fecha", datetime.now(UTC).astimezone(_HORA_EC).strftime("%d/%m/%Y"))
    return extras


_DATOS_FICHA = ("marca", "modelo", "pais_origen", "anio_fabricacion", "garantia", "cpc")


def _especificaciones(campos: dict[str, Any]) -> list[dict[str, str]]:
    """Requerido por la entidad frente a lo ofertado. Una característica suelta va sin requerido."""
    filas = [
        {
            "requerido": str(fila.get("requerido") or "").strip(),
            "ofertado": str(fila.get("ofertado") or "").strip(),
        }
        for fila in campos.get("especificaciones") or []
        if isinstance(fila, dict)
    ]
    filas = [fila for fila in filas if fila["requerido"] or fila["ofertado"]]
    if not filas:
        filas = [
            {"requerido": "", "ofertado": renglon.strip()}
            for renglon in str(campos.get("caracteristicas") or "").splitlines()
            if renglon.strip()
        ]
    return filas[:80]


async def crear_ficha(
    actor: Actor,
    *,
    documentos: RepositorioDocumentos,
    campos: dict[str, Any],
    perfil: RepositorioPerfil | None = None,
) -> dict[str, Any]:
    nombre = str(campos.get("nombre") or "").strip()
    if not nombre:
        raise DatoInvalido("La ficha necesita el nombre del producto.")
    especificaciones = _especificaciones(campos)
    linea = {
        "nombre": nombre,
        **{clave: str(campos.get(clave) or "").strip() for clave in _DATOS_FICHA},
        "caracteristicas": "\n".join(fila["ofertado"] for fila in especificaciones),
        "especificaciones": especificaciones,
        "descripcion": nombre,
    }
    extras = _extras(await _con_empresa(actor, _extras(campos.get("extras")), perfil))
    return await documentos.guardar_proforma(
        negocio_id=actor.negocio_id,
        campos={
            "usuario_id": actor.usuario_id,
            "registro_id": campos.get("registro_id"),
            "tipo": "ficha",
            "titulo": f"Ficha técnica · {nombre}",
            "entidad": str(campos.get("entidad") or "").strip(),
            "objeto": str(campos.get("objeto") or "").strip() or nombre,
            "contacto": campos.get("contacto") or "",
            "impuesto_porcentaje": 0,
            "lineas": [linea],
            "cifras": {},
            "extras": extras,
        },
    )


async def comparar_con_tdr(
    actor: Actor,
    *,
    documentos: RepositorioDocumentos,
    lectura_id: UUID,
    proforma_id: UUID,
) -> dict[str, Any]:
    lectura = await documentos.lectura(negocio_id=actor.negocio_id, lectura_id=lectura_id)
    documento = await documentos.proforma(negocio_id=actor.negocio_id, proforma_id=proforma_id)
    if lectura is None or documento is None:
        raise NoEncontrado("La lectura o la proforma no está en la empresa.")
    requisitos = await documentos.requisitos(negocio_id=actor.negocio_id, lectura_id=lectura_id)
    textos = [fila["texto"] for fila in requisitos] or checklist(dict(lectura["secciones"] or {}))
    extras = documento.get("extras") or {}
    partes = [str(extras.get("carta") or "")]
    partes.extend(str(valor) for valor in (extras.get("condiciones") or {}).values())
    for clave in ("experiencia", "personal", "equipo"):
        partes.extend(str(fila) for fila in extras.get(clave) or [])
    cumplimiento = [fila for fila in extras.get("cumplimiento") or [] if isinstance(fila, dict)]
    for fila in cumplimiento:
        partes.append(str(fila.get("requisito") or ""))
        partes.append(str(fila.get("como_cumple") or ""))
    return contrastar(
        textos,
        list(documento.get("lineas") or []),
        texto_extra=" ".join(partes),
        cumplimiento=cumplimiento,
    )


def _termino(pregunta: str) -> str:
    """La palabra más larga de la pregunta, sin la marca de plural.

    La búsqueda es una frase dentro del texto publicado. «impresoras» no aparecería dentro de
    «impresora», y al revés sí.
    """
    palabras = []
    for token in normalizar(pregunta).split():
        palabra = "".join(caracter for caracter in token if caracter.isalnum())
        if palabra not in _PARAR and palabra not in _INTENTO and len(palabra) >= 4:
            palabras.append(palabra)
    if not palabras:
        return ""
    palabra = max(palabras, key=len)
    if len(palabra) > 5 and palabra.endswith("es"):
        return palabra[:-2]
    if len(palabra) > 4 and palabra.endswith("s"):
        return palabra[:-1]
    return palabra


_TEMAS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("plazos", "Plazos", ("plazo", "fecha", "cuando", "cronograma", "dias", "tiempo", "hasta")),
    ("presupuesto", "Presupuesto", ("presupuesto", "monto", "cuanto", "valor referencial")),
    ("entregables", "Entregables", ("entreg", "producto")),
    ("requisitos_tecnicos", "Requisitos técnicos", ("especific", "tecnic", "requis", "document")),
    ("condiciones", "Condiciones", ("condicion", "pago", "garantia", "multa", "forma de")),
    ("actividades", "Actividades", ("actividad", "tarea", "que hay que hacer")),
    ("alcance", "Alcance", ("alcance",)),
    ("objeto", "Objeto", ("objeto", "necesita", "solicita", "piden", "trata", "de que", "que es")),
)
_ETIQUETAS = {clave: etiqueta for clave, etiqueta, _ in _TEMAS}
_ASISTENTE = (
    "Eres el asistente de una empresa ecuatoriana que se presenta a procesos de contratación "
    "pública (SERCOP). Contestas en español, breve y concreto, en 2 a 6 frases o una lista corta. "
    "Usa solo el TDR y los datos de la empresa que te dan. Si la respuesta no está ahí, dilo y "
    "sugiere qué revisar. Nunca inventes precios, fechas ni requisitos."
)


def _sobre_tdr(plana: str) -> list[str]:
    return [clave for clave, _, pistas in _TEMAS if any(pista in plana for pista in pistas)]


def _oraciones_con(termino: str, secciones: dict[str, str]) -> list[str]:
    if not termino:
        return []
    halladas = []
    for clave, texto in secciones.items():
        for oracion in re.split(r"(?<=[.;:])\s+", texto):
            if termino in normalizar(oracion):
                halladas.append(f"{_ETIQUETAS.get(clave, clave.title())}: {oracion.strip()[:400]}")
    return halladas[:6]


async def _con_modelo(
    actor: Actor,
    *,
    pregunta: str,
    lectura: dict[str, Any] | None,
    perfil: RepositorioPerfil,
    modelo: ModeloIa,
    creditos: RepositorioCreditos,
) -> str:
    datos = await perfil.leer(actor.negocio_id)
    contexto = {
        "tdr": {
            clave: str(valor)[:1500] for clave, valor in dict(lectura["secciones"] or {}).items()
        }
        if lectura
        else {},
        "empresa": datos_empresa(datos),
        "catalogo": [str(o.get("nombre")) for o in (datos.get("ofertas") or [])[:20]],
        "experiencia": [
            f"{e.get('objeto')} · {e.get('entidad')}" for e in (datos.get("experiencia") or [])[:10]
        ],
    }
    creditos = creditos_de(actor, creditos)
    await creditos.consumir(
        actor.negocio_id, actor.usuario_id, COSTO_PREGUNTA, "Pregunta al asistente"
    )
    try:
        return (
            await modelo.completar(
                _ASISTENTE,
                f"Datos:\n{json.dumps(contexto, ensure_ascii=False, default=str)}\n\n"
                f"Pregunta: {pregunta}",
                max_tokens=2000,
            )
        ).strip()
    except EstadoInvalido:
        await creditos.devolver(actor.negocio_id, COSTO_PREGUNTA, "Devolución: la IA no respondió")
        raise


async def preguntar(
    actor: Actor,
    vistas: frozenset[Vista],
    *,
    pregunta: str,
    documentos: RepositorioDocumentos,
    mercado: RepositorioMercado,
    perfil: RepositorioPerfil,
    cpc: RepositorioCpc,
    radar: RepositorioRadar,
    modelo: ModeloIa | None = None,
    creditos: RepositorioCreditos | None = None,
    lectura_id: UUID | None = None,
) -> dict[str, Any]:
    """Contesta con datos guardados y, si hay modelo configurado, redacta la respuesta con IA."""
    ahora = datetime.now(UTC).isoformat()
    plana = normalizar(pregunta)
    if not plana:
        raise DatoInvalido("Escribe la pregunta.")
    menciona_tdr = any(pista in plana for pista in ("tdr", "pliego", "termino", "proceso"))

    if not menciona_tdr and any(pista in plana for pista in ("pendiente", "me falta", "faltan")):
        # Se piden ya filtrados y con tope: de la respuesta salen doce, y traer el checklist
        # entero de la empresa para filtrarlo aquí eran miles de filas por pregunta.
        filas = [
            fila["texto"]
            for fila in await documentos.requisitos(
                negocio_id=actor.negocio_id, estado="pendiente", limite=12
            )
        ]
        return _respuesta(
            "Estos requisitos siguen pendientes:"
            if filas
            else "No hay requisitos pendientes. Trae un TDR para armar la lista.",
            filas[:12],
            "Checklist de la empresa",
            ahora,
        )
    if any(pista in plana for pista in ("proveedor", "ganad", "adjudic", "competencia")):
        datos = await ver_proveedores(vistas, mercado=mercado, q=_termino(pregunta))
        nombres = [fila["nombre"] for fila in datos["filas"][:8]]
        return _respuesta(
            "Proveedores adjudicados en la búsqueda:"
            if nombres
            else "No hay adjudicaciones para esa búsqueda.",
            nombres,
            "OCDS, proveedor adjudicado",
            ahora,
        )
    if any(pista in plana for pista in ("entidades", "instituc", "quien compra", "quienes compr")):
        datos = await ver_entidades(vistas, mercado=mercado, q=_termino(pregunta))
        nombres = [f"{fila['nombre']} ({fila['procesos']} procesos)" for fila in datos["filas"][:8]]
        return _respuesta(
            "Entidades con procesos que coinciden:"
            if nombres
            else "No hay entidades para esa búsqueda.",
            nombres,
            "Procesos publicados",
            ahora,
        )
    if any(pista in plana for pista in ("oportunidad", "radar", "nuevos procesos")):
        radar_datos = await ver_radar(actor, vistas=vistas, perfil=perfil, cpc=cpc, radar=radar)
        filas = [
            f"{fila.get('codigo')} · {fila.get('objeto') or 'sin objeto'}"
            for fila in (radar_datos.get("oportunidades") or [])[:5]
        ]
        return _respuesta(
            radar_datos.get("motivo") or "Oportunidades que el perfil reconoce ahora:",
            filas,
            "Radar de la empresa",
            ahora,
        )

    lectura = (
        await documentos.lectura(negocio_id=actor.negocio_id, lectura_id=lectura_id)
        if lectura_id
        else await documentos.ultima(negocio_id=actor.negocio_id)
    )
    aviso = ""
    if modelo is not None and creditos is not None and modelo.disponible:
        try:
            texto = await _con_modelo(
                actor,
                pregunta=pregunta,
                lectura=lectura,
                perfil=perfil,
                modelo=modelo,
                creditos=creditos,
            )
            if texto:
                origen = f"IA ({modelo.modelo})"
                if lectura:
                    origen += f" · TDR {lectura['nombre']}"
                return _respuesta(texto, [], origen, ahora)
        except SinCreditos:
            aviso = "Sin créditos de IA: contesto con el texto del TDR."
        except EstadoInvalido:
            aviso = "La IA no respondió: contesto con el texto del TDR."

    if lectura is None:
        return _respuesta(
            "Todavía no hay un TDR leído. En «Preparar oferta» escribe el código del proceso y "
            "pulsa «Traer el TDR»; luego pregúntame por plazos, requisitos o entregables.",
            [],
            "Asistente",
            ahora,
            aviso,
        )
    secciones = dict(lectura["secciones"] or {})
    origen = f"TDR {lectura['nombre']}"
    temas = [clave for clave in _sobre_tdr(plana) if secciones.get(clave)]
    if temas:
        return _respuesta(
            "Esto dice el TDR:",
            [f"{_ETIQUETAS[clave]}: {secciones[clave][:900]}" for clave in temas[:3]],
            origen,
            ahora,
            aviso,
        )
    halladas = _oraciones_con(_termino(pregunta), secciones)
    if halladas:
        return _respuesta("Encontré esto en el TDR:", halladas, origen, ahora, aviso)
    if menciona_tdr or _sobre_tdr(plana):
        resumen = [
            f"{_ETIQUETAS.get(clave, clave.title())}: {texto[:500]}"
            for clave, texto in secciones.items()
        ]
        return _respuesta(
            "El TDR no trae un apartado sobre eso. Este es su contenido:",
            resumen[:6],
            origen,
            ahora,
            aviso,
        )
    return _respuesta(
        "Pregúntame por el TDR (plazos, entregables, requisitos, forma de pago), por los "
        "requisitos pendientes, por proveedores que ganan o por entidades que compran.",
        [],
        "Asistente",
        ahora,
        aviso,
    )


def _respuesta(
    texto: str, datos: list[Any], origen: str, consultado_en: str, aviso: str = ""
) -> dict[str, Any]:
    respuesta: dict[str, Any] = {
        "respuesta": texto,
        "datos": datos,
        "fuentes": [{"origen": origen, "consultado_en": consultado_en}],
    }
    if aviso:
        respuesta["aviso"] = aviso
    return respuesta
