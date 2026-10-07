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
# Las dos formas de llamar a la base **dentro** de una red privada: el servicio del `compose`
# (`deploy/`) se llama `bd` a secas, y en Railway la base se resolvió como
# `postgres.railway.internal` aunque la tarjeta del servicio se llamara `bd`.
DEL_COMPOSE = "postgresql://usuario:clave@bd:5432/contratacion"
DE_RAILWAY = "postgresql://usuario:clave@postgres.railway.internal:5432/contratacion"


def test_anade_el_controlador_asincrono() -> None:
    assert normalizar_url_bd(REMOTA).drivername == "postgresql+asyncpg"


def test_acepta_el_alias_postgres() -> None:
    destino = "postgres://usuario:clave@aws-0-region.pooler.supabase.com:5432/postgres"
    assert normalizar_url_bd(destino).drivername == "postgresql+asyncpg"


def test_activa_tls_en_host_remoto() -> None:
    assert normalizar_url_bd(REMOTA).query.get("ssl") == "require"


def test_no_activa_tls_en_host_local() -> None:
    assert "ssl" not in normalizar_url_bd(LOCAL).query


@pytest.mark.parametrize("destino", [DEL_COMPOSE, DE_RAILWAY])
def test_no_activa_tls_dentro_de_una_red_privada(destino: str) -> None:
    """El fallo que costó el despliegue en Railway: la base estaba viva y el cifrado lo impedía.

    Ninguno de los dos servidores tiene certificado, así que pedir TLS no protege nada y hace que
    la conexión se caiga con «rejected SSL upgrade». El del `compose` es el mismo caso: su
    PostgreSQL se llama `bd` y tampoco habla TLS.
    """
    assert "ssl" not in normalizar_url_bd(destino).query


def test_reconoce_un_sufijo_privado_por_el_final() -> None:
    destino = "postgresql://usuario:clave@base.svc.cluster.local:5432/contratacion"
    assert "ssl" not in normalizar_url_bd(destino).query


def test_una_ipv6_literal_sigue_siendo_remota() -> None:
    """De pedir cifrado de más se sale con `?ssl=disable`; de pedir de menos, no tan fácil."""
    destino = "postgresql://usuario:clave@[2001:db8::1]:5432/contratacion"
    assert normalizar_url_bd(destino).query.get("ssl") == "require"


def test_se_puede_forzar_el_cifrado_en_una_red_privada() -> None:
    assert normalizar_url_bd(f"{DE_RAILWAY}?ssl=require").query.get("ssl") == "require"


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
