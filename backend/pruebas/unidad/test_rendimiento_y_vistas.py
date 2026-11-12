"""Rendimiento, concurrencia y vistas ocultas (docs/39-rendimiento-y-concurrencia.md).

Lo que se comprueba:

- Una vista oculta por el superadministrador no se filtra por el asistente: ni por el camino rápido,
  ni por las herramientas que se ofrecen al modelo, ni por las sugerencias, ni por el inicio.
- La vista previa de una alerta solo cuenta y enseña procesos de las fuentes visibles.
- El inicio del asistente no ocupa más de `PARALELO_INICIO` conexiones a la vez y lee el perfil una
  sola vez por petición.
- Las memorias en proceso están acotadas (LRU) y la revisión de alertas escribe sus avisos juntos.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from pruebas.unidad.test_asistente import (
    ACTOR,
    ConversacionesFalsas,
    CreditosFalsos,
    HistorialFalso,
    ModeloFalso,
    RadarFalso,
    SriFalso,
    UsuariosFalsos,
    servicios,
)

from contratacion.aplicacion.asistente import herramientas as h
from contratacion.aplicacion.asistente.recordados import CpcRecordado, PerfilRecordado
from contratacion.aplicacion.casos_uso import asistente, revisar_alertas
from contratacion.aplicacion.hilos import MemoLru
from contratacion.dominio.acceso import Vista
from contratacion.infraestructura.adaptadores.salida.bd.sesion import parametros_de_sesion

SOLO_OFERTAS = frozenset({Vista.OFERTAS})
SOLO_INFIMAS = frozenset({Vista.NECESIDADES})
SIN_DATOS = frozenset({Vista.GRAFICAS})


def _con_vistas(vistas: frozenset[Vista]) -> h.Servicios:
    piezas = servicios()
    piezas.vistas = vistas
    return piezas


# --- Asistente y vistas ------------------------------------------------------------------------- #


async def test_sin_vista_de_infimas_el_chat_no_las_busca_ni_las_recomienda() -> None:
    piezas = _con_vistas(SOLO_OFERTAS)
    for nombre, argumentos in (
        ("buscar_infimas", {"texto": "impresoras"}),
        ("propuestas_para_ti", {}),
    ):
        resultado = await h.ejecutar(piezas, nombre, argumentos)
        assert resultado.tarjetas == []
        assert "no tiene acceso" in resultado.resumen


async def test_sin_vista_de_ofertas_no_hay_historial_precios_ni_competidores() -> None:
    piezas = _con_vistas(SOLO_INFIMAS)
    piezas.sri = cast(Any, SriFalso())
    piezas.historial = cast(Any, HistorialFalso())
    for nombre, argumentos in (
        ("historial_ruc", {"ruc": "1790012345001"}),
        ("precio_referencia", {"texto_o_cpc": "impresoras"}),
        ("competidores", {"texto_o_cpc": "impresoras"}),
    ):
        resultado = await h.ejecutar(piezas, nombre, argumentos)
        assert resultado.tarjetas == [], nombre
        assert "no tiene acceso" in resultado.resumen, nombre


async def test_lo_propio_de_la_empresa_no_depende_de_las_vistas() -> None:
    piezas = _con_vistas(SIN_DATOS)
    datos = await h.ejecutar(piezas, "datos_empresa", {})
    ofertas = await h.ejecutar(piezas, "mis_ofertas", {})
    assert datos.tarjetas and ofertas.tarjetas


def test_al_modelo_solo_se_le_ofrecen_las_herramientas_de_sus_vistas() -> None:
    def nombres(vistas: frozenset[Vista]) -> set[str]:
        return {e["function"]["name"] for e in h.esquemas(vistas)}

    solo_ofertas = nombres(SOLO_OFERTAS)
    assert "buscar_infimas" not in solo_ofertas
    assert "propuestas_para_ti" not in solo_ofertas
    assert {"precio_referencia", "competidores", "historial_ruc"} <= solo_ofertas

    solo_infimas = nombres(SOLO_INFIMAS)
    assert {"precio_referencia", "competidores", "historial_ruc"}.isdisjoint(solo_infimas)
    assert {"buscar_infimas", "propuestas_para_ti", "estado_proceso"} <= solo_infimas

    sin_datos = nombres(SIN_DATOS)
    assert sin_datos == {"datos_empresa", "listar_alertas", "mis_ofertas", "consultar_ruc"}
    # Sin vistas (llamada antigua) se ofrecen todas.
    assert len(h.esquemas()) == len(h.HERRAMIENTAS)


async def test_el_modelo_no_recibe_herramientas_de_vistas_ocultas() -> None:
    piezas = _con_vistas(SOLO_OFERTAS)
    respuesta: list[Any] = []

    class ModeloQueMira(ModeloFalso):
        async def conversar(self, mensajes: Any, herramientas: Any = None, **kw: Any) -> Any:
            respuesta.append(herramientas)
            return await super().conversar(mensajes, herramientas, **kw)

    modelo = ModeloQueMira([{"content": "Hola."}])
    await asistente.enviar(
        ACTOR,
        texto="¿qué me conviene vender este mes al estado?",
        conversacion_id=None,
        servicios=piezas,
        conversaciones=cast(Any, ConversacionesFalsas()),
        modelo=cast(Any, modelo),
        creditos=cast(Any, CreditosFalsos()),
    )
    ofrecidas = {e["function"]["name"] for e in respuesta[0]}
    assert "buscar_infimas" not in ofrecidas and "propuestas_para_ti" not in ofrecidas


async def test_las_sugerencias_no_llevan_a_una_vista_oculta() -> None:
    piezas = _con_vistas(SOLO_OFERTAS)
    datos = await asistente.inicio(
        ACTOR,
        servicios=piezas,
        conversaciones=cast(Any, ConversacionesFalsas()),
        modelo=cast(Any, ModeloFalso([])),
        creditos=cast(Any, CreditosFalsos()),
        usuarios=cast(Any, UsuariosFalsos()),
    )
    assert "Recomiéndame ínfimas" not in datos["sugerencias"]
    assert "Mis ofertas" in datos["sugerencias"]
    # Sin la vista no se calcula el contador (ni se registra como fallo).
    assert datos["resumen"]["propuestas"] is None

    salida = await asistente.enviar(
        ACTOR,
        texto="mis alertas",
        conversacion_id=None,
        servicios=piezas,
        conversaciones=cast(Any, ConversacionesFalsas()),
        modelo=cast(Any, ModeloFalso([])),
        creditos=cast(Any, CreditosFalsos()),
    )
    sugeridas = salida["mensajes"][1]["sugerencias"]
    assert sugeridas and "Recomiéndame ínfimas" not in sugeridas


def test_sugerencia_permitida_sigue_la_regla_de_cada_herramienta() -> None:
    assert asistente.sugerencia_permitida("Recomiéndame ínfimas", SOLO_INFIMAS)
    assert not asistente.sugerencia_permitida("Recomiéndame ínfimas", SOLO_OFERTAS)
    assert asistente.sugerencia_permitida("Datos de mi empresa", SIN_DATOS)
    assert asistente.sugerencia_permitida("Mis ofertas", SIN_DATOS)


# --- Inicio: conexiones y lecturas -------------------------------------------------------------- #


async def test_el_inicio_no_ocupa_mas_de_dos_conexiones_a_la_vez() -> None:
    en_curso = 0
    maximo = 0

    async def medir() -> None:
        nonlocal en_curso, maximo
        en_curso += 1
        maximo = max(maximo, en_curso)
        await asyncio.sleep(0.01)
        en_curso -= 1

    class Lento:
        def __init__(self, interno: Any) -> None:
            self._interno = interno

        def __getattr__(self, nombre: str) -> Any:
            original = getattr(self._interno, nombre)

            async def envoltura(*args: Any, **kwargs: Any) -> Any:
                await medir()
                return await original(*args, **kwargs)

            return envoltura

    piezas = servicios()
    piezas.perfil = cast(Any, Lento(piezas.perfil))
    piezas.alertas = cast(Any, Lento(piezas.alertas))
    piezas.seguimiento = cast(Any, Lento(piezas.seguimiento))
    await asistente.inicio(
        ACTOR,
        servicios=piezas,
        conversaciones=cast(Any, Lento(ConversacionesFalsas())),
        modelo=cast(Any, ModeloFalso([])),
        creditos=cast(Any, Lento(CreditosFalsos())),
        usuarios=cast(Any, Lento(UsuariosFalsos())),
    )
    assert 1 <= maximo <= asistente.PARALELO_INICIO


async def test_el_perfil_se_lee_una_vez_por_peticion_aunque_lo_pidan_a_la_vez() -> None:
    lecturas: list[UUID] = []

    class Perfil:
        async def leer(self, negocio_id: UUID) -> dict[str, Any]:
            lecturas.append(negocio_id)
            await asyncio.sleep(0.01)
            return {"nombre": "Andinos"}

    recordado = PerfilRecordado(cast(Any, Perfil()))
    negocio = uuid4()
    primero, segundo = await asyncio.gather(recordado.leer(negocio), recordado.leer(negocio))
    assert primero == segundo == {"nombre": "Andinos"}
    assert lecturas == [negocio]
    # Lo que se devuelve es una copia: tocarlo no cambia lo recordado.
    primero["nombre"] = "otro"
    assert (await recordado.leer(negocio))["nombre"] == "Andinos"


async def test_la_lista_de_cpc_se_olvida_al_escribir() -> None:
    llamadas = 0

    class Cpc:
        async def listar(self, *, negocio_id: UUID) -> tuple[Any, ...]:
            nonlocal llamadas
            llamadas += 1
            return ()

        async def limpiar(self, *, negocio_id: UUID) -> int:
            return 0

    recordado = CpcRecordado(cast(Any, Cpc()))
    negocio = uuid4()
    await recordado.listar(negocio_id=negocio)
    await recordado.listar(negocio_id=negocio)
    await recordado.limpiar(negocio_id=negocio)
    await recordado.listar(negocio_id=negocio)
    assert llamadas == 2


# --- Alertas ------------------------------------------------------------------------------------ #


class RadarDeFuentes:
    def __init__(self) -> None:
        self.fuentes_pedidas: list[tuple[str, ...]] = []
        self.lotes: list[list[dict[str, Any]]] = []

    async def candidatos(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.fuentes_pedidas.append(tuple(kwargs["fuentes"]))
        return [
            {
                "id": uuid4(),
                "fuente": fuente,
                "codigo": f"{fuente}-1",
                "objeto": "Mantenimiento de impresoras",
                "entidad": "GAD",
                "provincia": "Pichincha",
                "canton": "",
                "cpc_codigos": [],
                "presupuesto": 500.0,
                "plazo": None,
                "texto": "mantenimiento de impresoras",
            }
            for fuente in kwargs["fuentes"]
        ]

    async def crear_avisos(self, avisos: list[dict[str, Any]]) -> int:
        self.lotes.append(avisos)
        return len(avisos)


async def test_la_vista_previa_de_una_alerta_solo_mira_las_fuentes_visibles() -> None:
    radar = RadarDeFuentes()
    alerta: dict[str, Any] = {"palabras": ["impresoras"], "provincia": "Pichincha"}
    solo_nco = await revisar_alertas.previsualizar_alerta(
        cast(Any, radar), {**alerta, "presupuesto_max": 501}, fuentes=("NCO",)
    )
    assert radar.fuentes_pedidas[-1] == ("NCO",)
    assert set(solo_nco["por_fuente"]) == {"NCO"}

    nada = await revisar_alertas.previsualizar_alerta(cast(Any, radar), alerta, fuentes=())
    assert nada["total"] == 0 and nada["muestras"] == []


async def test_la_revision_deja_los_avisos_en_un_solo_lote() -> None:
    radar = RadarDeFuentes()
    await revisar_alertas._una(
        cast(Any, radar),
        {
            "id": uuid4(),
            "negocio_id": uuid4(),
            "usuario_id": uuid4(),
            "palabras": ["impresoras"],
            "revisada_en": None,
        },
        datetime.now(UTC),
    )
    assert len(radar.lotes) == 1
    assert len(radar.lotes[0]) == 2


async def test_crear_alerta_desde_el_chat_cuenta_solo_lo_visible() -> None:
    radar = RadarFalso()
    vistas_pedidas: list[Any] = []

    async def candidatos(**kwargs: Any) -> list[dict[str, Any]]:
        vistas_pedidas.append(tuple(kwargs["fuentes"]))
        return []

    radar.candidatos = candidatos  # type: ignore[method-assign]
    piezas = servicios(radar)
    piezas.vistas = SOLO_OFERTAS
    await h.ejecutar(
        piezas, "crear_alerta", {"palabras": [f"tornillos-{uuid4().hex[:6]}"], "nombre": "x"}
    )
    assert vistas_pedidas == [("OCDS",)]


# --- Memorias y conexiones ---------------------------------------------------------------------- #


def test_la_memoria_lru_olvida_la_menos_usada_y_no_todo() -> None:
    memo: MemoLru[str, int] = MemoLru(3)
    memo["a"] = 1
    memo["b"] = 2
    memo["c"] = 3
    assert memo.get("a") == 1  # «a» pasa a ser la más reciente
    memo["d"] = 4
    assert list(memo) == ["c", "a", "d"]
    assert memo.get("b") is None
    assert len(memo) == 3


def test_los_topes_de_postgres_viajan_al_abrir_la_conexion() -> None:
    assert parametros_de_sesion(statement_timeout_ms=30_000, idle_tx_timeout_ms=60_000) == {
        "application_name": "cercoapp-api",
        "statement_timeout": "30000",
        "idle_in_transaction_session_timeout": "60000",
    }
    # El worker los pone a cero: solo viaja el nombre.
    assert parametros_de_sesion(
        statement_timeout_ms=0, idle_tx_timeout_ms=0, nombre="cercoapp-worker"
    ) == {"application_name": "cercoapp-worker"}


# --- TDR de un proceso de una vista oculta ------------------------------------------------------ #


async def test_los_tdr_de_una_infima_piden_la_vista_de_infimas() -> None:
    import pytest

    from contratacion.dominio.errores import SinPermiso
    from contratacion.infraestructura.adaptadores.entrada.http.routers.tdr import (
        exigir_vista_del_proceso,
    )

    class TdrFalso:
        async def fuente_de(self, registro_id: UUID) -> str | None:
            return "NCO"

    with pytest.raises(SinPermiso):
        await exigir_vista_del_proceso(uuid4(), SOLO_OFERTAS, cast(Any, TdrFalso()))
    await exigir_vista_del_proceso(uuid4(), SOLO_INFIMAS, cast(Any, TdrFalso()))

    class TdrSinProceso:
        async def fuente_de(self, registro_id: UUID) -> str | None:
            return None

    # Un proceso que no existe se deja pasar: la ruta responde 404 por su cuenta.
    await exigir_vista_del_proceso(uuid4(), SIN_DATOS, cast(Any, TdrSinProceso()))
