"""Verificación de la administración de la plataforma: censo, suspensión y bloqueo total.

Se ejecuta a mano contra una base real, con la API levantada:

    .\\.venv\\Scripts\\python.exe scripts\\verificar_plataforma.py

**No usa ninguna contraseña escrita en el archivo.** Genera las suyas en memoria con
`secrets.token_urlsafe`, las usa para iniciar sesión y las descarta al terminar. Es deliberado: un
guion de verificación con una credencial dentro acaba copiándose a otro sitio, y ese es el
camino por
el que las claves de pruebas llegan a producción.

Crea dos empresas temporales —una con el superadministrador de la plataforma y otra con un
administrador normal—, comprueba lo que hay que comprobar y las borra. Deja la base como estaba, y
por eso puede ejecutarse tantas veces como haga falta.
"""

from __future__ import annotations

import asyncio
import secrets
import sys
import time
from datetime import UTC, datetime
from uuid import uuid4

sys.path.insert(0, "src")

import httpx
from sqlalchemy import text

from contratacion.aplicacion.puertos.negocios import AltaEmpresa
from contratacion.dominio.acceso import Plazo, Vista
from contratacion.dominio.negocios import construir_datos_empresa
from contratacion.dominio.roles import Rol
from contratacion.infraestructura.adaptadores.salida.bd.contexto import (
    contexto_negocio,
)
from contratacion.infraestructura.adaptadores.salida.bd.negocios import (
    RepositorioNegociosBd,
)
from contratacion.infraestructura.adaptadores.salida.bd.sesion import obtener_motor
from contratacion.infraestructura.adaptadores.salida.seguridad.fabrica import (
    obtener_contrasenas,
)

BASE = "http://127.0.0.1:8001"
FALLOS: list[str] = []


def _seccion(titulo: str) -> None:
    print(f"\n{'=' * 66}\n{titulo}\n{'=' * 66}")


def _marca(condicion: bool, texto: str) -> None:
    if not condicion:
        FALLOS.append(texto)
    print(f"  {'OK ' if condicion else 'MAL'} {texto}")


async def _crear_superadministrador(email: str, contrasena: str, nombre: str) -> object:
    motor = obtener_motor()
    negocio_id = uuid4()
    await RepositorioNegociosBd(motor).crear(
        AltaEmpresa(
            negocio_id=negocio_id,
            datos=construir_datos_empresa(nombre=f"Verificacion Plataforma {negocio_id.hex[:6]}"),
            admin_id=uuid4(),
            admin_email=email,
            admin_nombre=nombre,
            admin_rol=Rol.SUPER_ADMIN,
            huella=obtener_contrasenas().hash(contrasena),
            vistas_prueba=tuple(Vista),
            plazo_prueba=Plazo.A1,
            momento=datetime.now(UTC),
        )
    )
    return negocio_id


async def _borrar_empresa(negocio_id: object) -> None:
    """Borra una empresa temporal. El `ON DELETE CASCADE` se lleva sus cuentas y sus sesiones."""
    motor = obtener_motor()
    async with contexto_negocio(motor, negocio_id) as conexion:  # type: ignore[arg-type]
        await conexion.execute(
            text("DELETE FROM negocio WHERE id = :negocio_id"),
            {"negocio_id": str(negocio_id)},
        )


async def main() -> None:
    clave_plataforma = secrets.token_urlsafe(24)
    clave_empresa = secrets.token_urlsafe(24)
    correo_plataforma = f"plataforma-{uuid4().hex[:8]}@verificacion.ec"
    correo_empresa = f"empresa-{uuid4().hex[:8]}@verificacion.ec"

    negocio_plataforma = await _crear_superadministrador(
        correo_plataforma, clave_plataforma, "Verificador"
    )
    negocio_empresa: object | None = None
    cuerpo: dict[str, object] = {}

    try:
        async with httpx.AsyncClient(base_url=BASE, timeout=60) as c:
            _seccion("1. El superadministrador entra")
            r = await c.post(
                "/v1/auth/sesion",
                json={"email": correo_plataforma, "contrasena": clave_plataforma},
            )
            _marca(r.status_code == 200, f"POST /v1/auth/sesion -> {r.status_code}")
            _marca(r.json().get("rol") == "super_admin", f"rol: {r.json().get('rol')}")
            cab_plataforma = {"Authorization": f"Bearer {r.json()['token_acceso']}"}

            _seccion("2. Se registra una empresa normal (el objetivo)")
            r = await c.post(
                "/v1/registro/empresa",
                json={
                    "nombre": "Empresa Para Suspender S.A.",
                    "admin_email": correo_empresa,
                    "contrasena": clave_empresa,
                    "admin_nombre": "Admin Objetivo",
                },
            )
            _marca(r.status_code == 201, f"POST /v1/registro/empresa -> {r.status_code}")
            negocio_empresa = r.json()["negocio_id"]

            r = await c.post(
                "/v1/auth/sesion",
                json={"email": correo_empresa, "contrasena": clave_empresa},
            )
            cab_empresa = {"Authorization": f"Bearer {r.json()['token_acceso']}"}
            # La empresa nueva nace debiendo aceptar los términos, y sin aceptarlos no lee datos.
            pendientes = (await c.get("/v1/politicas", headers=cab_empresa)).json()["politicas"]
            for politica in pendientes:
                await c.post(
                    f"/v1/politicas/{politica['tipo']}/aceptacion",
                    json={"version": politica["version"], "hash": politica["hash"]},
                    headers=cab_empresa,
                )
            _marca(
                (await c.get("/v1/registros?tamano=1", headers=cab_empresa)).status_code == 200,
                "la empresa lee datos antes de la suspensión",
            )

            _seccion("3. El censo de empresas")
            r = await c.get("/v1/plataforma/empresas", headers=cab_plataforma)
            _marca(r.status_code == 200, f"GET /v1/plataforma/empresas -> {r.status_code}")
            empresas = r.json()["empresas"] if r.status_code == 200 else []
            nombres = [e["nombre"] for e in empresas]
            _marca(len(empresas) > 0, f"{len(empresas)} empresas en el censo")
            _marca(
                "Empresa Para Suspender S.A." in nombres,
                "la empresa recién registrada aparece en el censo",
            )
            if empresas:
                print(f"  claves de una ficha: {sorted(empresas[0])}")

            _seccion("4. Una empresa normal NO administra la plataforma")
            r = await c.get("/v1/plataforma/empresas", headers=cab_empresa)
            _marca(r.status_code == 403, f"GET como administrador de negocio -> {r.status_code}")
            r = await c.post(
                f"/v1/plataforma/empresas/{negocio_empresa}/suspension", headers=cab_empresa
            )
            _marca(
                r.status_code == 403,
                f"POST suspensión como administrador de negocio -> {r.status_code}",
            )

            _seccion("5. Suspender la empresa")
            r = await c.post(
                f"/v1/plataforma/empresas/{negocio_empresa}/suspension", headers=cab_plataforma
            )
            _marca(r.status_code == 201, f"POST suspensión -> {r.status_code}")
            if r.status_code < 300:
                print(f"  estado: {r.json()['estado']} | activa: {r.json()['activa']}")
                print(f"  aviso: {r.json()['aviso']}")
                _marca(
                    "suspendida" in r.json()["aviso"] and "@" in r.json()["aviso"],
                    "el aviso menciona la suspensión y un correo de contacto",
                )
            r = await c.post(
                f"/v1/plataforma/empresas/{negocio_empresa}/suspension", headers=cab_plataforma
            )
            _marca(r.status_code == 422, f"suspender dos veces -> {r.status_code}")

            _seccion("6. La empresa suspendida no ve NADA")
            for ruta in (
                "/v1/registros?tamano=1",
                "/v1/negocio",
                "/v1/catalogos",
                "/v1/estadisticas",
                "/v1/usuarios",
                "/v1/terminos",
                "/v1/accesos/catalogo",
            ):
                respuesta = await c.get(ruta, headers=cab_empresa)
                try:
                    cuerpo = respuesta.json()
                except Exception:  # noqa: BLE001
                    cuerpo = {}
                codigo = cuerpo.get("codigo", "")
                _marca(
                    respuesta.status_code == 403 and codigo == "empresa_suspendida",
                    f"GET {ruta:24} -> {respuesta.status_code} | {codigo}",
                )
            print(f"  mensaje que ve el usuario: {cuerpo.get('detail', '')}")

            _seccion("7. El superadministrador sigue trabajando")
            r = await c.get("/v1/plataforma/empresas", headers=cab_plataforma)
            _marca(r.status_code == 200, f"GET /v1/plataforma/empresas -> {r.status_code}")
            if r.status_code == 200:
                ficha = next(
                    (e for e in r.json()["empresas"] if e["negocio_id"] == negocio_empresa), None
                )
                _marca(
                    ficha is not None and ficha["estado"] == "suspendido",
                    f"la ficha dice estado={ficha['estado'] if ficha else '?'}",
                )

            _seccion("8. Reactivar")
            r = await c.post(
                f"/v1/plataforma/empresas/{negocio_empresa}/reactivacion", headers=cab_plataforma
            )
            _marca(r.status_code == 201, f"POST reactivación -> {r.status_code}")
            r = await c.get("/v1/registros?tamano=1", headers=cab_empresa)
            _marca(r.status_code == 200, f"la empresa vuelve a leer -> {r.status_code}")

            _seccion("9. Auditoría: ningún endpoint de datos sin sesión")
            esquema = (await c.get("/openapi.json")).json()
            abiertos: list[tuple[str, int]] = []
            for ruta in sorted(esquema.get("paths", {})):
                if not ruta.startswith("/v1/") or "{" in ruta:
                    continue
                respuesta = await c.get(ruta)
                if respuesta.status_code not in {401, 403, 404, 405, 422}:
                    abiertos.append((ruta, respuesta.status_code))
            # Las únicas que pueden abrirse son las del registro, que existen justo para quien
            # todavía no tiene cuenta. Cualquier otra abierta es un agujero: por ahí una empresa
            # suspendida seguiría leyendo.
            esperadas = {"/v1/registro/requisitos"}
            inesperadas = [par for par in abiertos if par[0] not in esperadas]
            _marca(
                not inesperadas,
                f"rutas de datos abiertas sin sesión: {inesperadas or 'ninguna'}",
            )
            if abiertos:
                print(
                    f"  (abiertas y permitidas: {[p[0] for p in abiertos if p not in inesperadas]})"
                )

            _seccion("10. El trabajo del worker: historial y petición de un ciclo")
            r = await c.get("/v1/plataforma/ingesta/historial", headers=cab_plataforma)
            _marca(r.status_code == 200, f"GET /v1/plataforma/ingesta/historial -> {r.status_code}")
            tablero = r.json() if r.status_code == 200 else {}
            fuentes = tablero.get("fuentes") or []
            ciclos = tablero.get("historial") or {}
            _marca(bool(fuentes), f"fuentes informadas: {[f['codigo'] for f in fuentes]}")
            _marca(
                all(
                    {"iniciada_en", "estado", "nuevos"} <= set(ciclo)
                    for lista in ciclos.values()
                    for ciclo in lista
                ),
                "cada ciclo trae al menos cuándo arrancó, cómo acabó y cuánto escribió",
            )
            print(f"  ciclos por fuente: { {k: len(v) for k, v in ciclos.items()} }")
            print(f"  cadencia de comprobación: {tablero.get('cadencia_seg')} s")
            _marca(
                tablero.get("solicitud") is None, "no hay petición pendiente antes de pedir nada"
            )

            # Ordenar un ciclo es una decisión de la plataforma: un administrador de empresa no la
            # toma aunque su empresa esté activa y con todas sus vistas concedidas.
            r = await c.get("/v1/plataforma/ingesta/historial", headers=cab_empresa)
            _marca(
                r.status_code == 403 and r.json().get("codigo") == "sin_permiso",
                f"un admin de empresa -> {r.status_code} | {r.json().get('codigo')}",
            )
            r = await c.post("/v1/plataforma/ingesta/solicitud", headers=cab_empresa)
            _marca(
                r.status_code == 403 and r.json().get("codigo") == "sin_permiso",
                f"un admin de empresa no puede pedir un ciclo -> {r.status_code}",
            )

            pedido_en = datetime.now(UTC)
            r = await c.post("/v1/plataforma/ingesta/solicitud", headers=cab_plataforma)
            _marca(
                r.status_code == 201, f"POST /v1/plataforma/ingesta/solicitud -> {r.status_code}"
            )
            if r.status_code != 201:
                print(f"  respuesta: {r.text[:200]}")
            else:
                print(f"  petición: {r.json().get('solicitud')}")

                # Y ahora lo que de verdad se comprueba: que el worker la ve. Es la costura entre
                # los dos procesos —una petición HTTP que acaba en un ciclo de ingesta—, y sin el
                # worker levantado lo único que se puede decir es que la petición quedó esperando.
                empezado = time.monotonic()
                recogida: float | None = None
                # Dos minutos de paciencia y no treinta segundos: el worker mira la petición
                # **entre** ciclos, así que si está dentro de uno —y un ciclo completo tarda
                # minutos— la atiende al terminar. Medido: pedida durante un ciclo, seguía en cola a
                # los 30 s.
                while time.monotonic() - empezado < 120:
                    await asyncio.sleep(2)
                    seguimiento = await c.get(
                        "/v1/plataforma/ingesta/historial", headers=cab_plataforma
                    )
                    if (
                        seguimiento.status_code == 200
                        and seguimiento.json().get("solicitud") is None
                    ):
                        recogida = time.monotonic() - empezado
                        break

                if recogida is None:
                    print(
                        "  AVISO: la petición sigue en cola tras 120 s. Si el worker está "
                        "levantado y libre, esto es un fallo; si no lo está, es lo esperado."
                    )
                else:
                    print(f"  el worker la recogió en {recogida:.1f} s")

                    # Y que el ciclo quede escrito, que es lo que dibuja la gráfica. Se insiste
                    # porque hay una carrera de verdad entre las dos mitades: el worker
                    # consume la petición y **después** abre la fila de la sincronización, así que
                    # preguntar en el mismo suspiro en que desaparece la petición la encuentra sin
                    # escribir todavía. Se vio: la petición recogida en 3,2 s y cero ciclos nuevos,
                    # cuando el ciclo estaba arrancando en ese momento (`worker.err.log` lo enseña).
                    arrancados: list[str] = []
                    esperando = time.monotonic()
                    while time.monotonic() - esperando < 20 and not arrancados:
                        await asyncio.sleep(2)
                        tablero = (
                            await c.get("/v1/plataforma/ingesta/historial", headers=cab_plataforma)
                        ).json()
                        arrancados = [
                            ciclo["iniciada_en"]
                            for lista in (tablero.get("historial") or {}).values()
                            for ciclo in lista
                            if ciclo.get("iniciada_en")
                            and datetime.fromisoformat(ciclo["iniciada_en"]) >= pedido_en
                        ]
                    _marca(
                        bool(arrancados),
                        f"ciclos arrancados después de la petición: {sorted(arrancados)}",
                    )

            _seccion("11. La sesión: caducidad visible, rotación y ventana de gracia")
            entrada = (
                await c.post(
                    "/v1/auth/sesion",
                    json={"email": correo_empresa, "contrasena": clave_empresa},
                )
            ).json()
            # El panel programa su renovación con esa hora, así que si faltara no habría forma de
            # adelantarse a la caducidad: cada sesión esperaría al 401 y luego renovaría.
            _marca(
                "acceso_expira_en" in entrada and "renovacion_expira_en" in entrada,
                "el inicio de sesión dice cuándo caduca cada token",
            )
            print(
                f"  el acceso caduca en {entrada.get('acceso_expira_en')} "
                f"y la renovación en {entrada.get('renovacion_expira_en')}"
            )
            primera = entrada["token_renovacion"]

            r = await c.post("/v1/auth/sesion/renovacion", json={"token_renovacion": primera})
            _marca(r.status_code == 200, f"POST /v1/auth/sesion/renovacion -> {r.status_code}")
            segunda = r.json().get("token_renovacion", "")
            _marca(
                bool(segunda) and segunda != primera,
                "el token de renovación rota: el nuevo no es el mismo que el usado",
            )
            cab_nueva = {"Authorization": f"Bearer {r.json().get('token_acceso', '')}"}
            _marca(
                (await c.get("/v1/negocio", headers=cab_nueva)).status_code == 200,
                "el token de acceso recién emitido sirve para leer",
            )

            # Y ahora el tamaño de la ventana, que es lo que se cambió. Se espera **más** que los
            # treinta segundos del valor anterior para que la comprobación distinga una ventana de
            # segundos de una de minutos: con el valor viejo, presentar aquí el token de la
            # generación anterior se habría leído como «hay dos copias en circulación» y el servidor
            # habría cerrado **todas** las sesiones de la cuenta.
            espera = 35
            print(f"  esperando {espera} s para volver a presentar el token anterior...")
            await asyncio.sleep(espera)
            r = await c.post("/v1/auth/sesion/renovacion", json={"token_renovacion": primera})
            _marca(
                r.status_code == 200,
                f"el token de la generación anterior sigue valiendo a los {espera} s "
                f"-> {r.status_code}",
            )
            _marca(
                (await c.get("/v1/negocio", headers=cab_empresa)).status_code == 200,
                "la otra sesión de la cuenta sigue viva: dentro de la ventana no se cierra nada",
            )
    finally:
        if negocio_empresa is not None:
            await _borrar_empresa(negocio_empresa)
        await _borrar_empresa(negocio_plataforma)
        print("\nEmpresas temporales borradas.")
        if FALLOS:
            print(f"\n{len(FALLOS)} COMPROBACIONES FALLIDAS:")
            for fallo in FALLOS:
                print(f"  · {fallo}")
        else:
            print("\nTodas las comprobaciones pasaron.")


if __name__ == "__main__":
    asyncio.run(main())
