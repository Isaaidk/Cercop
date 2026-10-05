"""Factoría de la aplicación HTTP.

Concentra el armado del adaptador de entrada: middleware, enrutadores, traducción de errores y ciclo
de vida. No contiene reglas de negocio.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from contratacion.dominio.errores import (
    ConsentimientoPendiente,
    DatoInvalido,
    EmpresaSuspendida,
    ErrorDominio,
    EstadoInvalido,
    NoEncontrado,
    SesionRevocada,
    SinPermiso,
)
from contratacion.infraestructura.adaptadores.entrada.http.routers import (
    accesos,
    autenticacion,
    busqueda,
    cpc,
    ingestas,
    negocios,
    plantilla,
    plataforma,
    politicas,
    presencia,
    salud,
    terminos,
    usuarios,
)

# El enrutador de registro se importa con otro nombre a propósito: este módulo tiene una variable
# `registro` que es el registro de sucesos, y `from ... import registro` la sobrescribiría con el
# módulo del enrutador. El resultado no sería un error de importación sino algo peor: las llamadas a
# `registro.info(...)` de este archivo dejarían de escribir en el registro, en silencio, y se
# convertirían en un acceso a un atributo de un módulo de rutas.
from contratacion.infraestructura.adaptadores.entrada.http.routers import (
    registro as registro_router,
)
from contratacion.infraestructura.adaptadores.salida.bd.sesion import cerrar_bd, verificar_bd
from contratacion.infraestructura.adaptadores.salida.cache.cliente import (
    cerrar_cache,
    verificar_cache,
)
from contratacion.infraestructura.adaptadores.salida.presencia.fabrica import cerrar_presencia
from contratacion.infraestructura.config.ajustes import Ajustes, obtener_ajustes

TITULO = "API Contratación Pública — Plataforma Multi-Tenant"
VERSION = "0.3.0"

registro = logging.getLogger(__name__)

# Traducción de las reglas de negocio a códigos HTTP. El dominio no conoce HTTP, así que la decisión
# de «qué código corresponde a este error» vive aquí, en un solo sitio y a la vista.
CODIGOS_POR_ERROR: tuple[tuple[type[ErrorDominio], int], ...] = (
    # Los dos son 403, y el código del cuerpo es lo que los distingue: uno pide permiso al
    # administrador y el otro pide aceptar los términos. Sin esa distinción, la interfaz mostraría
    # el mismo mensaje para las dos cosas y mandaría al usuario a resolver el problema equivocado.
    (ConsentimientoPendiente, status.HTTP_403_FORBIDDEN),
    (SinPermiso, status.HTTP_403_FORBIDDEN),
    # 403 y no 401: la sesión es válida y la contraseña también; lo que está cerrado es la empresa.
    # Volver a entrar no arregla nada y el aviso lo dice, así que mandar un 401 solo serviría para
    # que el cliente intentara renovar y reintentar en un bucle.
    (EmpresaSuspendida, status.HTTP_403_FORBIDDEN),
    (NoEncontrado, status.HTTP_404_NOT_FOUND),
    (EstadoInvalido, status.HTTP_409_CONFLICT),
    (DatoInvalido, status.HTTP_422_UNPROCESSABLE_ENTITY),
    # 401 y no 403: la sesión no está y hay que volver a entrar. El 401 además hace que el cliente
    # sepa que reintentar con el mismo token no sirve de nada.
    (SesionRevocada, status.HTTP_401_UNAUTHORIZED),
)


@asynccontextmanager
async def _ciclo_vida(app: FastAPI) -> AsyncIterator[None]:
    """Comprueba las dependencias al arrancar y libera recursos al apagar."""
    hay_bd = await verificar_bd()
    hay_cache = await verificar_cache()
    registro.info("Arranque: postgres=%s redis=%s", hay_bd, hay_cache)
    if not hay_bd or not hay_cache:
        registro.warning(
            "Alguna dependencia no responde; /listo devolverá 503 hasta que esté disponible."
        )
    yield
    await cerrar_presencia()
    await cerrar_cache()
    await cerrar_bd()


async def _manejador_de_dominio(peticion: Request, exc: Exception) -> JSONResponse:
    """Convierte un error de negocio en una respuesta HTTP.

    El mensaje del dominio se devuelve tal cual porque está escrito para que lo lea una persona: los
    errores de este sistema explican qué pasó y qué hacer, no exponen detalles internos.

    Se añade además el `codigo` del error. El mensaje es para mostrar y puede reescribirse; el
    código es para decidir, y hay casos en los que dos errores comparten el mismo estado HTTP.
    """
    codigo = status.HTTP_400_BAD_REQUEST
    for tipo, candidato in CODIGOS_POR_ERROR:
        if isinstance(exc, tipo):
            codigo = candidato
            break
    registro.info("Error de dominio en %s: %s", peticion.url.path, exc)
    cuerpo: dict[str, Any] = {"detail": str(exc), "codigo": getattr(exc, "codigo", "error")}
    # El motivo de la revocación solo lo lleva `SesionRevocada`, y la interfaz lo necesita para
    # contar bien lo que pasó: no es lo mismo «cerraste la sesión» que «otra persona entró con tu
    # cuenta». Se añade cuando existe en vez de mandar siempre un campo nulo.
    motivo = getattr(exc, "motivo", None)
    if motivo:
        cuerpo["motivo"] = motivo
    return JSONResponse(status_code=codigo, content=cuerpo)


def crear_app(ajustes: Ajustes | None = None) -> FastAPI:
    """Construye la aplicación. Acepta ajustes explícitos para facilitar las pruebas."""
    configuracion = ajustes or obtener_ajustes()

    aplicacion = FastAPI(
        title=TITULO,
        version=VERSION,
        lifespan=_ciclo_vida,
    )
    aplicacion.state.ajustes = configuracion

    # Orígenes exactos desde configuración. Nunca comodín con credenciales (vulnerabilidad V1).
    aplicacion.add_middleware(
        CORSMiddleware,
        allow_origins=configuracion.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        # Sin esto, el navegador deja leer la respuesta pero **no** sus cabeceras, y las dos que
        # importan para la exportación son cabeceras: `Content-Disposition` trae el nombre del
        # archivo y `X-Contenido-Filas` cuántas contrataciones lleva. Con un origen distinto al de
        # la API —que es como se despliega— el panel descargaría un archivo llamado «descarga» y no
        # podría decir cuántas filas se llevó. Se listan una a una en lugar de usar `*` porque la
        # lista es la documentación de qué se expone.
        expose_headers=["Content-Disposition", "X-Contenido-Filas"],
    )

    aplicacion.add_exception_handler(ErrorDominio, _manejador_de_dominio)

    aplicacion.include_router(salud.router)
    aplicacion.include_router(autenticacion.router)
    # El registro va antes que los demás y sin autenticación: es la puerta de entrada a todo lo
    # demás. No lleva la comprobación de consentimiento, porque aceptar los términos es justo lo que
    # se hace después de entrar por primera vez.
    aplicacion.include_router(registro_router.router)
    aplicacion.include_router(politicas.router)
    aplicacion.include_router(presencia.router)
    aplicacion.include_router(busqueda.router)
    aplicacion.include_router(plantilla.router)
    aplicacion.include_router(terminos.router)
    aplicacion.include_router(cpc.router)
    aplicacion.include_router(ingestas.router)
    aplicacion.include_router(accesos.router)
    aplicacion.include_router(usuarios.router)
    aplicacion.include_router(negocios.router)
    aplicacion.include_router(plataforma.router)
    return aplicacion
