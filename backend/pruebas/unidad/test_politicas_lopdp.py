"""Pruebas de la adecuación a la LOPDP: dos textos obligatorios y su lectura pública.

Defienden tres cosas que no se ven en ninguna pantalla:

1. **Que aceptar un texto no abra la puerta mientras falte el otro.** Con un solo texto
   obligatorio, aceptar limpiaba el marcador de la cuenta sin más; con dos, eso dejaba entrar a
   quien solo había aceptado los términos.
2. **Que la huella que guarda la migración 0044 sea la que calcula el dominio**, igual que para
   las versiones anteriores: si se separaran, nadie podría aceptar nunca el texto publicado.
3. **Que la lectura pública sirva solo lo público**, sin cuenta y con freno por IP.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.casos_uso.consentimiento import aceptar
from contratacion.dominio.politicas import (
    POLITICAS_OBLIGATORIAS,
    POLITICAS_PUBLICAS,
    Consentimiento,
    Politica,
    TipoPolitica,
    huella_texto,
    pendientes,
)
from contratacion.infraestructura.adaptadores.entrada.http import proteccion
from contratacion.infraestructura.adaptadores.entrada.http.dependencias import (
    repositorio_politicas,
)
from contratacion.infraestructura.app import crear_app

AHORA = datetime(2026, 11, 13, 12, tzinfo=UTC)
MIGRACION = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0044_politicas_lopdp.py"


def _migracion() -> ModuleType:
    especificacion = importlib.util.spec_from_file_location("migracion_0044", MIGRACION)
    assert especificacion is not None and especificacion.loader is not None
    modulo = importlib.util.module_from_spec(especificacion)
    especificacion.loader.exec_module(modulo)
    return modulo


def _politica(tipo: TipoPolitica, version: int, texto: str) -> Politica:
    return Politica(
        tipo=tipo, version=version, texto=texto, hash=huella_texto(texto), vigente_desde=AHORA
    )


TERMINOS = _politica(TipoPolitica.TERMINOS_USO, 3, "términos tres")
PRIVACIDAD = _politica(TipoPolitica.TRATAMIENTO_DATOS, 1, "privacidad uno")


class PoliticasFalsas:
    def __init__(self, *publicadas: Politica) -> None:
        self._publicadas = {politica.tipo: politica for politica in publicadas}

    async def vigentes(self) -> Sequence[Politica]:
        return tuple(self._publicadas.values())

    async def vigente(self, tipo: TipoPolitica) -> Politica | None:
        return self._publicadas.get(tipo)


class ConsentimientosFalsos:
    def __init__(self) -> None:
        self.historial: list[Consentimiento] = []
        self.marcador: int | None = 3

    async def registrar(
        self, *, tipo: TipoPolitica, version: int, hash_texto: str, **_: Any
    ) -> UUID:
        self.historial.append(
            Consentimiento(tipo=tipo, version=version, hash_texto=hash_texto, aceptado_en=AHORA)
        )
        return uuid4()

    async def del_usuario(self, **_: Any) -> Sequence[Consentimiento]:
        return tuple(self.historial)

    async def marcar_pendiente(self, *, version: int, **_: Any) -> None:
        self.marcador = version

    async def limpiar_pendiente(self, **_: Any) -> None:
        self.marcador = None


class CuentasFalsas:
    async def auditar(self, **_: Any) -> None:
        return None


def _actor() -> Actor:
    return Actor(usuario_id=uuid4(), negocio_id=uuid4(), rol="admin_negocio")


async def _aceptar(
    politica: Politica, politicas: PoliticasFalsas, consentimientos: ConsentimientosFalsos
) -> None:
    await aceptar(
        _actor(),
        tipo=politica.tipo,
        version=politica.version,
        hash_texto=politica.hash,
        politicas=politicas,  # type: ignore[arg-type]
        consentimientos=consentimientos,  # type: ignore[arg-type]
        cuentas=CuentasFalsas(),  # type: ignore[arg-type]
        momento=AHORA,
    )


# --- Dominio ------------------------------------------------------------------------------------


def test_la_politica_de_privacidad_es_obligatoria_y_publica() -> None:
    assert POLITICAS_OBLIGATORIAS == (TipoPolitica.TERMINOS_USO, TipoPolitica.TRATAMIENTO_DATOS)
    assert set(POLITICAS_PUBLICAS) == set(POLITICAS_OBLIGATORIAS)


def test_aceptar_solo_los_terminos_deja_pendiente_la_privacidad() -> None:
    aceptadas = (
        Consentimiento(tipo=TERMINOS.tipo, version=3, hash_texto=TERMINOS.hash, aceptado_en=AHORA),
    )
    resultado = pendientes(publicadas=(TERMINOS, PRIVACIDAD), aceptadas=aceptadas)
    assert resultado.tipos == (TipoPolitica.TRATAMIENTO_DATOS,)


# --- Caso de uso --------------------------------------------------------------------------------


async def test_aceptar_un_texto_no_levanta_el_bloqueo_si_falta_el_otro() -> None:
    politicas = PoliticasFalsas(TERMINOS, PRIVACIDAD)
    consentimientos = ConsentimientosFalsos()

    await _aceptar(TERMINOS, politicas, consentimientos)

    assert consentimientos.marcador is not None


async def test_aceptar_los_dos_textos_levanta_el_bloqueo() -> None:
    politicas = PoliticasFalsas(TERMINOS, PRIVACIDAD)
    consentimientos = ConsentimientosFalsos()

    await _aceptar(TERMINOS, politicas, consentimientos)
    await _aceptar(PRIVACIDAD, politicas, consentimientos)

    assert consentimientos.marcador is None


# --- Migración ----------------------------------------------------------------------------------


def test_la_migracion_guarda_la_huella_que_calcula_el_dominio() -> None:
    migracion = _migracion()
    for tipo, _version, texto in migracion.PUBLICACIONES:
        TipoPolitica(tipo)  # el tipo existe en el dominio
        assert migracion._huella(texto) == huella_texto(texto)


def test_la_migracion_publica_las_dos_politicas_obligatorias() -> None:
    migracion = _migracion()
    publicadas = {(tipo, version) for tipo, version, _ in migracion.PUBLICACIONES}
    assert publicadas == {("terminos_uso", 3), ("tratamiento_datos", 1)}
    assert migracion.down_revision == "0043"


def test_la_migracion_no_publica_marcadores_en_produccion(monkeypatch: pytest.MonkeyPatch) -> None:
    migracion = _migracion()
    monkeypatch.setattr(migracion, "_es_produccion", lambda: True)
    monkeypatch.setattr(migracion, "PUBLICACIONES", (("terminos_uso", 3, "Responsable: «[RUC]»"),))
    # No publica, pero tampoco tumba el deploy (el arranque es `alembic upgrade head && uvicorn`).
    assert migracion._faltan_datos_en_produccion() is True


def test_fuera_de_produccion_la_migracion_admite_marcadores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migracion = _migracion()
    monkeypatch.setattr(migracion, "_es_produccion", lambda: False)
    monkeypatch.setattr(migracion, "PUBLICACIONES", (("terminos_uso", 3, "Responsable: «[RUC]»"),))
    assert migracion._faltan_datos_en_produccion() is False


# --- Lectura pública ----------------------------------------------------------------------------


@pytest.fixture
def cliente() -> TestClient:
    aplicacion = crear_app()
    aplicacion.dependency_overrides[repositorio_politicas] = lambda: PoliticasFalsas(
        TERMINOS, PRIVACIDAD, _politica(TipoPolitica.AVISO_PRIVACIDAD, 1, "aviso")
    )
    return TestClient(aplicacion)


@pytest.mark.parametrize("politica", [TERMINOS, PRIVACIDAD])
def test_la_lectura_publica_no_pide_cuenta(cliente: TestClient, politica: Politica) -> None:
    respuesta = cliente.get(f"/v1/politicas/publicas/{politica.tipo}")

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["tipo"] == str(politica.tipo)
    assert cuerpo["version"] == politica.version
    assert cuerpo["texto"] == politica.texto
    assert cuerpo["titulo"] == politica.titulo
    assert cuerpo["vigente_desde"].startswith("2026-11-13")


def test_la_lectura_publica_no_sirve_textos_que_no_son_publicos(cliente: TestClient) -> None:
    assert cliente.get("/v1/politicas/publicas/aviso_privacidad").status_code == 404


def test_la_lectura_publica_rechaza_tipos_desconocidos(cliente: TestClient) -> None:
    assert cliente.get("/v1/politicas/publicas/inventado").status_code == 422


def test_la_lectura_publica_tiene_freno_por_ip() -> None:
    for tipo in POLITICAS_PUBLICAS:
        assert ("GET", f"/v1/politicas/publicas/{tipo}") in proteccion._LIMITES
