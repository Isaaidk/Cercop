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

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, status

from contratacion.aplicacion.casos_uso.administrar_negocios import (
    eliminar_cuenta_de_empresa,
    eliminar_empresa,
    listar_empresas,
    reactivar_empresa,
    suspender_empresa,
)
from contratacion.aplicacion.casos_uso.operar_ingesta import solicitar_ciclo, tablero_ingesta
from contratacion.dominio.serializacion import cuerpo_json
from contratacion.infraestructura.adaptadores.entrada.http.dependencias import (
    ActorDep,
    AuditoriaDep,
    CacheDep,
    CierreSesionesDep,
    ConsultasDep,
    NegociosDep,
    UsuariosDep,
)

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
