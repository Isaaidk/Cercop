"""Enrutador de gestión de cuentas de la empresa.

Va aparte de `/v1/accesos`, que es donde se conceden las vistas, porque son dos cosas distintas con
dos públicos distintos: aquí se decide **quién entra**, allí **qué ve** quien ya entra.
Mezclarlas en el mismo prefijo haría que una lista de rutas que empiezan igual significara dos
cosas.

La forma de las rutas sigue una regla que conviene notar: **ninguna operación destructiva se
hace con `DELETE` salvo el borrado de verdad**. Dar de baja es `POST .../baja` porque es
reversible y crea un estado —`inactivo`—, no porque se borre algo. El borrado real sí es
`DELETE`, y exige confirmación.
Si las dos fueran `DELETE`, la que se equivoca de botón en la interfaz borraría pruebas de
consentimiento, que es justo lo que no se puede recuperar.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

from contratacion.aplicacion.casos_uso.gestionar_usuarios import (
    crear_cuenta,
    desactivar_cuenta,
    eliminar_cuenta,
    listar_cuentas,
    reactivar_cuenta,
    restablecer_contrasena,
)
from contratacion.dominio.serializacion import cuerpo_json
from contratacion.infraestructura.adaptadores.entrada.http.dependencias import (
    ActorDep,
    AuditoriaDep,
    CierreSesionesDep,
    ConsentimientoDep,
    ConsentimientosDep,
    ContrasenasDep,
    NegociosDep,
    PoliticasDep,
    UsuariosDep,
)

router = APIRouter(prefix="/v1/usuarios", tags=["Usuarios"])


class AltaDeCuenta(BaseModel):
    """Cuerpo para crear una cuenta."""

    email: str = Field(max_length=254, examples=["compras@empresa.ec"])
    contrasena: str = Field(
        max_length=128,
        description=(
            "Contraseña inicial, la elige quien crea la cuenta. Debe cumplir la misma política que "
            "se exige al registrarse; los requisitos se consultan en /v1/registro/requisitos."
        ),
    )
    rol: str = Field(
        default="consultor",
        description="admin_negocio, consultor o lector. Superadministrador no se asigna aquí.",
        examples=["consultor"],
    )
    nombre: str | None = Field(default=None, max_length=120)


class ReactivacionDeCuenta(BaseModel):
    """Datos opcionales al reactivar. Si no se envían, la cuenta vuelve como estaba."""

    nombre: str | None = Field(default=None, max_length=120)
    rol: str | None = Field(default=None)
    contrasena: str | None = Field(default=None, max_length=128)


class CambioDeContrasena(BaseModel):
    """Contraseña nueva que fija un administrador para otra cuenta."""

    contrasena: str = Field(max_length=128)


@router.get("", summary="Cuentas de la empresa, con el margen del plan")
async def listar(
    actor: ActorDep,
    usuarios: UsuariosDep,
    negocios: NegociosDep,
    _: ConsentimientoDep,
    inactivos: Annotated[bool, Query(description="Incluir las cuentas dadas de baja.")] = True,
) -> dict[str, Any]:
    """Devuelve las cuentas y, junto a ellas, cuántas plazas quedan y los roles asignables.

    Las tres cosas en la misma respuesta porque el panel las necesita a la vez: para decidir si
    muestra el botón de crear hace falta el margen, y para construirlo, los roles. Pedirlas
    por separado daría tres fotos de instantes distintos.

    Las cuentas dadas de baja se incluyen por defecto: son las que hay que poder reactivar, y
    esconderlas obligaría a adivinar que existen.
    """
    resumen = await listar_cuentas(
        actor, usuarios=usuarios, negocios=negocios, incluir_inactivos=inactivos
    )
    return cuerpo_json(resumen.como_diccionario())


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Crear una cuenta con una contraseña elegida por el administrador",
)
async def crear(
    cuerpo: AltaDeCuenta,
    actor: ActorDep,
    usuarios: UsuariosDep,
    negocios: NegociosDep,
    contrasenas: ContrasenasDep,
    politicas: PoliticasDep,
    consentimientos: ConsentimientosDep,
    auditoria: AuditoriaDep,
    _: ConsentimientoDep,
) -> dict[str, Any]:
    """Crea una cuenta activa en la empresa de quien llama.

    La cuenta nace activa y con la contraseña ya puesta: la persona puede entrar en cuanto se la
    comuniquen. Al entrar por primera vez tendrá que aceptar los términos y condiciones, y esa
    la aplica el servidor igual que para cualquier otro usuario.
    """
    resultado = await crear_cuenta(
        actor,
        email=cuerpo.email,
        nombre=cuerpo.nombre,
        rol_codigo=cuerpo.rol,
        contrasena=cuerpo.contrasena,
        usuarios=usuarios,
        negocios=negocios,
        contrasenas=contrasenas,
        politicas=politicas,
        consentimientos=consentimientos,
        auditoria=auditoria,
    )
    return cuerpo_json(resultado.como_diccionario())


@router.post("/{usuario_id}/baja", summary="Dar de baja una cuenta (reversible)")
async def dar_de_baja(
    usuario_id: UUID,
    actor: ActorDep,
    usuarios: UsuariosDep,
    sesiones: CierreSesionesDep,
    auditoria: AuditoriaDep,
    _: ConsentimientoDep,
) -> dict[str, Any]:
    """Desactiva la cuenta y cierra sus sesiones.

    **No borra nada**, y esa es la diferencia con el `DELETE` de más abajo: conserva el registro de
    que esa persona aceptó los términos y condiciones, la prueba que el sistema tiene que
    enseñar. Es reversible.
    """
    resultado = await desactivar_cuenta(
        actor, usuario_id=usuario_id, usuarios=usuarios, sesiones=sesiones, auditoria=auditoria
    )
    return cuerpo_json(resultado.como_diccionario())


@router.post("/{usuario_id}/reactivacion", summary="Volver a habilitar una cuenta dada de baja")
async def reactivar(
    usuario_id: UUID,
    cuerpo: ReactivacionDeCuenta,
    actor: ActorDep,
    usuarios: UsuariosDep,
    negocios: NegociosDep,
    contrasenas: ContrasenasDep,
    auditoria: AuditoriaDep,
    _: ConsentimientoDep,
) -> dict[str, Any]:
    """Reactiva la cuenta, opcionalmente con nombre, rol y contraseña nuevos.

    Existe para que la baja sea de verdad reversible. Sin esta ruta, recuperar a alguien obligaría a
    crear otra cuenta con el mismo correo, y el índice único la rechazaría sin explicar por qué.
    """
    resultado = await reactivar_cuenta(
        actor,
        usuario_id=usuario_id,
        usuarios=usuarios,
        negocios=negocios,
        contrasenas=contrasenas,
        auditoria=auditoria,
        nombre=cuerpo.nombre,
        rol_codigo=cuerpo.rol,
        contrasena=cuerpo.contrasena,
    )
    return cuerpo_json(resultado.como_diccionario())


@router.delete("/{usuario_id}", summary="Borrar una cuenta definitivamente")
async def borrar(
    usuario_id: UUID,
    actor: ActorDep,
    usuarios: UsuariosDep,
    sesiones: CierreSesionesDep,
    auditoria: AuditoriaDep,
    _: ConsentimientoDep,
    confirmacion: Annotated[
        str,
        Query(
            min_length=3,
            description=(
                "Correo de la cuenta que se va a borrar, escrito a mano. Es la confirmación de que "
                "se sabe qué se está destruyendo."
            ),
        ),
    ],
) -> dict[str, Any]:
    """Borra la cuenta **y su registro de aceptación de los términos**, en cascada.

    Es la única operación que destruye evidencia, y por eso exige escribir el correo de la
    cuenta como confirmación. Nada de un botón que se pulsa sin leer: si no coincide, no se borra.

    Si lo que se quiere es que alguien deje de entrar, la operación correcta es `baja`, que es
    reversible y no pierde nada.
    """
    resultado = await eliminar_cuenta(
        actor,
        usuario_id=usuario_id,
        usuarios=usuarios,
        sesiones=sesiones,
        auditoria=auditoria,
        confirmacion=confirmacion,
    )
    return cuerpo_json(resultado.como_diccionario())


@router.post("/{usuario_id}/contrasena", summary="Asignar una contraseña nueva a otra cuenta")
async def fijar_contrasena(
    usuario_id: UUID,
    cuerpo: CambioDeContrasena,
    actor: ActorDep,
    usuarios: UsuariosDep,
    sesiones: CierreSesionesDep,
    contrasenas: ContrasenasDep,
    auditoria: AuditoriaDep,
    _: ConsentimientoDep,
) -> dict[str, Any]:
    """Restablece la contraseña y **cierra todas las sesiones de esa cuenta**.

            Cerrarlas es la mitad del valor de la operación: el caso que la justifica es «creo que
    alguien ha entrado en esa cuenta», y si la sesión intrusa siguiera viva, el cambio de
    contraseña no habría servido para nada. También cierra las legítimas, y se avisa en la
    respuesta para que
            quien lo hace sepa que tendrá que dar la contraseña nueva.
    """
    resultado = await restablecer_contrasena(
        actor,
        usuario_id=usuario_id,
        contrasena=cuerpo.contrasena,
        usuarios=usuarios,
        sesiones=sesiones,
        contrasenas=contrasenas,
        auditoria=auditoria,
    )
    return cuerpo_json(resultado.como_diccionario())
