"""Comprobación de la exportación a Excel, de punta a punta y contra la API levantada.

Está aquí y no entre las pruebas automáticas porque necesita las tres cosas a la vez —una base real,
la API en marcha y archivos de verdad—, y porque lo que comprueba es precisamente la costura entre
el servidor y el navegador: cabeceras, tipo de contenido y bytes.

Lo que defiende esta comprobación, en una frase: **el archivo y la tabla no pueden discrepar**. Un
Excel con más filas que la pantalla, o con menos, sería el peor resultado posible, porque el usuario
no tiene forma de detectarlo. Por eso el recuento del archivo se compara con el total que declara
`/v1/registros` para los mismos filtros.

Se ejecuta a mano:

    .\\.venv\\Scripts\\python.exe scripts\\verificar_exportacion.py

Las credenciales se generan con `secrets.token_urlsafe`, se usan y se descartan: no hay ninguna
contraseña escrita en este archivo. Al terminar se borra la empresa temporal y con ella su cuenta,
por el `ON DELETE CASCADE`.
"""

from __future__ import annotations

import asyncio
import io
import secrets
import sys
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

sys.path.insert(0, "src")

import httpx
from openpyxl import load_workbook
from sqlalchemy import text

from contratacion.aplicacion.casos_uso.exportar_registros import (
    COLUMNA_PLAZO,
    NOMBRE_HOJA_CRITERIOS,
    TIPO_LIBRO,
)
from contratacion.aplicacion.puertos.negocios import AltaEmpresa
from contratacion.dominio.acceso import Plazo, Vista
from contratacion.dominio.busqueda import (
    ETIQUETA_OTRAS,
    ETIQUETA_POR_CATEGORIA,
    Categoria,
)
from contratacion.dominio.exportacion import inicio_exportable
from contratacion.dominio.negocios import construir_datos_empresa
from contratacion.dominio.roles import Rol
from contratacion.infraestructura.adaptadores.salida.bd.contexto import contexto_negocio
from contratacion.infraestructura.adaptadores.salida.bd.negocios import RepositorioNegociosBd
from contratacion.infraestructura.adaptadores.salida.bd.sesion import obtener_motor
from contratacion.infraestructura.adaptadores.salida.seguridad.fabrica import obtener_contrasenas

BASE = "http://127.0.0.1:8001"
TERMINO_DE_PRUEBA = "web"
# Palabra que existe dentro del **objeto de compra** de varias necesidades, y escrita como la
# escribiría una persona: con tilde y en mayúsculas. Que las dos cosas viajen bien no es cosmético:
# el índice guarda el objeto sin tildes, así que un término que llegara sin normalizar no
# coincidiría con nada y la exportación saldría vacía sin decir por qué.
DESCRIPCION_DE_PRUEBA = "CÓMPUTO"
FALLOS: list[str] = []

# Rellenos del semáforo, para comprobar que el color viaja en el archivo y no solo el número.
RELLENOS_ESPERADOS = {"FFC6EFCE", "FFFFEB9C", "FFFFC7CE"}


def _seccion(titulo: str) -> None:
    print(f"\n{'=' * 66}\n{titulo}\n{'=' * 66}")


def _marca(condicion: bool, texto: str) -> None:
    if not condicion:
        FALLOS.append(texto)
    print(f"  {'OK ' if condicion else 'MAL'} {texto}")


async def _crear_empresa(email: str, contrasena: str) -> object:
    """Una empresa temporal con una cuenta de superadministrador y todas las vistas concedidas."""
    motor = obtener_motor()
    negocio_id = uuid4()
    await RepositorioNegociosBd(motor).crear(
        AltaEmpresa(
            negocio_id=negocio_id,
            datos=construir_datos_empresa(nombre=f"Verificacion Exportacion {negocio_id.hex[:6]}"),
            admin_id=uuid4(),
            admin_email=email,
            admin_nombre="Verificador",
            admin_rol=Rol.SUPER_ADMIN,
            huella=obtener_contrasenas().hash(contrasena),
            vistas_prueba=tuple(Vista),
            plazo_prueba=Plazo.A1,
            momento=datetime.now(UTC),
        )
    )
    return negocio_id


async def _borrar_empresa(negocio_id: object) -> None:
    motor = obtener_motor()
    async with contexto_negocio(motor, negocio_id) as conexion:  # type: ignore[arg-type]
        await conexion.execute(
            text("DELETE FROM negocio WHERE id = :negocio_id"),
            {"negocio_id": str(negocio_id)},
        )


async def _entrar(c: httpx.AsyncClient, email: str, contrasena: str) -> dict[str, str]:
    """Inicia sesión y acepta los términos pendientes, que sin aceptar no se lee ningún dato."""
    respuesta = await c.post("/v1/auth/sesion", json={"email": email, "contrasena": contrasena})
    respuesta.raise_for_status()
    cabeceras = {"Authorization": f"Bearer {respuesta.json()['token_acceso']}"}

    pendientes = (await c.get("/v1/politicas", headers=cabeceras)).json()["politicas"]
    for politica in pendientes:
        await c.post(
            f"/v1/politicas/{politica['tipo']}/aceptacion",
            json={"version": politica["version"], "hash": politica["hash"]},
            headers=cabeceras,
        )
    return cabeceras


async def main() -> None:
    clave_admin = secrets.token_urlsafe(24)
    clave_lector = secrets.token_urlsafe(24)
    correo_admin = f"exportacion-{uuid4().hex[:8]}@verificacion.ec"
    correo_lector = f"lector-{uuid4().hex[:8]}@verificacion.ec"

    negocio = await _crear_empresa(correo_admin, clave_admin)

    try:
        async with httpx.AsyncClient(base_url=BASE, timeout=120) as c:
            cab_admin = await _entrar(c, correo_admin, clave_admin)
            # La descarga cubre como mucho los últimos tres meses, así que la comprobación pide ese
            # periodo: sin `desde`, el servidor **rechaza** la petición y este guion daría por rotas
            # cosas que están bien. El límite se pide a la misma función que usa el servidor —una
            # fecha escrita a mano aquí se quedaría vieja y volvería a fallar sin motivo—.
            desde = inicio_exportable().isoformat()
            filtros = {"termino": TERMINO_DE_PRUEBA, "modo": "cualquiera", "desde": desde}

            _seccion("1. Lo que dice la tabla")
            r = await c.get("/v1/registros", params={**filtros, "tamano": 1}, headers=cab_admin)
            _marca(r.status_code == 200, f"GET /v1/registros -> {r.status_code}")
            total_tabla = r.json()["total"]
            print(f"  total con «{TERMINO_DE_PRUEBA}»: {total_tabla}")

            _seccion("2. La exportación responde con un archivo")
            r = await c.get("/v1/registros/exportacion", params=filtros, headers=cab_admin)
            _marca(r.status_code == 200, f"GET /v1/registros/exportacion -> {r.status_code}")
            _marca(
                r.headers.get("content-type", "").startswith(TIPO_LIBRO),
                f"tipo de contenido: {r.headers.get('content-type')}",
            )
            _marca(
                "attachment" in r.headers.get("content-disposition", ""),
                f"se ofrece como descarga: {r.headers.get('content-disposition')}",
            )
            _marca(
                r.headers.get("cache-control") == "no-store",
                f"no se cachea: {r.headers.get('cache-control')}",
            )
            filas_cabecera = r.headers.get("x-contenido-filas")
            print(f"  cabecera X-Contenido-Filas: {filas_cabecera}")
            print(f"  tamaño del archivo: {len(r.content) / 1024:.1f} kB")

            _seccion("3. El archivo y la tabla cuentan lo mismo")
            _marca(
                str(total_tabla) == filas_cabecera,
                f"la tabla dice {total_tabla} y el archivo dice {filas_cabecera}",
            )

            _seccion("3b. La descripción del producto llega al archivo")
            # Sin el término de prueba: lo que se mide aquí es el criterio nuevo **solo**, porque
            # sumado a una palabra clave que no comparta filas devolvería cero y el cero no dice si
            # el filtro funciona o si simplemente no hay nada que cumpla las dos cosas.
            #
            # Las respuestas se guardan en variables propias **y no en `r`**: las secciones que
            # vienen detrás leen de `r` el archivo de la sección 2 y su hoja de criterios, así que
            # reutilizar el nombre cambiaría lo que ellas comprueban sin que se note.
            con_descripcion = {"descripcion": DESCRIPCION_DE_PRUEBA, "desde": desde}
            respuesta_desc = await c.get(
                "/v1/registros",
                params={**con_descripcion, "tamano": 1},
                headers=cab_admin,
            )
            total_descripcion = respuesta_desc.json()["total"]
            archivo_desc = await c.get(
                "/v1/registros/exportacion", params=con_descripcion, headers=cab_admin
            )
            filas_descripcion = archivo_desc.headers.get("x-contenido-filas")
            print(f"  total con la descripción «{DESCRIPCION_DE_PRUEBA}»: {total_descripcion}")
            _marca(
                total_descripcion > 0,
                f"la descripción encuentra algo ({total_descripcion})",
            )
            _marca(
                archivo_desc.status_code == 200,
                f"la exportación responde -> {archivo_desc.status_code}",
            )
            _marca(
                str(total_descripcion) == filas_descripcion,
                f"la tabla dice {total_descripcion} y el archivo dice {filas_descripcion}",
            )

            _seccion("4. El archivo es un libro de Excel legible")
            if r.status_code != 200 or not r.content:
                _marca(False, "no hay archivo que abrir")
            else:
                libro = load_workbook(io.BytesIO(r.content))
                # Una hoja por familia más la de criterios. Antes era una sola hoja con todo
                # mezclado, y esta comprobación se quedó esperando la forma vieja.
                esperadas = {
                    *ETIQUETA_POR_CATEGORIA.values(),
                    ETIQUETA_OTRAS,
                    "Contrataciones",
                    NOMBRE_HOJA_CRITERIOS,
                }
                _marca(
                    libro.sheetnames[-1] == NOMBRE_HOJA_CRITERIOS
                    and set(libro.sheetnames) <= esperadas,
                    f"hojas: {libro.sheetnames}",
                )
                hojas_datos = [n for n in libro.sheetnames if n != NOMBRE_HOJA_CRITERIOS]
                filas_en_hojas = sum(libro[n].max_row - 1 for n in hojas_datos)
                _marca(
                    filas_en_hojas == total_tabla,
                    f"filas entre todas las hojas de datos: {filas_en_hojas} de {total_tabla}",
                )
                hoja = libro[hojas_datos[0]]

                _seccion("5. El semáforo viaja en el archivo")
                cabecera = [celda.value for celda in hoja[1]]
                _marca(len(cabecera) > 10, f"columnas: {len(cabecera)}")
                _marca(
                    COLUMNA_PLAZO[1] in cabecera,
                    f"la columna del semáforo está: {COLUMNA_PLAZO[1] in cabecera}",
                )
                _marca(
                    hoja.auto_filter.ref is not None,
                    f"el cuadro lleva filtro: {hoja.auto_filter.ref}",
                )
                _marca(hoja.freeze_panes == "A2", f"cabecera fija: {hoja.freeze_panes}")

                columna = cabecera.index(COLUMNA_PLAZO[1]) + 1
                colores: dict[str, Any] = {}
                for numero in range(2, hoja.max_row + 1):
                    celda = hoja.cell(row=numero, column=columna)
                    color = celda.fill.start_color.rgb if celda.fill.fill_type else "sin relleno"
                    colores[color] = colores.get(color, 0) + 1
                print(f"  reparto de colores: {colores}")
                _marca(
                    any(color in RELLENOS_ESPERADOS for color in colores),
                    "hay celdas pintadas con un color del semáforo",
                )
                _marca(
                    all(valor is not None for valor in colores),
                    "todas las celdas del plazo traen texto",
                )

                _seccion("6. El archivo dice con qué filtros se generó")
                criterios = libro["Filtros aplicados"]
                volcado = {
                    fila[0]: fila[1] for fila in criterios.iter_rows(values_only=True) if fila[0]
                }
                for clave in ("Generado", "Palabras clave", "Combinación", "Fuente", "Orden"):
                    _marca(clave in volcado, f"criterio «{clave}»: {volcado.get(clave)}")
                _marca(
                    TERMINO_DE_PRUEBA in str(volcado.get("Palabras clave", "")),
                    "la hoja de criterios nombra el término buscado",
                )

            _seccion("6b. Pedir una familia deja solo esa familia")
            r = await c.get(
                "/v1/registros/exportacion",
                params={**filtros, "categoria": "infimas"},
                headers=cab_admin,
            )
            _marca(r.status_code == 200, f"exportar solo ínfimas -> {r.status_code}")
            if r.status_code == 200:
                solo = load_workbook(io.BytesIO(r.content))
                _marca(
                    ETIQUETA_POR_CATEGORIA[Categoria.INFIMAS] in solo.sheetnames,
                    f"hojas: {solo.sheetnames}",
                )
                _marca(
                    ETIQUETA_POR_CATEGORIA[Categoria.OFERTAS] not in solo.sheetnames,
                    "la hoja de ofertas no aparece cuando solo se piden ínfimas",
                )
                hoja_infimas = solo[ETIQUETA_POR_CATEGORIA[Categoria.INFIMAS]]
                _marca(
                    all(
                        celda.value != "OCDS"
                        for celda in hoja_infimas["A"]
                        if celda.value is not None
                    ),
                    "ninguna fila de la hoja de ínfimas es del portal de ofertas",
                )

            _seccion("7. Sin resultados también sale un archivo válido")
            r = await c.get(
                "/v1/registros/exportacion",
                params={"termino": "zzz-termino-inventado-zzz", "desde": desde},
                headers=cab_admin,
            )
            _marca(r.status_code == 200, f"con un término que no existe -> {r.status_code}")
            if r.status_code == 200:
                vacio = load_workbook(io.BytesIO(r.content))
                hojas_datos = [n for n in vacio.sheetnames if n != NOMBRE_HOJA_CRITERIOS]
                _marca(
                    all(vacio[n].max_row == 1 for n in hojas_datos),
                    f"las hojas de datos solo llevan la cabecera: {hojas_datos}",
                )

            #
            # La ventana de la descarga: es la única regla de este guion que **rechaza** en lugar de
            # servir, así que se comprueban las tres fronteras. Rechazar y no recortar es lo que
            # mantiene la propiedad que defiende todo lo de arriba —el archivo y la tabla no pueden
            # discrepar—: a un archivo recortado en silencio le faltarían filas sin decirlo.
            #
            # El código de estado del rechazo es **422** y no 400: en este proyecto `DatoInvalido`
            # —una petición bien formada que no se puede atender— viaja como 422, y el 400 queda
            # para los errores del dominio que no son de datos (`app.py`).
            _seccion("7b. La descarga se limita a los últimos meses")
            r = await c.get(
                "/v1/registros/exportacion",
                params={"termino": TERMINO_DE_PRUEBA, "modo": "cualquiera"},
                headers=cab_admin,
            )
            _marca(r.status_code == 422, f"sin fecha inicial -> {r.status_code}")
            _marca(desde in r.text, f"el mensaje dice desde cuándo se puede: {desde}")

            # Un día antes del límite: fuera por poco, que es el caso que un redondeo se llevaría.
            un_dia_antes = (inicio_exportable() - timedelta(days=1)).isoformat()
            r = await c.get(
                "/v1/registros/exportacion",
                params={**filtros, "desde": un_dia_antes},
                headers=cab_admin,
            )
            _marca(r.status_code == 422, f"con {un_dia_antes} -> {r.status_code}")

            # Y exactamente en el límite entra: la ventana es «desde», no «después de».
            r = await c.get(
                "/v1/registros/exportacion",
                params={**filtros, "desde": desde},
                headers=cab_admin,
            )
            _marca(r.status_code == 200, f"con {desde} -> {r.status_code}")

            _seccion("8. Un rol de solo lectura no exporta")
            r = await c.post(
                "/v1/usuarios",
                json={
                    "email": correo_lector,
                    "contrasena": clave_lector,
                    "rol": "lector",
                    "nombre": "Lector",
                },
                headers=cab_admin,
            )
            _marca(
                r.status_code in (200, 201), f"crear una cuenta de solo lectura -> {r.status_code}"
            )
            usuario_lector = r.json().get("usuario", {}).get("usuario_id")

            # Una cuenta recién creada **no tiene ninguna vista**: el acceso se concede aparte,
            # usuario por usuario. Sin este paso el lector no pasaría ni de la tabla, y entonces la
            # comprobación no distinguiría «no puede exportar» de «no puede ver nada», que son cosas
            # muy distintas: la primera es la que se quiere demostrar.
            for vista in ("necesidades", "contrataciones"):
                r = await c.post(
                    f"/v1/accesos/usuarios/{usuario_lector}/vistas",
                    json={"vista": vista, "plazo": "1a"},
                    headers=cab_admin,
                )
                _marca(
                    r.status_code == 201,
                    f"conceder la vista «{vista}» al lector -> {r.status_code}",
                )

            cab_lector = await _entrar(c, correo_lector, clave_lector)
            r = await c.get("/v1/registros", params={**filtros, "tamano": 1}, headers=cab_lector)
            _marca(r.status_code == 200, f"el lector sí ve la tabla -> {r.status_code}")
            r = await c.get("/v1/registros/exportacion", params=filtros, headers=cab_lector)
            _marca(r.status_code == 403, f"pero no exporta -> {r.status_code}")
            if r.status_code == 403:
                print(f"  mensaje: {r.json().get('mensaje') or r.json().get('detail')}")

            _seccion("9. Sin sesión no hay descarga")
            r = await c.get("/v1/registros/exportacion", params=filtros)
            _marca(r.status_code == 401, f"GET sin token -> {r.status_code}")
    finally:
        await _borrar_empresa(negocio)
        print("\nempresa temporal borrada")

    print(f"\n{'=' * 66}")
    if FALLOS:
        print(f"FALLARON {len(FALLOS)} COMPROBACIONES:")
        for fallo in FALLOS:
            print(f"  - {fallo}")
        raise SystemExit(1)
    print("Todas las comprobaciones pasaron.")


if __name__ == "__main__":
    asyncio.run(main())
