"""Pruebas del nombre de la cabecera de autorización.

Este archivo existe por un fallo real, y merece la pena contarlo porque es de los que pasan
desapercibidos durante semanas.

FastAPI convierte los guiones bajos del nombre de un parámetro en guiones al construir el
nombre de la cabecera. El parámetro se llamaba `autorizacion`, así que la cabecera que el
servidor esperaba era `autorizacion` —y **no** `Authorization`. Consecuencia: el inicio de
sesión respondía bien, porque no necesita cabecera, y a partir de ahí **todas** las peticiones
devolvían

    401 {"detail": "Falta la cabecera `Authorization` con un token de acceso válido."}

que es literalmente cierto y no dice nada sobre la causa. Cualquier cliente del mundo manda
`Authorization`, así que la API era inutilizable desde fuera mientras las pruebas de integración
pasaban: ninguna de ellas usaba un token, todas iban por el atajo de desarrollo con cabeceras
`X-Desarrollo-*`.

Las pruebas de aquí son de contrato: leen el esquema que la aplicación publica y comprueban que las
rutas esperan las cabeceras que se llaman de verdad así. No se necesita base de datos, porque el
esquema se genera leyendo las firmas de las rutas.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI

from contratacion.infraestructura.app import crear_app

# Cabeceras que la aplicación espera, en minúsculas porque es así como las publica el esquema.
# HTTP trata los nombres de cabecera **sin distinguir mayúsculas**, de modo que
# `X-Desarrollo-Usuario` y `x-desarrollo-usuario` son la misma cabecera y ahí no hay nada que
# corregir. Lo que sí son cabeceras distintas es `autorizacion` y `authorization`, y justo ahí
# estuvo el fallo: no era un problema de mayúsculas, sino de otra palabra.
CABECERAS_CONOCIDAS = frozenset(
    {
        "authorization",
        "user-agent",
        "x-forwarded-for",
        "x-desarrollo-usuario",
        "x-desarrollo-negocio",
        "x-desarrollo-rol",
    }
)

# El nombre que deben usar las rutas protegidas. Se comprueba aparte, y con la grafía exacta,
# porque es el que importa: es la cabecera que manda cualquier cliente HTTP.
CABECERA_DE_ACCESO = "Authorization"

# El nombre que salió por el olvido del alias. Se deja escrito para que la prueba explique el
# fallo en lugar de limitarse a mostrar una diferencia.
NOMBRE_QUE_FUE_UN_ERROR = "autorizacion"


@pytest.fixture(scope="module")
def esquema() -> dict[str, Any]:
    """Esquema OpenAPI de la aplicación, construido una vez para todo el módulo."""
    aplicacion: FastAPI = crear_app()
    return aplicacion.openapi()


def _cabeceras(esquema: dict[str, Any], ruta: str, metodo: str) -> set[str]:
    """Nombres de los parámetros de cabecera de una operación concreta."""
    return {
        str(parametro["name"])
        for parametro in esquema["paths"][ruta][metodo].get("parameters", [])
        if parametro.get("in") == "header"
    }


def _todas_las_cabeceras(esquema: dict[str, Any]) -> set[str]:
    """Nombres de todas las cabeceras declaradas en la aplicación."""
    nombres: set[str] = set()
    for metodos in esquema["paths"].values():
        for operacion in metodos.values():
            for parametro in operacion.get("parameters", []):
                if parametro.get("in") == "header":
                    nombres.add(str(parametro["name"]))
    return nombres


def test_la_ruta_de_consulta_de_sesion_espera_authorization(esquema: dict[str, Any]) -> None:
    """El caso que falló. `GET /v1/auth/sesion` es la comprobación más simple que existe."""
    assert CABECERA_DE_ACCESO in _cabeceras(esquema, "/v1/auth/sesion", "get")


def test_ninguna_ruta_espera_una_cabecera_desconocida(esquema: dict[str, Any]) -> None:
    """Recorre **todas** las operaciones y busca cabeceras que no sean las conocidas.

    Se hace sobre el esquema entero y no sobre una ruta concreta a propósito: el fallo se introdujo
    en una dependencia compartida, así que alcanzaba a todas las rutas protegidas. Comprobar una
    sola dejaría pasar la siguiente.

    La comparación no distingue mayúsculas, porque el esquema publica los nombres en minúsculas. Un
    nombre desconocido significa que su parámetro no llevó alias y que la cabecera resultante es la
    del nombre del parámetro, que no manda nadie.
    """
    desconocidas = {
        nombre
        for nombre in _todas_las_cabeceras(esquema)
        if nombre.lower() not in CABECERAS_CONOCIDAS
    }

    assert not desconocidas, (
        "Estas cabeceras no son las que manda un cliente, así que las rutas que las esperan no se "
        f"pueden autenticar desde fuera: {sorted(desconocidas)}. Si el nombre salió del parámetro "
        'sin alias, añade Header(alias="...") con el nombre real.'
    )


def test_la_cabecera_equivocada_no_vuelve(esquema: dict[str, Any]) -> None:
    """Deja el fallo concreto por escrito, para que la prueba explique qué pasó.

    Un nombre distinto en la misma palabra no se detecta ni por mayúsculas ni por guiones: es otra
    palabra, y por eso pasó desapercibido. Aquí queda dicho.
    """
    assert NOMBRE_QUE_FUE_UN_ERROR not in {
        nombre.lower() for nombre in _todas_las_cabeceras(esquema)
    }


def test_las_cabeceras_de_desarrollo_llevan_su_nombre(esquema: dict[str, Any]) -> None:
    """El atajo de desarrollo también debe pedir las cabeceras que manda quien lo usa."""
    presentes = {nombre.lower() for nombre in _cabeceras(esquema, "/v1/auth/sesion", "get")}
    assert {"x-desarrollo-usuario", "x-desarrollo-negocio"} <= presentes
