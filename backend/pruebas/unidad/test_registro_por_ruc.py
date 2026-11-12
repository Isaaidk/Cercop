"""El registro empieza por el RUC: lo que el SRI publica deja el perfil de la empresa listo.

Lo que se comprueba aquí es lo que llega de un formulario abierto: que solo se siembra lo que el SRI
publica, recortado y sin duplicados, y que un dato mal formado se descarta sin tumbar el registro.
"""

from __future__ import annotations

from datetime import date
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from contratacion.aplicacion.casos_uso.gestionar_perfil import (
    consultar_ruc_publico,
    sembrar_perfil,
)
from contratacion.dominio.errores import DatoInvalido
from contratacion.infraestructura.adaptadores.entrada.http import proteccion
from contratacion.infraestructura.adaptadores.salida.bd.perfil import RepositorioPerfil
from contratacion.infraestructura.adaptadores.salida.sri import ConsultaSri


class PerfilEspia:
    def __init__(self) -> None:
        self.identidad: dict[str, Any] = {}
        self.filas: list[tuple[str, dict[str, Any]]] = []

    async def guardar_identidad(self, negocio_id: UUID, campos: dict[str, Any]) -> None:
        self.identidad.update(campos)

    async def agregar(
        self, negocio_id: UUID, coleccion: str, campos: dict[str, Any]
    ) -> dict[str, Any]:
        self.filas.append((coleccion, campos))
        return campos


async def test_siembra_identidad_representante_cobertura_y_actividad() -> None:
    espia = PerfilEspia()
    await sembrar_perfil(
        uuid4(),
        repositorio=cast(RepositorioPerfil, espia),
        propuesta={
            "identidad": {
                "razon_social": "  CONSTRUCTORA DEL PACIFICO CIA. LTDA. ",
                "tipo_persona": "juridica",
                "obligado_contabilidad": True,
                "fecha_inicio_actividades": "2015-03-02",
                "ciudad": "Quito",
                # Lo que no está en la lista blanca no se siembra, aunque venga.
                "estado_rup": "habilitado",
                "ruc": "1790012344001",
            },
            "representante": {"nombre": "Ana Pérez", "cedula": "1712345678"},
            "cobertura": [
                {"provincia": "Pichincha", "canton": "Quito"},
                {"provincia": "Pichincha", "canton": "Quito"},
                {"provincia": "", "canton": "X"},
            ],
            "actividad": "Construcción de edificios",
        },
    )

    assert espia.identidad == {
        "razon_social": "CONSTRUCTORA DEL PACIFICO CIA. LTDA.",
        "tipo_persona": "juridica",
        "obligado_contabilidad": True,
        "fecha_inicio_actividades": date(2015, 3, 2),
        "ciudad": "Quito",
    }
    colecciones = [coleccion for coleccion, _ in espia.filas]
    assert colecciones == ["contactos", "cobertura", "actividades"]
    contacto = espia.filas[0][1]
    assert contacto["tipo"] == "representante_legal"
    assert contacto["cargo"] == "Representante legal"
    assert contacto["principal"] is True


async def test_un_dato_mal_formado_se_descarta_sin_fallar() -> None:
    espia = PerfilEspia()
    await sembrar_perfil(
        uuid4(),
        repositorio=cast(RepositorioPerfil, espia),
        propuesta={
            "identidad": {
                "tipo_persona": "marciana",
                "fecha_inicio_actividades": "ayer",
                "razon_social": "x" * 1000,
            },
        },
    )

    assert set(espia.identidad) == {"razon_social"}
    assert len(espia.identidad["razon_social"]) == 300
    assert espia.filas == []


async def test_la_consulta_publica_valida_el_ruc_antes_de_llamar_al_sri() -> None:
    class SriProhibido:
        async def consultar(self, ruc: str) -> Any:
            raise AssertionError("no debe llegar al SRI con un RUC mal formado")

    with pytest.raises(DatoInvalido):
        await consultar_ruc_publico("1234567890000", sri=cast(ConsultaSri, SriProhibido()))


def test_el_alta_y_la_consulta_publica_tienen_freno_por_ip() -> None:
    """La clave del freno era `/v1/registro`, que no es ninguna ruta: el alta no tenía freno."""
    assert ("POST", "/v1/registro/empresa") in proteccion._LIMITES
    assert ("POST", "/v1/registro/consulta-ruc") in proteccion._LIMITES


async def test_siembra_la_experiencia_de_los_datos_abiertos() -> None:
    espia = PerfilEspia()
    await sembrar_perfil(
        uuid4(),
        repositorio=cast(RepositorioPerfil, espia),
        propuesta={
            "experiencia": [
                {
                    "entidad": "GAD Quito",
                    "objeto": "Mantenimiento",
                    "monto": 5000.0,
                    "anio": 2025,
                    "cpc": "871500011",
                    "tipo_contratacion": "servicios",
                },
                {"entidad": "", "objeto": "sin entidad: se descarta"},
                {"entidad": "Otra", "anio": 1700, "tipo_contratacion": "marciana"},
            ]
        },
    )

    filas = [campos for coleccion, campos in espia.filas if coleccion == "experiencia"]
    assert len(filas) == 2
    assert filas[0]["tipo_contratacion"] == "servicios"
    assert "anio" not in filas[1] and "tipo_contratacion" not in filas[1]


async def test_siembra_los_cpc_sin_repetir() -> None:
    from contratacion.aplicacion.casos_uso.gestionar_cpc import sembrar_cpc

    class CpcEspia:
        def __init__(self) -> None:
            self.textos: list[str] = []

        async def agregar(self, **kwargs: Any) -> bool:
            self.textos.append(kwargs["texto"])
            return True

    espia = CpcEspia()
    agregados = await sembrar_cpc(
        negocio_id=uuid4(),
        usuario_id=uuid4(),
        textos=["871500011", "871500011", "45230"],
        repositorio=espia,  # type: ignore[arg-type]
    )

    assert agregados == 2
    assert espia.textos == ["871500011", "45230"]


async def test_una_ip_exenta_no_pasa_por_el_freno() -> None:
    from types import SimpleNamespace

    from fastapi import Response

    proteger = proteccion.crear_proteccion(produccion=False, exentas=frozenset({"10.0.0.9"}))

    async def siguiente(_: Any) -> Response:
        return Response("ok")

    def peticion(ip: str) -> Any:
        return SimpleNamespace(
            method="POST",
            url=SimpleNamespace(path="/v1/registro/empresa"),
            client=SimpleNamespace(host=ip),
        )

    exenta = [(await proteger(peticion("10.0.0.9"), siguiente)).status_code for _ in range(8)]
    otra = [(await proteger(peticion("10.0.0.1"), siguiente)).status_code for _ in range(8)]

    assert set(exenta) == {200}
    assert 429 in otra
