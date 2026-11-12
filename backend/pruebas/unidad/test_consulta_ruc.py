"""El RUC llena una propuesta de perfil; el SRI se simula, nunca se llama de verdad."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.casos_uso.gestionar_perfil import _fecha, consultar_ruc
from contratacion.dominio.consulta_ruc import propuesta_desde_sri
from contratacion.dominio.errores import DatoInvalido, EstadoInvalido, NoEncontrado, SinPermiso
from contratacion.infraestructura.adaptadores.salida.sri import ConsultaSri

CONTRIBUYENTE = {
    "numeroRuc": "1792146739001",
    "razonSocial": "SUMINISTROS ANDINOS S.A.",
    "estadoContribuyenteRuc": "ACTIVO",
    "actividadEconomicaPrincipal": "VENTA AL POR MAYOR DE MAQUINARIA.",
    "tipoContribuyente": "SOCIEDAD",
    "regimen": "GENERAL",
    "categoria": None,
    "obligadoLlevarContabilidad": "SI",
    "informacionFechasContribuyente": {"fechaInicioActividades": "2016-03-14 00:00:00.0"},
    "representantesLegales": [
        {"identificacion": "1712345678", "nombre": "PEREZ ANDRADE ISAAC"},
    ],
    "contribuyenteFantasma": "NO",
    "transaccionesInexistente": "NO",
}
ESTABLECIMIENTOS = [
    {
        "nombreFantasiaComercial": "ANDINOS OFICINA",
        "direccionCompleta": "PICHINCHA / QUITO / IÑAQUITO / AV. AMAZONAS N31-120",
        "estado": "ABIERTO",
        "matriz": "SI",
    },
    {
        "direccionCompleta": "GUAYAS / GUAYAQUIL / TARQUI / AV. 9 DE OCTUBRE 100",
        "estado": "ABIERTO",
        "matriz": "NO",
    },
    {
        "direccionCompleta": "AZUAY / CUENCA / SUCRE / CALLE LARGA 5",
        "estado": "CERRADO",
        "matriz": "NO",
    },
]


def _sri(contribuyentes: object, establecimientos: object = None, estado: int = 200) -> ConsultaSri:
    def responder(peticion: httpx.Request) -> httpx.Response:
        ruta = peticion.url.path
        cuerpo = contribuyentes if "Consolidado" in ruta else (establecimientos or [])
        return httpx.Response(estado, content=json.dumps(cuerpo))

    return ConsultaSri(transporte=httpx.MockTransport(responder))


def test_la_propuesta_llena_lo_que_el_sri_publica() -> None:
    propuesta = propuesta_desde_sri(CONTRIBUYENTE, ESTABLECIMIENTOS)
    identidad = propuesta["identidad"]
    assert identidad["razon_social"] == "SUMINISTROS ANDINOS S.A."
    assert identidad["nombre_comercial"] == "Andinos Oficina"
    assert identidad["tipo_persona"] == "juridica"
    assert identidad["regimen_tributario"] == "General"
    assert identidad["obligado_contabilidad"] is True
    assert identidad["fecha_inicio_actividades"] == "2016-03-14"
    assert identidad["ciudad"] == "Quito"
    assert identidad["direccion"].startswith("Av. Amazonas")
    assert propuesta["representante"]["cedula"] == "1712345678"
    assert propuesta["representante"]["tipo"] == "representante_legal"
    # Solo los establecimientos abiertos dan cobertura.
    assert propuesta["cobertura"] == [
        {"provincia": "Pichincha", "canton": "Quito"},
        {"provincia": "Guayas", "canton": "Guayaquil"},
    ]
    assert "Correo" in propuesta["no_publica"]
    assert propuesta["avisos"] == []


def test_las_provincias_sin_tilde_salen_con_la_grafia_oficial() -> None:
    propuesta = propuesta_desde_sri(
        CONTRIBUYENTE,
        [
            {"direccionCompleta": "MANABI / PORTOVIEJO / X / CALLE 1", "estado": "ABIERTO"},
            {
                "direccionCompleta": "SANTO DOMINGO DE LOS TSACHILAS / SANTO DOMINGO / X / Y",
                "estado": "ABIERTO",
            },
        ],
    )
    assert [f["provincia"] for f in propuesta["cobertura"]] == [
        "Manabí",
        "Santo Domingo de los Tsáchilas",
    ]


def test_un_ruc_que_no_esta_activo_avisa() -> None:
    propuesta = propuesta_desde_sri(
        {**CONTRIBUYENTE, "estadoContribuyenteRuc": "SUSPENDIDO"}, ESTABLECIMIENTOS
    )
    assert any("suspendido" in aviso for aviso in propuesta["avisos"])


def test_persona_natural_y_rimpe() -> None:
    propuesta = propuesta_desde_sri(
        {
            **CONTRIBUYENTE,
            "numeroRuc": "1712345678001",
            "tipoContribuyente": "PERSONAS NATURALES",
            "regimen": "RIMPE",
            "categoria": "NEGOCIO POPULAR",
            "obligadoLlevarContabilidad": "NO",
        },
        [],
    )
    assert propuesta["identidad"]["tipo_persona"] == "natural"
    assert propuesta["identidad"]["regimen_tributario"] == "RIMPE · Negocio Popular"
    assert propuesta["identidad"]["obligado_contabilidad"] is False
    assert propuesta["cobertura"] == []


def _actor(rol: str = "dueno_empresa") -> Actor:
    from uuid import uuid4

    return Actor(usuario_id=uuid4(), negocio_id=uuid4(), rol=rol)


def test_consultar_ruc_devuelve_la_propuesta() -> None:
    propuesta = asyncio.run(
        consultar_ruc(_actor(), ruc="1792146739001", sri=_sri([CONTRIBUYENTE], ESTABLECIMIENTOS))
    )
    assert propuesta["ruc"] == "1792146739001"
    assert propuesta["identidad"]["razon_social"]


def test_un_usuario_regular_no_consulta() -> None:
    with pytest.raises(SinPermiso):
        asyncio.run(consultar_ruc(_actor("usuario"), ruc="1792146739001", sri=_sri([])))


def test_un_ruc_mal_formado_no_llega_al_sri() -> None:
    with pytest.raises(DatoInvalido):
        asyncio.run(consultar_ruc(_actor(), ruc="1234567890000", sri=_sri([CONTRIBUYENTE])))


def test_el_sri_no_conoce_el_ruc() -> None:
    with pytest.raises(NoEncontrado):
        asyncio.run(consultar_ruc(_actor(), ruc="1792146739001", sri=_sri([])))


def test_el_sri_caido_dice_que_se_llene_a_mano() -> None:
    with pytest.raises(EstadoInvalido, match="a mano"):
        asyncio.run(consultar_ruc(_actor(), ruc="1792146739001", sri=_sri([], estado=503)))


def test_la_fecha_del_navegador_se_convierte() -> None:
    assert str(_fecha("2016-03-14")) == "2016-03-14"
    assert _fecha("") is None
    with pytest.raises(DatoInvalido):
        _fecha("14/03/2016")
