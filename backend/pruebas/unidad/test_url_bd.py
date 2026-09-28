"""Pruebas de la normalización de la URI de base de datos.

Aceptar sin retoques la URI que entrega un proveedor gestionado es lo que permite cumplir el
requisito RNF-12 («cambiar de base local a remota cambiando `DATABASE_URL`»).

No abren ninguna conexión: solo construyen y examinan la URL.
"""

from __future__ import annotations

import pytest

from contratacion.infraestructura.adaptadores.salida.bd.sesion import normalizar_url_bd

REMOTA = "postgresql://usuario:clave@aws-0-region.pooler.supabase.com:5432/postgres"
LOCAL = "postgresql://usuario:clave@localhost:5432/contratacion"


def test_anade_el_controlador_asincrono() -> None:
    assert normalizar_url_bd(REMOTA).drivername == "postgresql+asyncpg"


def test_acepta_el_alias_postgres() -> None:
    destino = "postgres://usuario:clave@aws-0-region.pooler.supabase.com:5432/postgres"
    assert normalizar_url_bd(destino).drivername == "postgresql+asyncpg"


def test_activa_tls_en_host_remoto() -> None:
    assert normalizar_url_bd(REMOTA).query.get("ssl") == "require"


def test_no_activa_tls_en_host_local() -> None:
    assert "ssl" not in normalizar_url_bd(LOCAL).query


def test_respeta_el_cifrado_indicado_por_el_usuario() -> None:
    destino = f"{REMOTA}?ssl=disable"
    assert normalizar_url_bd(destino).query.get("ssl") == "disable"


def test_una_url_ya_adaptada_no_se_altera() -> None:
    url = normalizar_url_bd("postgresql+asyncpg://u:c@127.0.0.1:5432/p")
    assert url.drivername == "postgresql+asyncpg"
    assert "ssl" not in url.query


def test_conserva_los_parametros_del_usuario() -> None:
    destino = f"{REMOTA}?prepared_statement_cache_size=0"
    assert normalizar_url_bd(destino).query.get("prepared_statement_cache_size") == "0"


def test_controlador_no_soportado_falla() -> None:
    with pytest.raises(ValueError, match="Controlador no soportado"):
        normalizar_url_bd("mysql://usuario:clave@localhost:3306/contratacion")
