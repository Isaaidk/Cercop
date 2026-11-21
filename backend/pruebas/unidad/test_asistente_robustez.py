"""Asistente: perfil siempre presente, «sin adjudicar» y respuestas que no se quedan colgadas.

Tres quejas del cliente:

- «Cuando alguien limpia los filtros, el bot no detecta que tiene su perfil cargado.» El asistente
  leía solo la lista de CPC del buscador; ahora describe la empresa con su **perfil**.
- «Que el bot nos pueda mostrar las que no están adjudicadas.»
- «Hay solicitudes que se jalan»: el modelo lento, un fallo inesperado o un bucle de herramientas
  dejaban el chat «Pensando…» o el mensaje sin respuesta.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any, cast
from uuid import uuid4

import pytest
from pruebas.unidad.test_asistente import (
    ACTOR,
    ConversacionesFalsas,
    CreditosFalsos,
    ModeloFalso,
    _llamada,
    servicios,
)

from contratacion.aplicacion import encolador
from contratacion.aplicacion.asistente import herramientas as h
from contratacion.aplicacion.casos_uso import asistente
from contratacion.dominio.errores import Saturado
from contratacion.dominio.perfil_comercial import resumen_comercial
from contratacion.infraestructura.adaptadores.entrada.http.routers import asistente as ruta

PERFIL_COMPLETO: dict[str, Any] = {
    "razon_social": "Limpiezas del Valle S.A.",
    "ruc": "1790012345001",
    "cobertura": [{"provincia": "Guayas"}, {"provincia": "Pichincha"}],
    "palabras": [{"texto": "limpieza de oficinas"}],
    "ofertas": [{"nombre": "Desinfección", "descripcion": "Servicio CPC 85330 de desinfección"}],
    "experiencia": [{"objeto": "Limpieza hospital", "cpc": "853300011"}],
    "dedicaciones": [{"tipo_contratacion": "Servicio", "tipo_procedimiento": "Ínfima Cuantía"}],
    "presupuesto_max": 7000,
}


class PerfilCompleto:
    async def leer(self, negocio_id: Any) -> dict[str, Any]:
        return dict(PERFIL_COMPLETO)


class CpcVacio:
    """La lista de CPC del buscador, vaciada al limpiar los filtros."""

    async def listar(self, *, negocio_id: Any) -> tuple[Any, ...]:
        return ()


def _con_perfil_y_filtros_limpios() -> h.Servicios:
    piezas = servicios()
    piezas.perfil = cast(Any, PerfilCompleto())
    piezas.cpc = cast(Any, CpcVacio())
    return piezas


async def _enviar(texto: str, piezas: h.Servicios, modelo: ModeloFalso, **extra: Any) -> Any:
    return await asistente.enviar(
        ACTOR,
        texto=texto,
        conversacion_id=None,
        servicios=piezas,
        conversaciones=cast(Any, extra.pop("conversaciones", ConversacionesFalsas())),
        modelo=cast(Any, modelo),
        creditos=cast(Any, extra.pop("creditos", CreditosFalsos())),
        **extra,
    )


# --- 1. El perfil manda, no los filtros -------------------------------------------------------- #


def test_resumen_comercial_sale_del_perfil_aunque_la_lista_este_vacia() -> None:
    perfil = resumen_comercial(PERFIL_COMPLETO, [])
    assert perfil.tiene_datos
    assert "85330" in perfil.cpc and "853300011" in perfil.cpc
    assert perfil.palabras[:2] == ("limpieza de oficinas", "Desinfección")
    assert perfil.provincias == ("Guayas", "Pichincha")
    assert perfil.dedicaciones == ("Servicio · Ínfima Cuantía",)
    assert perfil.presupuesto == "$0 a $7,000"


def test_la_lista_del_buscador_suma_sin_repetir() -> None:
    perfil = resumen_comercial(PERFIL_COMPLETO, ["85330", "Limpieza de oficinas", "toallas"])
    assert perfil.cpc.count("85330") == 1
    assert [p.lower() for p in perfil.palabras].count("limpieza de oficinas") == 1
    assert "toallas" in perfil.palabras


def test_sin_perfil_ni_lista_no_hay_datos() -> None:
    assert not resumen_comercial({}, []).tiene_datos


async def test_con_filtros_limpios_el_modelo_recibe_el_perfil() -> None:
    modelo = ModeloFalso([{"content": "Vendes limpieza.", "tool_calls": []}])
    await _enviar(
        "¿Qué documentos necesito para lo que vendo?", _con_perfil_y_filtros_limpios(), modelo
    )
    sistema = modelo.llamadas[0][0]["content"]
    assert "CPC: ninguno" not in sistema
    assert "85330" in sistema and "limpieza de oficinas" in sistema
    assert "Guayas" in sistema and "Ínfima Cuantía" in sistema
    assert "no de los filtros" in sistema


async def test_datos_de_mi_empresa_muestran_los_cpc_del_perfil() -> None:
    resultado = await h.ejecutar(_con_perfil_y_filtros_limpios(), "datos_empresa", {})
    tarjeta = resultado.tarjetas[0]
    assert {c["codigo"] for c in tarjeta["cpc"]} >= {"85330", "853300011"}
    etiquetas = {c["etiqueta"]: c["valor"] for c in tarjeta["campos"]}
    assert "limpieza de oficinas" in etiquetas["Palabras clave comerciales"]
    assert "ninguno" not in resultado.resumen.split("CPC del perfil", 1)[1].split(".")[0]


# --- 3. Lo que no está adjudicado -------------------------------------------------------------- #


async def test_infimas_no_adjudicadas_por_el_camino_rapido_sin_cobrar() -> None:
    modelo = ModeloFalso([])
    creditos = CreditosFalsos(disponibles=2)
    respuesta = await _enviar("ínfimas no adjudicadas", servicios(), modelo, creditos=creditos)
    assert modelo.llamadas == []
    assert creditos.disponibles == 2
    mensaje = respuesta["mensajes"][1]
    tarjeta = mensaje["tarjetas"][0]
    assert tarjeta["tipo"] == "infimas"
    assert tarjeta["titulo"] == "Ínfimas sin adjudicar para tu empresa"
    assert "no publica" in tarjeta["nota"]
    assert "aún no están adjudicadas" in mensaje["texto"]
    assert "Procesos sin adjudicar" in mensaje["sugerencias"]


class ConsultasFalsas:
    def __init__(self, filas: list[dict[str, Any]]) -> None:
        self.filas = filas
        self.filtros: list[Any] = []

    async def buscar(self, filtros: Any) -> tuple[tuple[Mapping[str, Any], ...], int]:
        self.filtros.append(filtros)
        return tuple(self.filas), len(self.filas)


async def test_procesos_sin_adjudicar_descartan_los_que_tienen_proveedor() -> None:
    piezas = servicios()
    consultas = ConsultasFalsas(
        [
            {"id": uuid4(), "codigo": "SIE-A-2026-1", "objeto": "Sillas", "proveedor": "ACME"},
            {"id": uuid4(), "codigo": "SIE-B-2026-2", "objeto": "Mesas", "estado": "En curso"},
            {"id": uuid4(), "codigo": "SIE-C-2026-3", "objeto": "Toner", "estado": "Desierto"},
        ]
    )
    piezas.consultas = cast(Any, consultas)
    resultado = await h.ejecutar(piezas, "sin_adjudicar", {"tipo": "procesos", "para_mi": False})
    tarjeta = resultado.tarjetas[0]
    assert [e["codigo"] for e in tarjeta["elementos"]] == ["SIE-B-2026-2"]
    assert tarjeta["proforma"] is False
    assert consultas.filtros[0].fuentes_permitidas == ("OCDS",)
    assert "1 no tienen adjudicación publicada" in resultado.resumen


def test_validar_sin_adjudicar() -> None:
    assert h._validar_sin_adjudicar({}) == {
        "tipo": "infimas",
        "texto": "",
        "provincia": None,
        "para_mi": True,
    }
    limpio = h._validar_sin_adjudicar({"tipo": "raro", "texto": "sillas", "provincia": "guayas"})
    assert limpio["tipo"] == "infimas" and limpio["para_mi"] is False
    assert limpio["provincia"] == "Guayas"


def test_sin_adjudicar_se_ofrece_al_modelo() -> None:
    assert "sin_adjudicar" in {e["function"]["name"] for e in h.esquemas()}


# --- 4. Nada se queda colgado ------------------------------------------------------------------ #


class ModeloLento(ModeloFalso):
    async def conversar(self, mensajes: list[dict[str, Any]], *a: Any, **k: Any) -> Any:
        self.llamadas.append(mensajes)
        await asyncio.sleep(5)
        return {"content": "tarde", "tool_calls": []}


async def test_un_modelo_lento_se_corta_devuelve_el_credito_y_guarda_respuesta() -> None:
    creditos = CreditosFalsos(disponibles=3)
    conversaciones = ConversacionesFalsas()
    respuesta = await _enviar(
        "¿Qué documentos necesito?",
        servicios(),
        ModeloLento([]),
        creditos=creditos,
        conversaciones=conversaciones,
        tiempo_max_seg=0.05,
    )
    assert creditos.disponibles == 3 and creditos.devueltos == 1
    assert respuesta["creditos"]["gastados"] == 0
    mensaje = respuesta["mensajes"][1]
    assert "tardando demasiado" in mensaje["texto"]
    assert mensaje["sugerencias"]
    # El mensaje de la persona nunca queda sin respuesta guardada.
    guardados = next(iter(conversaciones.msgs.values()))
    assert [m["rol"] for m in guardados] == ["usuario", "asistente"]


class ModeloQueBuscaYSeDemora(ModeloFalso):
    async def conversar(self, mensajes: list[dict[str, Any]], *a: Any, **k: Any) -> Any:
        self.llamadas.append(mensajes)
        if len(self.llamadas) == 1:
            return _llamada("listar_alertas", {})
        await asyncio.sleep(5)
        return {"content": "tarde", "tool_calls": []}


async def test_si_se_agota_el_tiempo_se_muestra_lo_que_ya_se_encontro() -> None:
    respuesta = await _enviar(
        "¿Cómo voy con todo?", servicios(), ModeloQueBuscaYSeDemora([]), tiempo_max_seg=0.1
    )
    mensaje = respuesta["mensajes"][1]
    assert "esto es lo que alcancé a encontrar" in mensaje["texto"]
    assert mensaje["tarjetas"][0]["tipo"] == "alertas"
    assert respuesta["creditos"]["gastados"] == 0


async def test_un_fallo_inesperado_responde_y_devuelve_el_credito() -> None:
    creditos = CreditosFalsos(disponibles=3)
    respuesta = await _enviar(
        "¿Qué documentos necesito?",
        servicios(),
        ModeloFalso([RuntimeError("respuesta rara del proveedor")]),
        creditos=creditos,
    )
    assert creditos.disponibles == 3
    assert "Tuve un problema" in respuesta["mensajes"][1]["texto"]


async def test_llamadas_repetidas_no_dan_vueltas_hasta_el_tope() -> None:
    misma = _llamada("listar_alertas", {})
    modelo = ModeloFalso([misma, misma, {"content": "Tienes una alerta.", "tool_calls": []}])
    respuesta = await _enviar("¿Qué tal mis cosas?", servicios(), modelo)
    # 1.ª ejecuta, 2.ª repetida (no se ejecuta), 3.ª ya sin herramientas.
    assert len(modelo.llamadas) == 3
    assert respuesta["mensajes"][1]["texto"] == "Tienes una alerta."
    ultima = modelo.llamadas[1][-1]
    assert ultima["role"] == "tool"
    assert "Ya consultaste" in modelo.llamadas[2][-1]["content"]


class _Ajustes:
    asistente_max_rondas = 2
    asistente_tiempo_max_seg = 5.0


async def _ruta(texto: str, modelo: ModeloFalso) -> dict[str, Any]:
    return await ruta.mensaje(
        ruta.MensajeNuevo(texto=texto),
        ACTOR,
        cast(Any, _Ajustes()),
        servicios(),
        cast(Any, ConversacionesFalsas()),
        cast(Any, modelo),
        cast(Any, CreditosFalsos()),
        cast(Any, None),
    )


async def test_el_camino_rapido_no_hace_fila_en_el_encolador_de_ia(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lleno = encolador.Encolador("ia", en_paralelo=0, en_espera=0, espera_max_seg=1, por_empresa=1)
    monkeypatch.setitem(ruta.ENCOLADORES, "ia", lleno)
    respuesta = await _ruta("mis alertas", ModeloFalso([]))
    assert respuesta["mensajes"][1]["tarjetas"][0]["tipo"] == "alertas"
    # Lo que sí va al modelo respeta el encolador: lleno, se rechaza con 503 y nada se guarda.
    with pytest.raises(Saturado):
        await _ruta("¿Qué documentos necesito?", ModeloFalso([]))
