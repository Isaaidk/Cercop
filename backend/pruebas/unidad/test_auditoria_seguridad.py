"""Regresiones de la auditoría de seguridad (docs/38-auditoria-seguridad.md).

Cada prueba fija un hallazgo concreto: si alguna vuelve a fallar, el hueco que cerró está abierto
otra vez. No necesitan base de datos.
"""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from contratacion.aplicacion.casos_uso.revisar_alertas import revisar_alertas
from contratacion.infraestructura.adaptadores.entrada.http import proteccion
from contratacion.infraestructura.adaptadores.entrada.http.proteccion import (
    CSP_API,
    FrenoPorIp,
    LimiteDeCuerpo,
    clave_de_ip,
    crear_proteccion,
    ip_cliente,
)
from contratacion.infraestructura.adaptadores.salida.archivos.tdr import (
    EnlaceNoPermitido,
    descargar_a,
    enlace_permitido,
)
from contratacion.infraestructura.adaptadores.salida.texto_anexos import (
    FormatoNoLegible,
    texto_de_docx,
    texto_de_xlsx,
)
from contratacion.infraestructura.app import crear_app
from contratacion.infraestructura.config.ajustes import Ajustes

# --- IP de quien llama -------------------------------------------------------------------------


def _peticion(directa: str, reenviada: str | None = None, ruta: str = "/v1/auth/sesion") -> Any:
    cabeceras = Headers({"x-forwarded-for": reenviada} if reenviada is not None else {})
    return SimpleNamespace(
        method="POST",
        url=SimpleNamespace(path=ruta),
        client=SimpleNamespace(host=directa),
        headers=cabeceras,
    )


def test_sin_proxy_declarado_la_cabecera_reenviada_se_ignora() -> None:
    assert ip_cliente(_peticion("10.0.0.5", "1.2.3.4"), 0) == "10.0.0.5"


def test_con_un_proxy_se_toma_la_ultima_direccion_no_la_primera() -> None:
    """La primera la escribe el cliente; la última, el proxy de confianza."""
    peticion = _peticion("1.2.3.4", "6.6.6.6, 203.0.113.7")
    assert ip_cliente(peticion, 1) == "203.0.113.7"


def test_una_cabecera_inservible_cae_a_la_conexion_directa() -> None:
    assert ip_cliente(_peticion("10.0.0.5", "no-es-una-ip"), 1) == "10.0.0.5"
    assert ip_cliente(_peticion("10.0.0.5", None), 1) == "10.0.0.5"
    assert ip_cliente(_peticion("10.0.0.5", "203.0.113.7"), 2) == "10.0.0.5"


def test_una_ipv6_cuenta_por_su_red() -> None:
    assert clave_de_ip("2001:db8:1:2:aaaa::1") == clave_de_ip("2001:db8:1:2:bbbb::9")
    assert clave_de_ip("2001:db8:1:2::1") != clave_de_ip("2001:db8:1:3::1")
    assert clave_de_ip("::ffff:203.0.113.7") == "203.0.113.7"
    assert clave_de_ip("203.0.113.7") == "203.0.113.7"


async def test_cambiar_la_ip_inventada_no_salta_el_freno() -> None:
    """Regresión: con `--forwarded-allow-ips '*'` cada intento podía traer una IP distinta."""
    proteger = crear_proteccion(produccion=False, exentas=frozenset(), saltos=1)

    async def siguiente(_: Any) -> Any:
        from fastapi import Response

        return Response("ok")

    codigos = []
    for intento in range(25):
        peticion = _peticion("10.0.0.1", f"198.51.100.{intento}, 203.0.113.7")
        codigos.append((await proteger(peticion, siguiente)).status_code)
    assert 429 in codigos


async def test_la_barra_final_no_abre_otro_cupo() -> None:
    proteger = crear_proteccion(produccion=False, exentas=frozenset())

    async def siguiente(_: Any) -> Any:
        from fastapi import Response

        return Response("ok")

    codigos = []
    for intento in range(25):
        ruta = "/v1/auth/sesion/" if intento % 2 else "/v1/auth/sesion"
        codigos.append((await proteger(_peticion("10.0.0.2", ruta=ruta), siguiente)).status_code)
    assert codigos.count(200) == 20


def test_llenar_el_freno_no_borra_las_marcas_del_atacante(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regresión: al pasar del tope se vaciaba todo, incluido el cupo de quien atacaba."""
    monkeypatch.setattr(proteccion, "_TOPE_IPS", 10)
    freno = FrenoPorIp()
    atacante = ("POST", "/v1/auth/sesion", "203.0.113.7")
    for _ in range(3):
        freno.permite(atacante, 3, 300)
    for relleno in range(50):
        freno.permite(("POST", "/v1/auth/sesion", f"198.51.100.{relleno}"), 3, 300)
        freno.permite(atacante, 3, 300)
    assert freno.permite(atacante, 3, 300) > 0


# --- Tope del cuerpo y cabeceras -----------------------------------------------------------------


def _app_con_tope(maximo: int) -> FastAPI:
    app = FastAPI()

    @app.post("/eco")
    async def eco(peticion: Request) -> dict[str, int]:
        return {"bytes": len(await peticion.body())}

    app.add_middleware(LimiteDeCuerpo, maximo_bytes=maximo)
    return app


def test_un_cuerpo_declarado_demasiado_grande_se_rechaza_antes_de_leerlo() -> None:
    cliente = TestClient(_app_con_tope(1024))
    respuesta = cliente.post("/eco", content=b"x" * 2048)
    assert respuesta.status_code == 413
    assert respuesta.json()["codigo"] == "cuerpo_demasiado_grande"


def test_un_cuerpo_por_trozos_se_corta_al_pasar_el_tope() -> None:
    """Sin `Content-Length` el tope se cuenta a medida que llega el cuerpo."""
    cliente = TestClient(_app_con_tope(1024))

    def trozos() -> Any:
        for _ in range(8):
            yield b"x" * 512

    respuesta = cliente.post("/eco", content=trozos())
    assert respuesta.status_code == 413


def test_un_cuerpo_dentro_del_tope_pasa() -> None:
    cliente = TestClient(_app_con_tope(1024))
    respuesta = cliente.post("/eco", content=b"x" * 100)
    assert respuesta.status_code == 200
    assert respuesta.json() == {"bytes": 100}


def test_la_api_publica_cabeceras_de_seguridad_y_tope_de_cuerpo() -> None:
    cliente = TestClient(crear_app())
    respuesta = cliente.get("/salud")
    assert respuesta.headers["content-security-policy"] == CSP_API
    assert respuesta.headers["x-content-type-options"] == "nosniff"
    assert respuesta.headers["x-frame-options"] == "DENY"
    grande = cliente.post(
        "/v1/registro/empresa",
        content=b"x" * (21 * 1024 * 1024),
        headers={"content-type": "application/json"},
    )
    assert grande.status_code == 413


# --- Rutas: todas piden sesión salvo las públicas a propósito -----------------------------------

RUTAS_PUBLICAS = {
    ("GET", "/salud"),
    ("GET", "/listo"),
    ("GET", "/v1/politicas/{tipo}"),
    # Páginas `/terminos` y `/privacidad`: el texto se lee antes de crear la cuenta (art. 12 LOPDP).
    ("GET", "/v1/politicas/publicas/{tipo}"),
    ("GET", "/v1/registro/requisitos"),
    ("POST", "/v1/registro/empresa"),
    ("POST", "/v1/registro/consulta-ruc"),
    ("POST", "/v1/auth/sesion"),
    ("POST", "/v1/auth/sesion/renovacion"),
    # El cierre acepta el token de renovación en el cuerpo y lo verifica él mismo.
    ("POST", "/v1/auth/sesion/cierre"),
}


def _llamadas(dependiente: Any, acumuladas: set[str]) -> set[str]:
    for sub in dependiente.dependencies:
        acumuladas.add(getattr(sub.call, "__name__", type(sub.call).__name__))
        _llamadas(sub, acumuladas)
    return acumuladas


def _rutas() -> list[APIRoute]:
    import importlib
    import pkgutil

    import contratacion.infraestructura.adaptadores.entrada.http.routers as paquete

    rutas: list[APIRoute] = []
    for modulo in pkgutil.iter_modules(paquete.__path__):
        enrutador = getattr(
            importlib.import_module(f"{paquete.__name__}.{modulo.name}"), "router", None
        )
        if enrutador is not None:
            rutas.extend(r for r in enrutador.routes if isinstance(r, APIRoute))
    return rutas


def test_toda_ruta_no_publica_exige_sesion() -> None:
    """Regresión: `/v1/terminos/{id}/estado` respondía sin sesión."""
    sin_sesion = sorted(
        (metodo, ruta.path)
        for ruta in _rutas()
        for metodo in ruta.methods
        if "obtener_actor" not in _llamadas(ruta.dependant, set())
        and (metodo, ruta.path) not in RUTAS_PUBLICAS
    )
    assert sin_sesion == []


def test_las_rutas_de_la_plantilla_pasan_por_la_puerta_de_consentimiento() -> None:
    """Regresión: con la contraseña temporal se podía subir o borrar la plantilla."""
    rutas = [r for r in _rutas() if r.path.startswith("/v1/plantilla")]
    assert rutas
    for ruta in rutas:
        assert "consentimiento_del_actor" in _llamadas(ruta.dependant, set()), ruta.path


def test_el_cambio_de_contrasena_tiene_freno_por_persona() -> None:
    """Con un token robado se podía probar la contraseña actual sin límite."""
    from contratacion.infraestructura.adaptadores.entrada.http.limites import LimitePorUsuario

    (ruta,) = [r for r in _rutas() if r.path == "/v1/auth/contrasena"]
    frenos = [d.call for d in ruta.dependant.dependencies if isinstance(d.call, LimitePorUsuario)]
    assert frenos


async def test_el_cierre_de_sesion_no_acepta_motivos_del_servidor() -> None:
    """El cliente no puede escribir en la auditoría «lo cerró un administrador» o «robo»."""
    from contratacion.aplicacion.puertos.seguridad import Claims, TipoToken
    from contratacion.dominio.sesiones import MotivoRevocacion
    from contratacion.infraestructura.adaptadores.entrada.http.routers.autenticacion import (
        CierreDeSesion,
        cerrar,
    )
    from contratacion.infraestructura.adaptadores.salida.seguridad.fabrica import obtener_tokens

    tokens = obtener_tokens()
    claims = Claims(
        usuario_id=uuid4(),
        negocio_id=uuid4(),
        rol="usuario",
        sesion_id=uuid4(),
        tipo=TipoToken.REFRESCO,
        expira_en=datetime.now(UTC),
    )
    token = tokens.emitir(claims, 600)

    class Sesiones:
        def __init__(self) -> None:
            self.motivos: list[MotivoRevocacion] = []

        async def revocar_varias(self, *, motivo: MotivoRevocacion, **_: Any) -> int:
            self.motivos.append(motivo)
            return 1

    class Cuentas:
        async def auditar(self, **_: Any) -> None:
            return None

    sesiones = Sesiones()
    for motivo in (MotivoRevocacion.ADMIN, MotivoRevocacion.REUSO_DETECTADO):
        await cerrar(
            cuentas=Cuentas(),  # type: ignore[arg-type]
            sesiones=sesiones,  # type: ignore[arg-type]
            cuerpo=CierreDeSesion(token_renovacion=token, motivo=motivo),
        )
    await cerrar(
        cuentas=Cuentas(),  # type: ignore[arg-type]
        sesiones=sesiones,  # type: ignore[arg-type]
        cuerpo=CierreDeSesion(token_renovacion=token, motivo=MotivoRevocacion.CIERRE_VENTANA),
    )
    assert sesiones.motivos == [
        MotivoRevocacion.LOGOUT,
        MotivoRevocacion.LOGOUT,
        MotivoRevocacion.CIERRE_VENTANA,
    ]


# --- SSRF en la descarga de anexos ---------------------------------------------------------------

PORTAL = ("compraspublicas.gob.ec",)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.compraspublicas.gob.ec/ProcesoContratacion/archivo.pdf",
        "http://compraspublicas.gob.ec/x",
        "https://datosabiertos.compraspublicas.gob.ec/PLATAFORMA/api",
    ],
)
def test_los_enlaces_del_portal_se_admiten(url: str) -> None:
    assert enlace_permitido(url, PORTAL)


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://localhost:8001/v1/salud",
        "http://127.0.0.1/",
        "http://[::1]/",
        "http://10.0.0.5/interno",
        "https://compraspublicas.gob.ec.atacante.com/x",
        "https://atacantecompraspublicas.gob.ec/x",
        "https://usuario:clave@compraspublicas.gob.ec/x",
        "file:///etc/passwd",
        "gopher://compraspublicas.gob.ec/x",
        "https://compraspublicas.gob.ec:99999/x",
    ],
)
def test_los_enlaces_fuera_del_portal_se_rechazan(url: str) -> None:
    assert not enlace_permitido(url, PORTAL)


async def test_una_redireccion_hacia_dentro_de_la_red_no_se_sigue(tmp_path: Path) -> None:
    pedidas: list[str] = []

    def responder(peticion: httpx.Request) -> httpx.Response:
        pedidas.append(str(peticion.url))
        return httpx.Response(302, headers={"location": "http://169.254.169.254/secreto"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as cliente:
        with pytest.raises(EnlaceNoPermitido):
            await descargar_a(
                cliente, "https://www.compraspublicas.gob.ec/a.pdf", tmp_path, dominios=PORTAL
            )
    assert pedidas == ["https://www.compraspublicas.gob.ec/a.pdf"]
    assert not any(tmp_path.iterdir())


async def test_una_redireccion_dentro_del_portal_se_sigue(tmp_path: Path) -> None:
    def responder(peticion: httpx.Request) -> httpx.Response:
        if peticion.url.path == "/a.pdf":
            return httpx.Response(302, headers={"location": "/b.pdf"})
        return httpx.Response(200, content=b"%PDF-1.4 hola")

    async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as cliente:
        ruta, _, tamano = await descargar_a(
            cliente, "https://www.compraspublicas.gob.ec/a.pdf", tmp_path, dominios=PORTAL
        )
    assert ruta.read_bytes() == b"%PDF-1.4 hola"
    assert tamano == len(b"%PDF-1.4 hola")


def test_por_defecto_solo_se_permite_el_portal(monkeypatch: pytest.MonkeyPatch) -> None:
    ajustes = Ajustes()
    assert ajustes.anexos_dominios_permitidos == ["compraspublicas.gob.ec"]
    monkeypatch.setenv("ANEXOS_DOMINIOS_PERMITIDOS", "compraspublicas.gob.ec, Sercop.Gob.Ec")
    assert Ajustes().anexos_dominios_permitidos == ["compraspublicas.gob.ec", "sercop.gob.ec"]


# --- Bombas ZIP en Word y Excel ------------------------------------------------------------------


def _paquete(partes: dict[str, bytes]) -> bytes:
    memoria = io.BytesIO()
    with zipfile.ZipFile(memoria, "w", compression=zipfile.ZIP_DEFLATED) as paquete:
        for nombre, contenido in partes.items():
            paquete.writestr(nombre, contenido)
    return memoria.getvalue()


def test_un_word_que_descomprimido_es_enorme_se_rechaza() -> None:
    """Regresión: cada parte se acotaba sola y mil encabezados pasaban el filtro."""
    relleno = b"<w:p/>" + b" " * (3 * 1024 * 1024)
    partes = {"word/document.xml": b"<w:p>hola</w:p>"}
    partes.update({f"word/header{n}.xml": relleno for n in range(15)})
    with pytest.raises(FormatoNoLegible):
        texto_de_docx(_paquete(partes))


def test_un_excel_que_descomprimido_es_enorme_se_rechaza_sin_abrirlo() -> None:
    contenido = _paquete(
        {
            "xl/workbook.xml": b"<workbook/>",
            "xl/sharedStrings.xml": b" " * (41 * 1024 * 1024),
        }
    )
    with pytest.raises(FormatoNoLegible):
        texto_de_xlsx(contenido)


def test_un_word_normal_se_sigue_leyendo() -> None:
    contenido = _paquete({"word/document.xml": b"<w:p><w:t>Hola &amp; adios</w:t></w:p>"})
    assert texto_de_docx(contenido) == "Hola & adios"


def test_un_word_con_entidades_no_las_expande() -> None:
    """El Word se lee con expresiones regulares, no con un analizador XML: un DTD no se aplica."""
    xml = (
        b'<?xml version="1.0"?><!DOCTYPE w [<!ENTITY a "AAAAAAAAAA">'
        b'<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]><w:p><w:t>&b;</w:t></w:p>'
    )
    texto = texto_de_docx(_paquete({"word/document.xml": xml}))
    assert "AAAAAAAAAA" not in texto


# --- Ajustes ----------------------------------------------------------------------------------


def test_un_entorno_mal_escrito_no_arranca() -> None:
    with pytest.raises(ValueError):
        Ajustes(entorno="prd")
    assert Ajustes(entorno=" Prod ").es_produccion


# --- Alertas del worker ------------------------------------------------------------------------


async def test_la_alerta_se_marca_revisada_en_el_contexto_de_su_empresa() -> None:
    """Regresión: sin contexto, con el rol correcto (sin BYPASSRLS) no se marcaba nunca."""
    negocio = uuid4()
    alerta_id = uuid4()

    class Radar:
        def __init__(self) -> None:
            self.marcadas: list[tuple[UUID, UUID | None]] = []

        async def listar_alertas(self, *, negocio_id: UUID | None = None) -> list[dict[str, Any]]:
            return [
                {
                    "id": alerta_id,
                    "negocio_id": negocio,
                    "usuario_id": uuid4(),
                    "revisada_en": None,
                    "frecuencia": "diaria",
                    "activa": True,
                }
            ]

        async def marcar_revisada(
            self, alerta_id: UUID, momento: datetime, *, negocio_id: UUID | None = None
        ) -> None:
            self.marcadas.append((alerta_id, negocio_id))

        def __getattr__(self, nombre: str) -> Any:
            async def nada(*_: Any, **__: Any) -> Any:
                return []

            return nada

    radar = Radar()
    await revisar_alertas(radar)  # type: ignore[arg-type]
    assert radar.marcadas == [(alerta_id, negocio)]


# --- Tokens ------------------------------------------------------------------------------------


def test_dos_tokens_del_mismo_segundo_no_son_iguales() -> None:
    """Regresión: sin `jti`, rotar dentro del mismo segundo devolvía el mismo token."""
    from contratacion.aplicacion.puertos.seguridad import Claims, TipoToken
    from contratacion.infraestructura.adaptadores.salida.seguridad.tokens import TokensJwt

    tokens = TokensJwt("s" * 48)
    claims = Claims(
        usuario_id=uuid4(),
        negocio_id=uuid4(),
        rol="usuario",
        sesion_id=uuid4(),
        tipo=TipoToken.REFRESCO,
        expira_en=datetime.now(UTC),
    )
    primero, segundo = tokens.emitir(claims, 600), tokens.emitir(claims, 600)
    assert primero != segundo
    assert tokens.huella(primero) != tokens.huella(segundo)
    assert tokens.verificar(segundo, TipoToken.REFRESCO).sesion_id == claims.sesion_id
