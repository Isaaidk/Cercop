"""Herramientas del asistente: lo que el chat puede consultar o hacer con los casos de uso.

Cada herramienta tiene nombre, descripción y parámetros en el formato `tools` de la API de OpenAI,
y una función que llama a un caso de uso **existente** con el actor de la sesión. Nada se salta: el
RLS, los permisos por rol y las vistas concedidas se aplican igual que en la pantalla de la que sale
cada dato. El asistente no ve más de lo que la persona ya puede ver.

Cada una devuelve dos cosas:

- `resumen`: texto compacto para el modelo. Lleva como mucho `MAX_ELEMENTOS` filas y solo los
  campos que hacen falta para contestar: cada token cuesta tiempo y dinero, y un resumen corto
  también deja menos sitio a que el modelo se pierda.
- `tarjetas`: lo que pinta el panel, con la forma del contrato de la API. El modelo no las ve ni
  las redacta: las tarjetas salen de los datos, no del texto generado, así que no pueden inventar.

Los argumentos que manda el modelo se validan aquí (`validar`) antes de tocar nada: el modelo es
una entrada más, y como tal puede mandar tipos raros, listas enormes o campos que no existen.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from uuid import UUID

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.casos_uso.buscar_registros import buscar
from contratacion.aplicacion.casos_uso.gestionar_perfil import consultar_ruc_publico
from contratacion.aplicacion.casos_uso.revisar_alertas import previsualizar_alerta
from contratacion.aplicacion.casos_uso.seguimiento_ofertas import ETAPAS, ver_ofertas
from contratacion.aplicacion.casos_uso.ver_mercado import ver_precios, ver_proveedores
from contratacion.aplicacion.casos_uso.ver_propuestas import ver_propuestas
from contratacion.aplicacion.puertos.asistente import AlertasDelUsuario
from contratacion.aplicacion.puertos.cache import Cache
from contratacion.aplicacion.puertos.consultas import RepositorioConsultas
from contratacion.aplicacion.puertos.cpc import RepositorioCpc
from contratacion.aplicacion.puertos.mercado import RepositorioMercado
from contratacion.aplicacion.puertos.perfil import (
    ConsultaRuc,
    HistorialContratos,
    RepositorioPerfil,
)
from contratacion.aplicacion.puertos.radar import InfimasAbiertas
from contratacion.aplicacion.puertos.seguimiento import RepositorioSeguimiento
from contratacion.dominio.acceso import Vista, fuentes_para_vistas
from contratacion.dominio.busqueda import (
    Categoria,
    Filtros,
    codigo_cercoapp,
    es_codigo_cpc,
    normalizar_terminos,
)
from contratacion.dominio.errores import DatoInvalido, ErrorDominio, EstadoInvalido
from contratacion.dominio.intencion import codigo_de_proceso, provincia_oficial
from contratacion.dominio.verificacion import ruc_valido

registro = logging.getLogger(__name__)

MAX_ELEMENTOS = 8
_FRECUENCIAS = ("inmediata", "diaria", "semanal")
_ORDENES = ("coincidencia", "cierre", "presupuesto")
# Pestañas del panel a las que el asistente puede mandar. Son las que el panel reconoce.
PESTANAS = ("propuestas", "ofertas", "alertas", "mis-ofertas", "empresa", "documentos")
_MENSAJE_RUC = (
    "El RUC debe tener 13 dígitos, con provincia válida y establecimiento distinto de 000."
)


# Qué fuente hace falta para cada herramienta que lee datos de contratación. Basta **una** de las
# de la tupla. Es la misma regla que la pantalla de la que sale cada dato: ínfimas y propuestas
# leen NCO; precios, competidores e historial de un RUC salen de las ofertas adjudicadas (OCDS);
# un proceso por su código, una alerta o el botón de proforma valen con cualquiera.
#
# Las que no están (datos de la empresa, sus alertas, sus proformas, el SRI) no leen el histórico.
CUALQUIER_FUENTE = ("NCO", "OCDS")
FUENTES_POR_HERRAMIENTA: dict[str, tuple[str, ...]] = {
    "buscar_infimas": ("NCO",),
    "propuestas_para_ti": ("NCO",),
    "estado_proceso": CUALQUIER_FUENTE,
    "preparar_proforma": CUALQUIER_FUENTE,
    "crear_alerta": CUALQUIER_FUENTE,
    "precio_referencia": ("OCDS",),
    "competidores": ("OCDS",),
    "historial_ruc": ("OCDS",),
}
SIN_VISTA = (
    "Tu cuenta no tiene acceso a esos datos: el administrador de la plataforma no tiene activa "
    "esa vista para ti."
)


def herramienta_permitida(nombre: str, vistas: frozenset[Vista]) -> bool:
    """¿Puede quien tiene estas vistas usar la herramienta? Las que no leen datos, siempre."""
    necesarias = FUENTES_POR_HERRAMIENTA.get(nombre)
    if necesarias is None:
        return True
    permitidas = fuentes_para_vistas(vistas)
    return any(fuente in permitidas for fuente in necesarias)


@dataclass(frozen=True, slots=True)
class Resultado:
    resumen: str
    tarjetas: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class Servicios:
    """Lo que las herramientas necesitan, ya resuelto para la persona que pregunta."""

    actor: Actor
    vistas: frozenset[Vista]
    perfil: RepositorioPerfil
    cpc: RepositorioCpc
    infimas: InfimasAbiertas
    alertas: AlertasDelUsuario
    cache: Cache
    consultas: RepositorioConsultas
    seguimiento: RepositorioSeguimiento
    mercado: RepositorioMercado
    sri: ConsultaRuc
    historial: HistorialContratos
    ttl_memo_seg: int = 0


Funcion = Callable[[Servicios, dict[str, Any]], Awaitable[Resultado]]
Validador = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class Herramienta:
    nombre: str
    descripcion: str
    parametros: dict[str, Any]
    validar: Validador
    ejecutar: Funcion

    def esquema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.nombre,
                "description": self.descripcion,
                "parameters": self.parametros,
            },
        }


# --- Validación de argumentos ------------------------------------------------------------------ #


def _texto(valor: Any, *, largo: int = 120) -> str:
    if valor is None:
        return ""
    if not isinstance(valor, str | int | float):
        raise DatoInvalido("Un argumento de texto llegó con otro tipo.")
    return " ".join(str(valor).split())[:largo]


def _textos(valor: Any, *, maximo: int = 10, largo: int = 60) -> list[str]:
    if valor is None or valor == "":
        return []
    if isinstance(valor, str):
        partes: list[Any] = valor.split(",")
    elif isinstance(valor, list):
        partes = valor
    else:
        raise DatoInvalido("Una lista llegó con otro tipo.")
    limpios: list[str] = []
    for parte in partes[: maximo * 2]:
        texto = _texto(parte, largo=largo)
        if texto and texto not in limpios:
            limpios.append(texto)
    return limpios[:maximo]


def _numero(valor: Any) -> float | None:
    if valor is None or valor == "":
        return None
    if isinstance(valor, bool):
        raise DatoInvalido("Un número llegó con otro tipo.")
    try:
        numero = float(str(valor).replace(",", "").replace("$", "").strip())
    except ValueError as error:
        raise DatoInvalido("Un número llegó con otro tipo.") from error
    if numero < 0 or numero > 1e12:
        raise DatoInvalido("El monto está fuera de rango.")
    return numero


def _booleano(valor: Any, defecto: bool) -> bool:
    if valor is None:
        return defecto
    if isinstance(valor, bool):
        return valor
    return str(valor).strip().lower() in {"true", "1", "si", "sí", "yes"}


def _provincia(valor: Any) -> str | None:
    texto = _texto(valor, largo=60)
    if not texto:
        return None
    oficial = provincia_oficial(texto)
    if oficial is None:
        raise DatoInvalido(f"«{texto}» no es una provincia del Ecuador.")
    return oficial


def _ruc(valor: Any) -> str:
    limpio = "".join(c for c in _texto(valor, largo=20) if c.isdigit())
    if not ruc_valido(limpio):
        raise DatoInvalido(_MENSAJE_RUC)
    return limpio


def _sin_argumentos(_: dict[str, Any]) -> dict[str, Any]:
    return {}


def _validar_buscar(crudos: dict[str, Any]) -> dict[str, Any]:
    texto = _texto(crudos.get("texto"), largo=120)
    cpc = _textos(crudos.get("cpc"), maximo=5, largo=40)
    provincia = _provincia(crudos.get("provincia"))
    if not texto and not cpc and not provincia:
        raise DatoInvalido("Para buscar hace falta un texto, un CPC o una provincia.")
    return {
        "texto": texto,
        "cpc": cpc,
        "provincia": provincia,
        "presupuesto_max": _numero(crudos.get("presupuesto_max")),
        "solo_abiertas": _booleano(crudos.get("solo_abiertas"), True),
    }


def _validar_propuestas(crudos: dict[str, Any]) -> dict[str, Any]:
    orden = _texto(crudos.get("orden"), largo=20) or "coincidencia"
    if orden not in _ORDENES:
        orden = "coincidencia"
    return {"orden": orden, "provincia": _provincia(crudos.get("provincia"))}


def _validar_codigo(crudos: dict[str, Any]) -> dict[str, Any]:
    crudo = _texto(crudos.get("codigo"), largo=80)
    codigo = codigo_de_proceso(crudo) or crudo.upper()
    if len(codigo) < 6:
        raise DatoInvalido("Falta el código del proceso (por ejemplo NIC-…-2026-00123).")
    return {"codigo": codigo}


def _validar_proforma(crudos: dict[str, Any]) -> dict[str, Any]:
    registro_id = _texto(crudos.get("registro_id"), largo=40)
    if registro_id:
        try:
            UUID(registro_id)
        except ValueError as error:
            raise DatoInvalido("El identificador del proceso no es válido.") from error
    codigo = _texto(crudos.get("codigo"), largo=80)
    if not codigo and not registro_id:
        raise DatoInvalido("Falta el código del proceso.")
    return {
        "codigo": (codigo_de_proceso(codigo) or codigo.upper()) if codigo else "",
        "registro_id": registro_id,
    }


def _validar_alerta(crudos: dict[str, Any]) -> dict[str, Any]:
    palabras = _textos(crudos.get("palabras"), maximo=10, largo=60)
    cpc = _textos(crudos.get("cpc"), maximo=10, largo=20)
    if not palabras and not cpc:
        raise DatoInvalido("La alerta necesita al menos una palabra clave o un CPC.")
    provincias = [p for p in (_provincia(v) for v in _textos(crudos.get("provincias"))) if p]
    frecuencia = _texto(crudos.get("frecuencia"), largo=20).lower() or "diaria"
    if frecuencia not in _FRECUENCIAS:
        frecuencia = "diaria"
    nombre = _texto(crudos.get("nombre"), largo=80) or ", ".join(palabras or cpc)[:80]
    if len(nombre) < 2:
        nombre = "Alerta del asistente"
    return {
        "nombre": nombre,
        "palabras": palabras,
        "cpc": cpc,
        "provincias": provincias,
        "frecuencia": frecuencia,
    }


def _validar_ofertas(crudos: dict[str, Any]) -> dict[str, Any]:
    etapa = _texto(crudos.get("etapa"), largo=20).lower()
    return {"etapa": etapa if etapa in ETAPAS else ""}


def _validar_ruc(crudos: dict[str, Any]) -> dict[str, Any]:
    return {"ruc": _ruc(crudos.get("ruc"))}


def _validar_mercado(crudos: dict[str, Any]) -> dict[str, Any]:
    texto = _texto(crudos.get("texto_o_cpc"), largo=80)
    if len(texto) < 3:
        raise DatoInvalido("Indica qué producto o qué CPC quieres comparar.")
    return {"texto_o_cpc": texto}


# --- Ayudas de formato ------------------------------------------------------------------------- #


def _iso(valor: Any) -> str | None:
    if isinstance(valor, datetime | date):
        return valor.isoformat()
    if isinstance(valor, str) and valor.strip():
        return valor.strip()
    return None


def _monto(fila: Any) -> float | None:
    for clave in ("presupuesto", "monto", "valor_unitario", "total"):
        valor = fila.get(clave) if hasattr(fila, "get") else None
        try:
            numero = float(str(valor).replace(",", "")) if valor not in (None, "") else 0.0
        except ValueError:
            continue
        if numero > 0:
            return numero
    return None


def _dinero(valor: Any) -> str:
    if valor in (None, ""):
        return "—"
    try:
        return f"${float(valor):,.2f}"
    except (TypeError, ValueError):
        return str(valor)


def _fecha_corta(valor: Any) -> str:
    texto = _iso(valor)
    return texto[:16].replace("T", " ") if texto else "sin fecha"


def _objeto(fila: Any) -> str:
    return str(fila.get("objeto") or fila.get("objeto_compra") or fila.get("titulo") or "")[:240]


def _codigo(fila: Any) -> str:
    return str(fila.get("codigo_cercoapp") or fila.get("codigo") or "")


def _cierre(fila: Any) -> str | None:
    return _iso(fila.get("plazo") or fila.get("plazo_proformas_en")) or _iso(
        fila.get("fecha_limite_proformas")
    )


def _elemento_infima(fila: Any, motivos: list[str] | None = None) -> dict[str, Any]:
    return {
        "registro_id": str(fila.get("id") or ""),
        "codigo": _codigo(fila),
        "objeto": _objeto(fila),
        "entidad": str(fila.get("entidad") or ""),
        "provincia": str(fila.get("provincia") or ""),
        "canton": str(fila.get("canton") or ""),
        "presupuesto": _monto(fila),
        "cierre": _cierre(fila),
        "motivos": list(motivos if motivos is not None else fila.get("motivos") or [])[:4],
    }


def _lineas_infimas(elementos: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"- {e['codigo']} | {e['objeto'][:110]} | {e['entidad'][:60]} | {e['provincia']} | "
        f"{_dinero(e['presupuesto'])} | cierra {_fecha_corta(e['cierre'])}"
        for e in elementos
    )


def _ir(etiqueta: str, pestana: str) -> dict[str, Any]:
    return {"tipo": "accion", "etiqueta": etiqueta, "accion": {"tipo": "ir", "pestana": pestana}}


def _preparar(registro_id: str, codigo: str) -> dict[str, Any]:
    return {
        "tipo": "accion",
        "etiqueta": f"Preparar proforma de {codigo}" if codigo else "Preparar proforma",
        "accion": {"tipo": "preparar_oferta", "registro_id": registro_id, "codigo": codigo},
    }


# --- Herramientas ------------------------------------------------------------------------------ #


async def buscar_infimas(servicios: Servicios, argumentos: dict[str, Any]) -> Resultado:
    if "NCO" not in fuentes_para_vistas(servicios.vistas):
        return Resultado("La cuenta no tiene acceso a las ínfimas cuantías.")
    texto = " ".join(p for p in str(argumentos.get("texto") or "").split() if len(p) > 2)
    tope = argumentos.get("presupuesto_max")
    provincia = argumentos.get("provincia")
    filtros = Filtros(
        terminos=normalizar_terminos(texto) if texto else (),
        cpc=normalizar_terminos(argumentos.get("cpc") or []),
        categoria=Categoria.INFIMAS,
        fuentes_permitidas=("NCO",),
        provincias=(provincia,) if provincia else (),
        solo_con_plazo=bool(argumentos.get("solo_abiertas", True)),
        tamano=50 if tope else MAX_ELEMENTOS,
    )
    pagina = await buscar(
        filtros,
        cache=servicios.cache,
        repositorio=servicios.consultas,
        ttl_memo_seg=servicios.ttl_memo_seg,
    )
    filas = list(pagina.elementos)
    total = pagina.total
    if tope:
        filas = [fila for fila in filas if (_monto(fila) or 0) <= tope]
        total = len(filas)
    elementos = [_elemento_infima(fila, []) for fila in filas[:MAX_ELEMENTOS]]
    criterio = ", ".join(
        parte
        for parte in (
            texto,
            ", ".join(argumentos.get("cpc") or []),
            provincia or "",
            f"hasta {_dinero(tope)}" if tope else "",
        )
        if parte
    )
    if not elementos:
        return Resultado(
            f"No hay ínfimas {'abiertas ' if filtros.solo_con_plazo else ''}"
            f"que coincidan con: {criterio}."
        )
    tarjeta = {
        "tipo": "infimas",
        "titulo": f"Ínfimas: {criterio}"[:120],
        "total": total,
        "elementos": elementos,
        "ver_mas": None,
    }
    return Resultado(
        f"{total} ínfimas coinciden con «{criterio}». Las {len(elementos)} más recientes:\n"
        + _lineas_infimas(elementos),
        [tarjeta],
    )


async def propuestas_para_ti(servicios: Servicios, argumentos: dict[str, Any]) -> Resultado:
    respuesta = await ver_propuestas(
        servicios.actor,
        vistas=servicios.vistas,
        perfil=servicios.perfil,
        cpc=servicios.cpc,
        infimas=servicios.infimas,
        cache=servicios.cache,
        tamano=MAX_ELEMENTOS,
        orden=str(argumentos.get("orden") or "coincidencia"),
        provincia=argumentos.get("provincia"),
    )
    propuestas = list(respuesta.get("propuestas") or [])
    if not propuestas:
        motivo = str(respuesta.get("motivo") or "Hoy no hay ínfimas que encajen con tu perfil.")
        return Resultado(motivo, [_ir("Completar mi empresa", "empresa")])
    elementos = [_elemento_infima(fila) for fila in propuestas[:MAX_ELEMENTOS]]
    total = int(respuesta.get("total") or len(elementos))
    tarjeta = {
        "tipo": "infimas",
        "titulo": "Propuestas para ti",
        "total": total,
        "elementos": elementos,
        "ver_mas": {"pestana": "propuestas"},
    }
    return Resultado(
        f"Hay {total} ínfimas abiertas que tu empresa puede ofertar según su perfil. Las "
        f"{len(elementos)} primeras:\n" + _lineas_infimas(elementos),
        [tarjeta],
    )


async def _buscar_proceso(servicios: Servicios, codigo: str) -> dict[str, Any] | None:
    fuentes = fuentes_para_vistas(servicios.vistas)
    if not fuentes:
        return None
    pagina = await buscar(
        Filtros(codigo=codigo, fuentes_permitidas=fuentes, tamano=5),
        cache=servicios.cache,
        repositorio=servicios.consultas,
        ttl_memo_seg=servicios.ttl_memo_seg,
    )
    filas = [dict(fila) for fila in pagina.elementos]
    buscado = codigo.upper()
    for fila in filas:
        if buscado in {_codigo(fila).upper(), str(fila.get("codigo") or "").upper()}:
            return fila
    return filas[0] if filas else None


def _cpc_del_proceso(fila: dict[str, Any]) -> list[dict[str, str]]:
    vistos: dict[str, str] = {}
    for item in fila.get("items") or []:
        if not isinstance(item, dict):
            continue
        codigo = str(item.get("codigo") or "").strip()
        if codigo and codigo not in vistos:
            vistos[codigo] = str(item.get("descripcion_cpc") or item.get("descripcion") or "")
    for codigo in fila.get("cpc_codigos") or []:
        vistos.setdefault(str(codigo), "")
    return [{"codigo": c, "descripcion": d[:160]} for c, d in list(vistos.items())[:8]]


async def estado_proceso(servicios: Servicios, argumentos: dict[str, Any]) -> Resultado:
    codigo = str(argumentos["codigo"])
    fila = await _buscar_proceso(servicios, codigo)
    if fila is None:
        return Resultado(
            f"No encontré el proceso {codigo} en lo que CercoApp tiene guardado. Revisa el código "
            "o búscalo en «Buscar oportunidades»."
        )
    registro_id = str(fila.get("id") or "")
    etapa: str | None = None
    try:
        for oferta in await servicios.seguimiento.listar(
            negocio_id=servicios.actor.negocio_id, limite=500
        ):
            if str(oferta.get("registro_id") or "") == registro_id:
                etapa = str(oferta.get("etapa") or "borrador")
                break
    except Exception:  # noqa: BLE001 - la etapa es un extra: sin ella el proceso se muestra igual
        registro.warning("asistente.etapa_no_disponible", exc_info=True)
    cierre = _cierre(fila)
    tarjeta: dict[str, Any] = {
        "tipo": "proceso",
        "registro_id": registro_id,
        "codigo": _codigo(fila) or codigo,
        "objeto": _objeto(fila),
        "entidad": str(fila.get("entidad") or ""),
        "estado": str(fila.get("estado") or ("Vigente" if fila.get("es_vigente") else "")),
        "presupuesto": _monto(fila),
        "publicado": _iso(fila.get("fecha_publicacion")),
        "cierre": cierre,
        "cpc": _cpc_del_proceso(fila),
        "etapa_mi_oferta": etapa,
    }
    tarjetas: list[dict[str, Any]] = [tarjeta]
    if str(fila.get("fuente") or "") == "NCO" and etapa is None:
        tarjetas.append(_preparar(registro_id, tarjeta["codigo"]))
    resumen = (
        f"Proceso {tarjeta['codigo']}: {tarjeta['objeto'][:160]}. Entidad: {tarjeta['entidad']}. "
        f"Estado: {tarjeta['estado'] or 'sin dato'}. "
        f"Presupuesto: {_dinero(tarjeta['presupuesto'])}. "
        f"Publicado: {_fecha_corta(tarjeta['publicado'])}. Cierra: {_fecha_corta(cierre)}. "
        f"Mi oferta: {etapa or 'no hay proforma'}."
    )
    return Resultado(resumen, tarjetas)


async def datos_empresa(servicios: Servicios, _: dict[str, Any]) -> Resultado:
    ficha = await servicios.perfil.leer(servicios.actor.negocio_id)
    claves = await servicios.cpc.listar(negocio_id=servicios.actor.negocio_id)
    provincias = sorted(
        {str(f.get("provincia") or "") for f in ficha.get("cobertura") or [] if f.get("provincia")}
    )
    rango = ""
    if ficha.get("presupuesto_min") or ficha.get("presupuesto_max"):
        rango = f"{_dinero(ficha.get('presupuesto_min'))} a {_dinero(ficha.get('presupuesto_max'))}"
    campos = [
        ("Razón social", ficha.get("razon_social") or ficha.get("nombre")),
        ("Nombre comercial", ficha.get("nombre_comercial")),
        ("RUC", ficha.get("ruc")),
        ("Estado en el RUP", ficha.get("estado_rup")),
        ("Ciudad", ficha.get("ciudad")),
        ("Correo", ficha.get("email_contacto")),
        ("Teléfono", ficha.get("telefono")),
        ("Provincias donde trabaja", ", ".join(provincias) or "Todo el país"),
        ("Rango de presupuesto", rango),
        ("Productos y servicios", str(len(ficha.get("ofertas") or [])) or ""),
    ]
    filas = [{"etiqueta": e, "valor": str(v)} for e, v in campos if v not in (None, "")]
    cpc = [
        {"codigo": c.texto, "descripcion": ""}
        if es_codigo_cpc(c.texto) or (c.texto.isdigit() and len(c.texto) >= 4)
        else {"codigo": "", "descripcion": c.texto}
        for c in claves[:30]
    ]
    tarjeta = {
        "tipo": "empresa",
        "titulo": str(ficha.get("razon_social") or ficha.get("nombre") or "Mi empresa"),
        "campos": filas,
        "cpc": cpc,
    }
    resumen = "; ".join(f"{f['etiqueta']}: {f['valor']}" for f in filas)
    textos_cpc = ", ".join(c.texto for c in claves[:12])
    resumen += f". CPC y palabras guardadas ({len(claves)}): {textos_cpc or 'ninguno'}."
    return Resultado(resumen, [tarjeta, _ir("Abrir Mi empresa", "empresa")])


async def crear_alerta(servicios: Servicios, argumentos: dict[str, Any]) -> Resultado:
    provincias: list[str] = list(argumentos.get("provincias") or [])
    campos = {
        "nombre": argumentos["nombre"],
        "palabras": argumentos.get("palabras") or [],
        "cpc": argumentos.get("cpc") or [],
        # Una alerta vigila una provincia (o todas). Con varias se toma la primera y se avisa.
        "provincia": provincias[0] if provincias else "",
        "canton": "",
        "presupuesto_min": None,
        "presupuesto_max": None,
        "frecuencia": argumentos.get("frecuencia") or "diaria",
        "avisar_correo": False,
    }
    fila = await servicios.alertas.crear_alerta(
        negocio_id=servicios.actor.negocio_id,
        usuario_id=servicios.actor.usuario_id,
        campos=campos,
    )
    coincidencias: int | None = None
    try:
        coincidencias = int(
            (
                await previsualizar_alerta(
                    servicios.alertas, campos, fuentes=fuentes_para_vistas(servicios.vistas)
                )
            )["total"]
        )
    except Exception:  # noqa: BLE001 - la cuenta es orientativa: la alerta ya quedó creada
        registro.warning("asistente.vista_previa_fallida", exc_info=True)
    tarjeta = {
        "tipo": "alerta",
        "alerta": {
            "id": str(fila.get("id") or ""),
            "nombre": str(fila.get("nombre") or campos["nombre"]),
            "palabras": list(fila.get("palabras") or campos["palabras"]),
            "cpc": list(fila.get("cpc") or campos["cpc"]),
            "provincias": [campos["provincia"]] if campos["provincia"] else [],
            "frecuencia": str(fila.get("frecuencia") or campos["frecuencia"]),
        },
        "coincidencias": coincidencias,
    }
    resumen = (
        f"Alerta creada: «{campos['nombre']}», palabras {campos['palabras'] or '—'}, "
        f"CPC {campos['cpc'] or '—'}, provincia {campos['provincia'] or 'todas'}, "
        f"frecuencia {campos['frecuencia']}."
    )
    if coincidencias is not None:
        resumen += f" Hoy coincidirían {coincidencias} procesos vigentes."
    if len(provincias) > 1:
        resumen += (
            f" Una alerta vigila una sola provincia: se usó {provincias[0]}. Para "
            f"{', '.join(provincias[1:])} hay que crear otra alerta."
        )
    return Resultado(resumen, [tarjeta, _ir("Ver mis alertas", "alertas")])


async def listar_alertas(servicios: Servicios, _: dict[str, Any]) -> Resultado:
    filas = [
        fila
        for fila in await servicios.alertas.listar_alertas(negocio_id=servicios.actor.negocio_id)
        if fila.get("usuario_id") == servicios.actor.usuario_id
    ]
    if not filas:
        return Resultado(
            "No tienes alertas. Puedes pedirme una, por ejemplo: «crea una alerta de limpieza en "
            "Pichincha».",
            [_ir("Ir a Mis alertas", "alertas")],
        )
    elementos = [
        {
            "id": str(fila.get("id") or ""),
            "nombre": str(fila.get("nombre") or ""),
            "frecuencia": str(fila.get("frecuencia") or "diaria"),
            "activa": bool(fila.get("activa", True)),
        }
        for fila in filas[:20]
    ]
    lineas = "\n".join(
        f"- {f.get('nombre')} | palabras {list(f.get('palabras') or [])} | CPC "
        f"{list(f.get('cpc') or [])} | {f.get('provincia') or 'todas'} | {f.get('frecuencia')}"
        f"{'' if f.get('activa', True) else ' (pausada)'}"
        for f in filas[:MAX_ELEMENTOS]
    )
    return Resultado(
        f"Tienes {len(filas)} alertas:\n{lineas}",
        [{"tipo": "alertas", "elementos": elementos}, _ir("Ir a Mis alertas", "alertas")],
    )


async def mis_ofertas(servicios: Servicios, argumentos: dict[str, Any]) -> Resultado:
    datos = await ver_ofertas(servicios.actor, repositorio=servicios.seguimiento)
    filas = list(datos.get("ofertas") or [])
    etapa = str(argumentos.get("etapa") or "")
    if etapa:
        filas = [fila for fila in filas if str(fila.get("etapa") or "borrador") == etapa]
    por_etapa = Counter(str(f.get("etapa") or "borrador") for f in datos.get("ofertas") or [])
    conteo = ", ".join(f"{n} {e}" for e, n in por_etapa.items()) or "ninguna"
    if not filas:
        texto = f"No tienes proformas{' en ' + etapa if etapa else ''}. En total: {conteo}."
        return Resultado(texto, [_ir("Abrir Mis ofertas", "mis-ofertas")])
    elementos: list[dict[str, Any]] = [
        {
            "id": str(fila.get("id") or ""),
            "titulo": str(fila.get("objeto") or fila.get("titulo") or "")[:200],
            "etapa": str(fila.get("etapa") or "borrador"),
            "monto": _monto(fila),
            "cierre": _iso(fila.get("plazo")),
            "registro_id": str(fila.get("registro_id") or "") or None,
        }
        for fila in filas[:MAX_ELEMENTOS]
    ]
    lineas = "\n".join(
        f"- {e['titulo'][:100]} | {e['etapa']} | {_dinero(e['monto'])} | cierra "
        f"{_fecha_corta(e['cierre'])}"
        for e in elementos
    )
    tasa = (datos.get("resumen") or {}).get("tasa_exito")
    return Resultado(
        f"Proformas por etapa: {conteo}. Tasa de éxito: "
        f"{f'{tasa}%' if tasa is not None else 'sin resueltas aún'}.\n{lineas}",
        [{"tipo": "ofertas", "elementos": elementos}, _ir("Abrir Mis ofertas", "mis-ofertas")],
    )


async def consultar_ruc(servicios: Servicios, argumentos: dict[str, Any]) -> Resultado:
    datos = await consultar_ruc_publico(str(argumentos["ruc"]), sri=servicios.sri)
    identidad = datos.get("identidad") or {}
    campos = [
        ("RUC", datos.get("ruc")),
        ("Razón social", identidad.get("razon_social")),
        ("Nombre comercial", identidad.get("nombre_comercial")),
        ("Estado en el SRI", (datos.get("estado_sri") or "").capitalize()),
        ("Tipo", identidad.get("tipo_persona")),
        ("Régimen", identidad.get("regimen_tributario")),
        ("Obligado a llevar contabilidad", "Sí" if identidad.get("obligado_contabilidad") else ""),
        ("Inicio de actividades", identidad.get("fecha_inicio_actividades")),
        ("Ciudad", identidad.get("ciudad")),
        ("Actividad principal", datos.get("actividad")),
        ("Avisos", " ".join(datos.get("avisos") or [])),
    ]
    filas = [{"etiqueta": e, "valor": str(v)} for e, v in campos if v not in (None, "")]
    return Resultado(
        "Datos públicos del SRI: " + "; ".join(f"{f['etiqueta']}: {f['valor']}" for f in filas),
        [{"tipo": "ruc", "campos": filas}],
    )


async def historial_ruc(servicios: Servicios, argumentos: dict[str, Any]) -> Resultado:
    if "OCDS" not in fuentes_para_vistas(servicios.vistas):
        return Resultado(SIN_VISTA)
    ruc = str(argumentos["ruc"])
    contribuyente, _ = await servicios.sri.consultar(ruc)
    razon = str(contribuyente.get("razonSocial") or "").strip()
    if len(razon) < 3:
        return Resultado(
            f"El SRI no publica la razón social del RUC {ruc}; sin ella no se puede "
            "buscar su historial."
        )
    try:
        datos = await servicios.historial.consultar(ruc, razon)
    except EstadoInvalido:
        # El portal de datos abiertos limita cuántas consultas acepta por minuto (responde 429) y
        # a veces no responde. El mensaje del adaptador está pensado para el perfil; aquí se dice
        # lo que le sirve a quien pregunta.
        return Resultado(
            f"Ahora no pude consultar el historial de {razon} en los datos abiertos del SERCOP: "
            "el portal no está respondiendo. Vuelve a intentarlo en unos minutos."
        )
    procesos = list(datos.get("procesos") or [])
    ganados = int(datos.get("verificados") or len(procesos))
    total = int(datos.get("contratos_total") or 0)
    monto = float(datos.get("monto_revisado") or 0)
    entidades = Counter(str(p.get("entidad") or "") for p in procesos if p.get("entidad"))
    principales = ", ".join(nombre for nombre, _ in entidades.most_common(3)) or "—"
    revisados = int(datos.get("revisados") or 0)
    elementos: list[dict[str, Any]] = [
        {
            "codigo": codigo_cercoapp(str(p.get("ocid") or ""), categoria=Categoria.OFERTAS) or "",
            "objeto": str(p.get("objeto") or p.get("titulo") or "")[:200],
            "entidad": str(p.get("entidad") or ""),
            "fecha": str(p.get("fecha") or "") or None,
            "monto": _monto(p),
            "resultado": "Adjudicado",
        }
        for p in procesos[:MAX_ELEMENTOS]
    ]
    datos_tarjeta = {
        "tipo": "datos",
        "titulo": f"Historial de {razon}"[:120],
        "campos": [
            {"etiqueta": "Procesos", "valor": str(total)},
            {"etiqueta": "Ganados", "valor": f"{ganados} verificados de {revisados} revisados"},
            {"etiqueta": "Monto adjudicado", "valor": _dinero(monto)},
            {"etiqueta": "Entidades principales", "valor": principales},
        ],
    }
    procesos_tarjeta = {
        "tipo": "procesos_ruc",
        "ruc": ruc,
        "razon_social": razon,
        "total": total,
        "ganados": ganados,
        "monto_total": round(monto, 2),
        "elementos": elementos,
    }
    lineas = "\n".join(
        f"- {e['codigo']} | {e['objeto'][:100]} | {e['entidad'][:60]} | {e['fecha']} | "
        f"{_dinero(e['monto'])}"
        for e in elementos
    )
    resumen = (
        f"{razon} (RUC {ruc}) en los datos abiertos del SERCOP, últimos 3 años, solo procesos con "
        f"oferta (no incluye ínfimas): {total} procesos encontrados por su nombre; de los "
        f"{revisados} más recientes, {ganados} adjudicados verificados por RUC, por "
        f"{_dinero(monto)}. Entidades principales: {principales}.\n{lineas}"
    )
    return Resultado(resumen, [datos_tarjeta, procesos_tarjeta])


def _mercado_args(texto: str) -> tuple[str, str]:
    limpio = texto.strip()
    if limpio.replace(".", "").isdigit() and len(limpio) >= 5:
        return "", limpio
    return limpio, ""


async def precio_referencia(servicios: Servicios, argumentos: dict[str, Any]) -> Resultado:
    texto = str(argumentos["texto_o_cpc"])
    q, cpc = _mercado_args(texto)
    datos = await ver_precios(servicios.vistas, mercado=servicios.mercado, q=q, cpc=cpc)
    grupos = [g for g in datos.get("grupos") or [] if g.get("resumen")]
    if not grupos:
        motivo = str(datos.get("motivo") or "")
        return Resultado(
            motivo or f"No hay adjudicaciones guardadas de «{texto}» para calcular un precio."
        )
    grupo = max(grupos, key=lambda g: int(g["resumen"]["n"]))
    resumen = grupo["resumen"]
    campos = [
        {"etiqueta": "Procesos comparados", "valor": str(resumen["n"])},
        {"etiqueta": "Mediana", "valor": _dinero(resumen["mediana"])},
        {"etiqueta": "Promedio", "valor": _dinero(resumen["promedio"])},
        {"etiqueta": "Mínimo", "valor": _dinero(resumen["minimo"])},
        {"etiqueta": "Máximo", "valor": _dinero(resumen["maximo"])},
        {"etiqueta": "CPC", "valor": str(grupo.get("cpc") or "varios")},
    ]
    tarjeta = {"tipo": "datos", "titulo": f"Precio de referencia: {texto}"[:120], "campos": campos}
    aviso = str(grupo.get("aviso") or datos.get("aviso") or "")
    return Resultado(
        "Montos adjudicados de procesos parecidos: "
        + "; ".join(f"{c['etiqueta']}: {c['valor']}" for c in campos)
        + (f". Aviso: {aviso}" if aviso else ""),
        [tarjeta],
    )


async def competidores(servicios: Servicios, argumentos: dict[str, Any]) -> Resultado:
    texto = str(argumentos["texto_o_cpc"])
    q, cpc = _mercado_args(texto)
    datos = await ver_proveedores(servicios.vistas, mercado=servicios.mercado, q=q, cpc=cpc)
    filas = list(datos.get("filas") or [])[:5]
    if not filas:
        return Resultado(
            str(datos.get("motivo") or "") or f"No hay proveedores adjudicados de «{texto}»."
        )
    campos = [
        {
            "etiqueta": str(f.get("nombre") or "Sin nombre")[:80],
            "valor": f"{f.get('procesos')} procesos, {_dinero(f.get('monto'))}",
        }
        for f in filas
    ]
    return Resultado(
        "Proveedores que más ganan en «"
        + texto
        + "»: "
        + "; ".join(f"{c['etiqueta']}: {c['valor']}" for c in campos),
        [{"tipo": "datos", "titulo": f"Competidores: {texto}"[:120], "campos": campos}],
    )


async def preparar_proforma(servicios: Servicios, argumentos: dict[str, Any]) -> Resultado:
    codigo = str(argumentos.get("codigo") or "")
    registro_id = str(argumentos.get("registro_id") or "")
    if codigo and not registro_id:
        fila = await _buscar_proceso(servicios, codigo)
        if fila is None:
            return Resultado(f"No encontré el proceso {codigo}. Revisa el código.")
        registro_id = str(fila.get("id") or "")
        codigo = _codigo(fila) or codigo
    return Resultado(
        f"Listo para preparar la proforma de {codigo or 'ese proceso'}: la persona debe pulsar el "
        "botón; la proforma se arma en «Documentos».",
        [_preparar(registro_id, codigo)],
    )


def _objeto_json(propiedades: dict[str, Any], requeridos: tuple[str, ...] = ()) -> dict[str, Any]:
    return {"type": "object", "properties": propiedades, "required": list(requeridos)}


_TEXTO = {"type": "string"}
_LISTA = {"type": "array", "items": {"type": "string"}}

HERRAMIENTAS: dict[str, Herramienta] = {
    h.nombre: h
    for h in (
        Herramienta(
            "buscar_infimas",
            "Busca ínfimas cuantías (compras pequeñas del Estado) por texto, provincia, CPC o "
            "presupuesto máximo. Úsala cuando la persona pide buscar algo concreto.",
            _objeto_json(
                {
                    "texto": {**_TEXTO, "description": "Qué se compra, p. ej. «impresoras»."},
                    "provincia": {**_TEXTO, "description": "Provincia del Ecuador."},
                    "cpc": {**_LISTA, "description": "Códigos CPC (solo dígitos)."},
                    "presupuesto_max": {"type": "number", "description": "Dólares."},
                    "solo_abiertas": {"type": "boolean", "description": "Por defecto true."},
                }
            ),
            _validar_buscar,
            buscar_infimas,
        ),
        Herramienta(
            "propuestas_para_ti",
            "Ínfimas abiertas que encajan con el perfil de la empresa (sus CPC y provincias).",
            _objeto_json(
                {
                    "orden": {"type": "string", "enum": list(_ORDENES)},
                    "provincia": {**_TEXTO, "description": "Limitar a una provincia."},
                }
            ),
            _validar_propuestas,
            propuestas_para_ti,
        ),
        Herramienta(
            "estado_proceso",
            "Estado, fechas, presupuesto y CPC de un proceso por su código (NIC-…, SIE-…).",
            _objeto_json({"codigo": _TEXTO}, ("codigo",)),
            _validar_codigo,
            estado_proceso,
        ),
        Herramienta(
            "datos_empresa",
            "Datos del perfil de la empresa de la persona: RUC, provincias, CPC.",
            _objeto_json({}),
            _sin_argumentos,
            datos_empresa,
        ),
        Herramienta(
            "crear_alerta",
            "Crea una alerta que avisa cuando salgan procesos con esas palabras o CPC. Créala "
            "solo si la persona lo pide.",
            _objeto_json(
                {
                    "nombre": {**_TEXTO, "description": "Nombre corto."},
                    "palabras": {**_LISTA, "description": "Palabras clave, p. ej. «impresoras»."},
                    "cpc": {**_LISTA, "description": "Códigos CPC."},
                    "provincias": {**_LISTA, "description": "Provincias; vacío = todo el país."},
                    "frecuencia": {"type": "string", "enum": list(_FRECUENCIAS)},
                }
            ),
            _validar_alerta,
            crear_alerta,
        ),
        Herramienta(
            "listar_alertas",
            "Las alertas que la persona tiene creadas.",
            _objeto_json({}),
            _sin_argumentos,
            listar_alertas,
        ),
        Herramienta(
            "mis_ofertas",
            "Las proformas de la empresa y su etapa (borrador, enviada, adjudicada, perdida, "
            "descartada).",
            _objeto_json({"etapa": {"type": "string", "enum": list(ETAPAS)}}),
            _validar_ofertas,
            mis_ofertas,
        ),
        Herramienta(
            "consultar_ruc",
            "Datos públicos del SRI de un RUC: razón social, estado, actividad.",
            _objeto_json({"ruc": {**_TEXTO, "description": "13 dígitos."}}, ("ruc",)),
            _validar_ruc,
            consultar_ruc,
        ),
        Herramienta(
            "historial_ruc",
            "Procesos públicos que ganó un proveedor por su RUC (últimos 3 años, sin ínfimas): "
            "cuántos, monto adjudicado, entidades y los más recientes.",
            _objeto_json({"ruc": {**_TEXTO, "description": "13 dígitos."}}, ("ruc",)),
            _validar_ruc,
            historial_ruc,
        ),
        Herramienta(
            "precio_referencia",
            "Precio de referencia (mediana, mínimo, máximo) de lo adjudicado en procesos "
            "parecidos, por producto o CPC.",
            _objeto_json({"texto_o_cpc": _TEXTO}, ("texto_o_cpc",)),
            _validar_mercado,
            precio_referencia,
        ),
        Herramienta(
            "competidores",
            "Proveedores que más contratos ganan de un producto o CPC.",
            _objeto_json({"texto_o_cpc": _TEXTO}, ("texto_o_cpc",)),
            _validar_mercado,
            competidores,
        ),
        Herramienta(
            "preparar_proforma",
            "Ofrece el botón para preparar la proforma de un proceso. No genera el documento.",
            _objeto_json({"codigo": _TEXTO, "registro_id": _TEXTO}),
            _validar_proforma,
            preparar_proforma,
        ),
    )
}


def esquemas(vistas: frozenset[Vista] | None = None) -> list[dict[str, Any]]:
    """Las herramientas que se le ofrecen al modelo. Con `vistas`, solo las que la persona puede
    usar: así el modelo ni siquiera intenta leer datos de una vista oculta."""
    return [
        herramienta.esquema()
        for herramienta in HERRAMIENTAS.values()
        if vistas is None or herramienta_permitida(herramienta.nombre, vistas)
    ]


def argumentos_de(crudos: Any) -> dict[str, Any]:
    """Los argumentos de una llamada del modelo: llegan como texto JSON (o ya como objeto)."""
    if isinstance(crudos, dict):
        return crudos
    if not crudos:
        return {}
    try:
        valor = json.loads(str(crudos))
    except ValueError as error:
        raise DatoInvalido("Los argumentos no son JSON.") from error
    if not isinstance(valor, dict):
        raise DatoInvalido("Los argumentos no son un objeto.")
    return valor


async def ejecutar(servicios: Servicios, nombre: str, crudos: Any) -> Resultado:
    """Valida y ejecuta. Un error de dominio vuelve como texto para el modelo, no como excepción."""
    herramienta = HERRAMIENTAS.get(nombre)
    if herramienta is None:
        return Resultado(f"La herramienta «{nombre}» no existe.")
    # Segunda barrera, por si el modelo llama a una herramienta que no se le ofreció: cada caso de
    # uso vuelve a comprobar sus fuentes, pero aquí se corta antes de tocar nada.
    if not herramienta_permitida(nombre, servicios.vistas):
        return Resultado(SIN_VISTA)
    try:
        argumentos = herramienta.validar(argumentos_de(crudos))
        return await herramienta.ejecutar(servicios, argumentos)
    except ErrorDominio as error:
        return Resultado(f"No se pudo: {error}")
    except Exception:  # noqa: BLE001 - una herramienta rota no tumba la conversación
        registro.exception("asistente.herramienta_fallida %s", nombre)
        return Resultado("No se pudo consultar ese dato ahora. Inténtalo de nuevo en un momento.")
