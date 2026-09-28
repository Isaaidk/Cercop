"""Enrutador de registro de empresas.

Es el único enrutador del sistema **sin autenticación**, y esa condición obliga a tres cosas.

**Nada de lo que entra se da por bueno.** Un formulario abierto a internet recibe, en cuestión de
horas, todo lo que alguien quiera mandarle. Todas las comprobaciones viven en el caso de uso y en el
dominio, y este enrutador no decide ninguna: solo traduce.

**La respuesta no revela si un correo tiene cuenta.** Cuando el correo ya está en uso se
responde con un `400` y un mensaje explícito, porque en un registro eso es inevitable: hay
que decirle a la persona que no puede seguir. Lo que sí se evita es cualquier otro camino que
permita enumerar correos sin registrarse; por eso no hay un endpoint de «¿está libre este
correo?», que sería exactamente eso.

**No se emiten tokens.** El registro crea la cuenta y la persona entra iniciando sesión.
Fabricar una sesión aquí abriría un segundo camino de autenticación, y los segundos caminos
son los que se olvidan de comprobar algo.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from contratacion.aplicacion.casos_uso.registrar_empresa import registrar_empresa, requisitos
from contratacion.dominio.serializacion import cuerpo_json
from contratacion.infraestructura.adaptadores.entrada.http.dependencias import (
    ConsentimientosDep,
    ContrasenasDep,
    NegociosDep,
    PoliticasDep,
)

router = APIRouter(prefix="/v1/registro", tags=["Registro"])


class AltaDeEmpresa(BaseModel):
    """Datos del formulario de registro.

    Las longitudes declaradas aquí son solo un primer filtro para no procesar un cuerpo absurdo: la
    comprobación de verdad —el dígito verificador del RUC, la forma del correo, la política de la
    contraseña— está en el dominio, y se aplica aunque esta capa no la declare. Duplicarla aquí
    crearía dos versiones de la misma y la de aquí sería la que se quede atrás.
    """

    nombre: str = Field(
        max_length=160,
        description="Razón social o nombre con el que se conoce a la empresa.",
        examples=["Constructora del Pacífico Cía. Ltda."],
    )
    admin_email: str = Field(
        max_length=254,
        description="Correo de quien administrará la empresa. Será su usuario para entrar.",
        examples=["gerencia@constructora.ec"],
    )
    contrasena: str = Field(
        max_length=128,
        description="Contraseña del administrador. Requisitos en /v1/registro/requisitos.",
    )
    admin_nombre: str | None = Field(
        default=None,
        max_length=120,
        description="Nombre de la persona. Si se omite, se usa el correo.",
    )
    ruc: str | None = Field(
        default=None,
        max_length=20,
        description="RUC de la empresa. Opcional, pero se valida su dígito verificador si viene.",
    )
    email_contacto: str | None = Field(
        default=None, max_length=254, description="Correo de contacto de la empresa."
    )
    telefono: str | None = Field(
        default=None, max_length=20, description="Teléfono de contacto de la empresa."
    )
    direccion: str | None = Field(default=None, max_length=200)
    ciudad: str | None = Field(default=None, max_length=80)


@router.get(
    "/requisitos", summary="Qué exige el registro: política de contraseñas y prueba inicial"
)
async def ver_requisitos() -> dict[str, Any]:
    """Lo que el formulario necesita saber antes de enviar nada.

    Se sirve desde el servidor para que el formulario no tenga que adivinar la política. Uno
    que dice «mínimo 8 caracteres» mientras el servidor exige 12 rechaza lo que acaba de dar por
    bueno, y ese es un fallo que se descubre justo al terminar de rellenarlo todo.
    """
    return requisitos()


@router.post(
    "/empresa",
    status_code=status.HTTP_201_CREATED,
    summary="Registrar una empresa y su administrador",
)
async def crear_empresa(
    cuerpo: AltaDeEmpresa,
    negocios: NegociosDep,
    contrasenas: ContrasenasDep,
    politicas: PoliticasDep,
    consentimientos: ConsentimientosDep,
) -> dict[str, Any]:
    """Da de alta la empresa, su administrador y una prueba de las vistas.

    Quien firma el registro queda como **administrador de su propia empresa**: puede crear usuarios,
    asignarles contraseña y darles de baja. La cuenta nace activa y con una prueba de las vistas, de
    modo que al entrar hay datos que ver; sin eso, el panel recién registrado aparecería vacío y
    parecería roto.

    La empresa nace en estado `prueba`. El estado no limita nada por sí solo: lo que limita son las
    vistas concedidas y sus vencimientos, que es donde vive el modelo de suscripción.
    """
    resultado = await registrar_empresa(
        nombre_empresa=cuerpo.nombre,
        admin_email=cuerpo.admin_email,
        contrasena=cuerpo.contrasena,
        admin_nombre=cuerpo.admin_nombre,
        ruc=cuerpo.ruc,
        email_contacto=cuerpo.email_contacto,
        telefono=cuerpo.telefono,
        direccion=cuerpo.direccion,
        ciudad=cuerpo.ciudad,
        negocios=negocios,
        contrasenas=contrasenas,
        politicas=politicas,
        consentimientos=consentimientos,
    )
    return cuerpo_json(resultado.como_diccionario())
