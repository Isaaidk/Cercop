"""Enrutador de la administración de la plataforma.

Va aparte de `/v1/negocio` —que es «los datos de mi empresa»— porque son dos cosas distintas y con
dueños distintos: allí una empresa se describe a sí misma, aquí el dueño del sistema decide sobre
las demás. Juntarlos dejaría rutas que empiezan igual y significan lo contrario, que es justo lo que
no se quiere leer con prisa.

Todos los endpoints exigen el rol de plataforma. La comprobación vive en el caso de uso y no aquí:
la regla es de negocio —«solo el dueño del sistema administra empresas ajenas»— y debe negarse igual
desde la API, desde el worker o desde una tarea programada.
"""

from __future__ import annotations

import asyncio
import time
from typing import Annotated, Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Query, Request, status
from pydantic import BaseModel, Field

from contratacion.aplicacion.casos_uso.administrar_negocios import (
    desbloquear_cuenta_en_empresa,
    eliminar_cuenta_de_empresa,
    eliminar_empresa,
    listar_empresas,
    reactivar_empresa,
    restablecer_contrasena_en_empresa,
    suspender_empresa,
)
from contratacion.aplicacion.casos_uso.operar_ingesta import solicitar_ciclo, tablero_ingesta
from contratacion.dominio.errores import SinPermiso
from contratacion.dominio.roles import Rol
from contratacion.dominio.serializacion import cuerpo_json
from contratacion.infraestructura.adaptadores.entrada.http.dependencias import (
    ActorDep,
    AuditoriaDep,
    CacheDep,
    CierreSesionesDep,
    ConsultasDep,
    ContrasenasDep,
    NegociosDep,
    UsuariosDep,
)
from contratacion.infraestructura.adaptadores.entrada.http.proteccion import ip_cliente

router = APIRouter(prefix="/v1/plataforma", tags=["Plataforma"])


@router.get("/empresas", summary="Todas las empresas registradas")
async def empresas(actor: ActorDep, negocios: NegociosDep) -> dict[str, Any]:
    """El censo de empresas: identidad, estado y cuántas cuentas tiene cada una.

    No lleva la puerta de consentimiento a propósito. Esa puerta protege datos de contratación de
    terceros; esto es la lista de clientes de la plataforma, y quien la pide ya ha aceptado los
    términos para poder entrar. Añadirla aquí no protegería nada nuevo y sí dejaría al dueño del
    sistema sin poder ver sus empresas si su propia aceptación caducara.
    """
    fichas = await listar_empresas(actor, repositorio=negocios)
    return cuerpo_json({"empresas": [ficha.como_diccionario() for ficha in fichas]})


_PRUEBAS_DE_SALIDA = (
    (
        "Portal: listado de necesidades (NCO)",
        "https://www.compraspublicas.gob.ec/ProcesoContratacion/compras/NCO/FrmNCOListado.cpe",
    ),
    (
        "Portal: ingreso al sistema",
        "https://www.compraspublicas.gob.ec/ProcesoContratacion/compras/",
    ),
    (
        "Datos abiertos (OCDS)",
        "https://datosabiertos.compraspublicas.gob.ec/PLATAFORMA/api/search_ocds?year=2025&page=1",
    ),
)


@router.get("/eco-ip", summary="Cómo ve el servidor la IP de quien llama (diagnóstico)")
async def eco_ip(actor: ActorDep, peticion: Request) -> dict[str, Any]:
    """Cabeceras de proxy tal como llegan y la IP que usa el freno. Solo el superadministrador.

    Sirve para comprobar `PROXY_SALTOS` en el despliegue: si la IP calculada es la del proxy de la
    plataforma y no la del cliente, el freno de inicio de sesión se reparte entre todos.
    """
    if str(actor.rol) != Rol.SUPER_ADMIN.value:
        raise SinPermiso("Solo el superadministrador puede ver este diagnóstico.")
    cliente = peticion.client.host if peticion.client else None
    return {
        "client_host": cliente,
        "x_forwarded_for": peticion.headers.getlist("x-forwarded-for"),
        "x_real_ip": peticion.headers.get("x-real-ip"),
        "ip_para_el_freno": ip_cliente(peticion),
    }


@router.get("/salida-portal", summary="¿Llega este servidor al portal de compras públicas?")
async def salida_portal(actor: ActorDep) -> dict[str, Any]:
    """Prueba, desde el propio servidor, la salida directa (sin proxy) hacia el portal.

    Responde la pregunta de la que depende la descarga de TDR en el despliegue: si el portal acepta
    conexiones desde la IP del servidor o las corta. Solo el superadministrador.
    """
    if str(actor.rol) != Rol.SUPER_ADMIN.value:
        raise SinPermiso("Solo el superadministrador puede probar la salida al portal.")
    resultados: list[dict[str, Any]] = []
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(20.0), follow_redirects=False, headers={"User-Agent": "Mozilla/5.0"}
    ) as cliente:
        for nombre, url in _PRUEBAS_DE_SALIDA:
            inicio = time.monotonic()
            try:
                # Tope total por prueba: un servidor que corta a las IP que no quiere puede mandar
                # los datos a cuentagotas, y un tope entre lecturas nunca salta.
                respuesta = await asyncio.wait_for(cliente.get(url), timeout=15.0)
                resultados.append(
                    {
                        "prueba": nombre,
                        "estado": respuesta.status_code,
                        "bytes": len(respuesta.content),
                        "segundos": round(time.monotonic() - inicio, 2),
                    }
                )
            except (httpx.HTTPError, TimeoutError) as exc:
                resultados.append(
                    {
                        "prueba": nombre,
                        "error": type(exc).__name__,
                        "segundos": round(time.monotonic() - inicio, 2),
                    }
                )
    return {"salida": "directa", "resultados": resultados}


@router.get("/ingesta/historial", summary="Lo que han trabajado los workers")
async def historial_ingesta(
    actor: ActorDep, consultas: ConsultasDep, cache: CacheDep
) -> dict[str, Any]:
    """El último ciclo de cada fuente, la serie de los últimos y la petición que esté pendiente.

    Se lee de `sincronizacion`, que es donde los ciclos ya se registran para poder auditarse: ver el
    trabajo del worker no exige instrumentar nada nuevo, solo enseñar lo que ya se escribe.

    Va **antes** que las rutas con `{negocio_id}` por la norma de la casa —FastAPI resuelve en orden
    de declaración— aunque hoy no colisionen, para que añadir mañana `/ingesta/{algo}` no convierta
    esta ruta en un 404 sin que nadie entienda por qué.

    No lleva la puerta de consentimiento, por la misma razón que `/empresas`: esto es operación del
    sistema, no datos de contratación de terceros, y su dueño no debería quedarse ciego si su propia
    aceptación caduca. El rol sí se exige, y se exige en el caso de uso.
    """
    return cuerpo_json(await tablero_ingesta(actor, repositorio=consultas, cache=cache))


@router.post(
    "/ingesta/solicitud",
    status_code=status.HTTP_201_CREATED,
    summary="Pedir un ciclo de ingesta ahora",
)
async def ordenar_ciclo(
    actor: ActorDep, cache: CacheDep, auditoria: AuditoriaDep
) -> dict[str, Any]:
    """Deja pedido un ciclo completo. Lo ejecuta el worker, no el API.

    Aquí no se ingesta nada: escribir desde el API sería hablar con el SERCOP desde una petición de
    usuario, que es lo que prohíben R-01 y CU-07, y además dejaría la petición HTTP abierta durante
    minutos. Esto solo deja la petición donde el worker la ve, y contesta en cuanto está escrita,
    para que el panel pueda decir «en cola» y refrescar hasta verla arrancar.

    Se anota en la auditoría: el ciclo deja su propia fila en `sincronizacion`, pero ahí no consta
    quién lo ordenó, y «quién pidió ingerir» es la pregunta que se hace cuando una ejecución
    inesperada aparece en el registro.
    """
    peticion = await solicitar_ciclo(actor, cache=cache)
    await auditoria.auditar(
        accion="ingesta.solicitud",
        negocio_id=actor.negocio_id,
        usuario_id=actor.usuario_id,
        entidad="ingesta",
        resultado="pendiente",
        detalle=peticion.como_diccionario(),
    )
    return cuerpo_json({"solicitud": peticion.como_diccionario()})


@router.post(
    "/empresas/{negocio_id}/suspension",
    status_code=status.HTTP_201_CREATED,
    summary="Suspender el acceso de una empresa",
)
async def suspender(
    negocio_id: UUID,
    actor: ActorDep,
    negocios: NegociosDep,
    auditoria: AuditoriaDep,
) -> dict[str, Any]:
    """Corta el acceso de una empresa entera.

    Sus usuarios dejan de poder leer nada y ven **solo** el aviso de suspensión. No se borra nada:
    suspender es reversible y tiene que seguir siéndolo.
    """
    resultado = await suspender_empresa(
        actor,
        negocio_id=negocio_id,
        repositorio=negocios,
        auditoria=auditoria,
    )
    return cuerpo_json(resultado.como_diccionario())


@router.post(
    "/empresas/{negocio_id}/reactivacion",
    status_code=status.HTTP_201_CREATED,
    summary="Devolver el acceso a una empresa",
)
async def reactivar(
    negocio_id: UUID,
    actor: ActorDep,
    negocios: NegociosDep,
    auditoria: AuditoriaDep,
) -> dict[str, Any]:
    """Devuelve el acceso. Las vistas que la empresa tuviera concedidas siguen donde estaban."""
    resultado = await reactivar_empresa(
        actor,
        negocio_id=negocio_id,
        repositorio=negocios,
        auditoria=auditoria,
    )
    return cuerpo_json(resultado.como_diccionario())


@router.delete("/empresas/{negocio_id}", summary="Eliminar una empresa y sus cuentas")
async def eliminar(
    negocio_id: UUID,
    actor: ActorDep,
    confirmacion: Annotated[
        str,
        Query(
            min_length=3,
            description=(
                "Nombre de la empresa, escrito a mano. Es la única forma de que un borrado "
                "irreversible no ocurra por un clic de más."
            ),
        ),
    ],
    negocios: NegociosDep,
    usuarios: UsuariosDep,
    sesiones: CierreSesionesDep,
    auditoria: AuditoriaDep,
) -> dict[str, Any]:
    """Retira la empresa con sus cuentas, sus accesos y su plantilla. **No se deshace.**

    Va como `DELETE` y no como un `POST` con la palabra «borrar» dentro por la misma razón por la
    que el nombre se pide en la dirección y no en el cuerpo: aquí no hay un recurso que se crea. Lo
    que ocurre es que deja de existir, y eso no se parece a nada más de este enrutador.

    Lo que **no** se lleva: el histórico de contratación —es de la plataforma, no de la empresa,
    y borrar un cliente no puede restar datos a los demás— ni la auditoría, que sobrevive para
    poder decir quién lo hizo. Y no se puede pedir sobre la empresa propia: quien lo hace se queda
    fuera del sistema sin forma de volver.
    """
    resultado = await eliminar_empresa(
        actor,
        negocio_id=negocio_id,
        repositorio=negocios,
        usuarios=usuarios,
        sesiones=sesiones,
        auditoria=auditoria,
        confirmacion=confirmacion,
    )
    return cuerpo_json(resultado.como_diccionario())


@router.delete(
    "/empresas/{negocio_id}/usuarios/{usuario_id}",
    summary="Eliminar una cuenta de una empresa",
)
async def eliminar_usuario(
    negocio_id: UUID,
    usuario_id: UUID,
    actor: ActorDep,
    confirmacion: Annotated[
        str,
        Query(
            min_length=3,
            description="Correo de la cuenta, escrito a mano.",
        ),
    ],
    usuarios: UsuariosDep,
    sesiones: CierreSesionesDep,
    auditoria: AuditoriaDep,
) -> dict[str, Any]:
    """Retira una cuenta concreta de cualquier empresa. **No se deshace.**

    Es el mismo borrado que puede hacer un administrador con su propia gente, ejercido desde la
    plataforma sobre una empresa ajena. Se conserva la regla de que una empresa no puede quedarse
    sin administradores: sin ninguno no podría volver a gestionar sus cuentas desde dentro, y para
    retirarla entera está el borrado de la empresa.
    """
    resultado = await eliminar_cuenta_de_empresa(
        actor,
        negocio_id=negocio_id,
        usuario_id=usuario_id,
        usuarios=usuarios,
        sesiones=sesiones,
        auditoria=auditoria,
        confirmacion=confirmacion,
    )
    return cuerpo_json(resultado.como_diccionario())


class ContrasenaTemporal(BaseModel):
    """Contraseña temporal que fija la plataforma para una cuenta de otra empresa."""

    contrasena: str = Field(max_length=128)


@router.post(
    "/empresas/{negocio_id}/usuarios/{usuario_id}/contrasena",
    summary="Asignar una contraseña temporal a una cuenta de cualquier empresa",
)
async def fijar_contrasena_usuario(
    negocio_id: UUID,
    usuario_id: UUID,
    cuerpo: ContrasenaTemporal,
    actor: ActorDep,
    usuarios: UsuariosDep,
    sesiones: CierreSesionesDep,
    contrasenas: ContrasenasDep,
    auditoria: AuditoriaDep,
) -> dict[str, Any]:
    """La persona tendrá que cambiarla al entrar. Se cierran todas sus sesiones."""
    resultado = await restablecer_contrasena_en_empresa(
        actor,
        negocio_id=negocio_id,
        usuario_id=usuario_id,
        contrasena=cuerpo.contrasena,
        usuarios=usuarios,
        sesiones=sesiones,
        contrasenas=contrasenas,
        auditoria=auditoria,
    )
    return cuerpo_json(resultado.como_diccionario())


@router.post(
    "/empresas/{negocio_id}/usuarios/{usuario_id}/desbloqueo",
    summary="Quitar el bloqueo por intentos fallidos de una cuenta de cualquier empresa",
)
async def desbloquear_usuario(
    negocio_id: UUID,
    usuario_id: UUID,
    actor: ActorDep,
    usuarios: UsuariosDep,
    auditoria: AuditoriaDep,
) -> dict[str, Any]:
    """Es la salida cuando el bloqueado es el único administrador de su empresa."""
    resultado = await desbloquear_cuenta_en_empresa(
        actor,
        negocio_id=negocio_id,
        usuario_id=usuario_id,
        usuarios=usuarios,
        auditoria=auditoria,
    )
    return cuerpo_json(resultado.como_diccionario())
