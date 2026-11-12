"""Lectura de los certificados del RUP (SERCOP) y del RUC (SRI) subidos en PDF.

`datos/rup_y_ruc_ejemplo.txt` es el texto que `pypdf` saca de un PDF **real** que trae los dos
certificados (dos páginas del SRI y una del RUP), con los datos personales reemplazados. Si el
formato de los certificados cambia, se actualiza ese archivo con el texto nuevo y estas pruebas
dicen qué se dejó de leer.
"""

from __future__ import annotations

from pathlib import Path

from contratacion.dominio.rup import leer_rup

EJEMPLO = (Path(__file__).parent / "datos" / "rup_y_ruc_ejemplo.txt").read_text(encoding="utf-8")


def test_lee_los_dos_certificados() -> None:
    resultado = leer_rup(EJEMPLO)

    assert resultado["ruc"] == "1712345678001"
    assert resultado["documentos"] == ["RUP", "RUC del SRI"]
    assert resultado["avisos"] == []
    assert resultado["identidad"] == {
        "razon_social": "Perez Lopez Juan Carlos",
        "tipo_persona": "natural",
        "regimen_tributario": "General",
        "estado_rup": "habilitado",
        "email_contacto": "contacto@ejemplo.ec",
        "telefono": "0990000000",
        "direccion": "Av. Siempre Viva S1-100 y Carlos Alvarez (frente al parque)",
        "ciudad": "Quito",
        "capacidad_ejecucion": "Categoría RUP: Micro 0-300000",
        "obligado_contabilidad": False,
    }
    assert resultado["cobertura"] == [{"provincia": "Pichincha", "canton": "Quito"}]
    assert resultado["representante"]["cedula"] == "1712345678"


def test_cada_cpc_con_su_descripcion_completa() -> None:
    cpc = leer_rup(EJEMPLO)["cpc"]

    codigos = [fila["codigo"] for fila in cpc]
    assert codigos == ["73210", "85970", "85990", "96111", "96220", "96320"]
    # La descripción partida en dos líneas del PDF llega entera.
    assert cpc[0]["descripcion"].endswith("EQUIPOS DE AMPLIFICACION Y DE ESCENARIOS")


def test_las_actividades_del_sri_con_su_ciiu() -> None:
    actividades = leer_rup(EJEMPLO)["actividades"]

    assert len(actividades) == 11
    assert actividades[0]["ciiu"] == "G46491102" and actividades[0]["principal"] is True
    # La que cruza de página sigue entera y la cabecera repetida no se cuela en la anterior.
    assert actividades[9]["ciiu"] == "R90000401"
    assert "PEREZ" not in actividades[8]["descripcion"]
    # «ESTABLECIMIENTOS ESPECIALIZADOS» dentro de una descripción no corta el bloque.
    assert actividades[2]["descripcion"].endswith("ESTABLECIMIENTOS ESPECIALIZADOS.")


def test_no_toma_por_cpc_ciiu_resoluciones_ni_codigos_de_verificacion() -> None:
    codigos = {fila["codigo"] for fila in leer_rup(EJEMPLO)["cpc"]}
    assert not codigos & {"46491102", "00000217", "2011", "1712345678001"}


def test_solo_el_ruc_del_sri_avisa_que_falta_el_rup() -> None:
    solo_sri = EJEMPLO.split("Sistema Oficial de Contratación Pública")[0]
    resultado = leer_rup(solo_sri)
    assert resultado["cpc"] == []
    assert len(resultado["actividades"]) == 11
    assert any("RUP" in aviso for aviso in resultado["avisos"])


def test_pdf_escaneado_avisa() -> None:
    resultado = leer_rup("")
    assert resultado["cpc"] == []
    assert any("escaneado" in aviso for aviso in resultado["avisos"])


def test_rup_suspendido_avisa() -> None:
    resultado = leer_rup(
        "REGISTRO ÚNICO DE PROVEEDORES\nqueda SUSPENDIDO en el Registro\n"
        "Código Producto\n45110 OBRAS"
    )
    assert resultado["identidad"]["estado_rup"] == "suspendido"
    assert any("suspendido" in aviso for aviso in resultado["avisos"])


async def test_aplicar_rup_carga_cada_cpc_sin_duplicar() -> None:
    from typing import Any
    from uuid import uuid4

    from contratacion.aplicacion.actor import Actor
    from contratacion.aplicacion.casos_uso.gestionar_perfil import aplicar_rup

    class Perfil:
        def __init__(self) -> None:
            self.identidad: dict[str, Any] = {}
            self.filas: list[tuple[str, dict[str, Any]]] = []

        async def leer(self, negocio_id: Any) -> dict[str, Any]:
            return {"ofertas": [{"nombre": "Ya estaba", "descripcion": "CPC 87150"}]}

        async def guardar_identidad(self, negocio_id: Any, campos: dict[str, Any]) -> None:
            self.identidad.update(campos)

        async def agregar(self, negocio_id: Any, coleccion: str, campos: dict[str, Any]) -> Any:
            self.filas.append((coleccion, campos))
            return campos

    class Cpc:
        def __init__(self) -> None:
            self.textos: list[str] = []

        async def agregar(self, **kwargs: Any) -> bool:
            self.textos.append(kwargs["texto"])
            return True

    perfil, cpc = Perfil(), Cpc()
    actor = Actor(usuario_id=uuid4(), negocio_id=uuid4(), rol="super_admin")
    resultado = await aplicar_rup(
        actor,
        repositorio=perfil,  # type: ignore[arg-type]
        cpc=cpc,  # type: ignore[arg-type]
        propuesta={
            "identidad": {"estado_rup": "habilitado", "telefono": "022345678", "otro": "x"},
            "cpc": [
                {"codigo": "541290011", "descripcion": "CONSTRUCCION DE EDIFICIOS"},
                {"codigo": "38110", "descripcion": "MUEBLES DE OFICINA"},
                {"codigo": "87150", "descripcion": "MANTENIMIENTO"},
            ],
        },
    )

    assert perfil.identidad == {"estado_rup": "habilitado", "telefono": "022345678"}
    assert cpc.textos == ["541290011", "38110", "87150"]
    ofertas = [campos for coleccion, campos in perfil.filas if coleccion == "ofertas"]
    assert [(o["tipo"], o["descripcion"]) for o in ofertas] == [
        ("servicio", "CPC 541290011"),
        ("producto", "CPC 38110"),
    ]
    assert resultado["ofertas"] == 2
