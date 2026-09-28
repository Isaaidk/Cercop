"""Caso de uso: registrar una empresa y su primer administrador.

Es la única operación del sistema que **crea un negocio**, y por eso tiene tres reglas que no
aparecen en ningún otro sitio.

**Quien se registra queda como administrador de su propia empresa.** No como «usuario pendiente de
aprobación»: el modelo de este producto es que cada empresa gestiona sus cuentas, y un registro que
dejara a alguien sin poder crear usuarios lo obligaría a escribir a soporte para el primer paso, que
es justo lo que el autoservicio viene a evitar.

**La contraseña se exige aquí y cumple la misma política que en el resto del sistema.** Podría
pensarse que en el alta conviene ser indulgente para no perder un registro. Es al contrario: es el
momento en el que más se puede hacer, porque la persona está delante y le importa. Dejarla pasar con
una contraseña que luego el panel rechazaría crearía una cuenta que no se puede volver a configurar
igual.

**La empresa recibe una prueba de las vistas.** Sin vistas, el panel que se acaba de abrir
está vacío y no hay manera de llenarlo desde dentro —concederlas es cosa del
superadministrador—, así que el registro parecería roto. La prueba es un vencimiento de
verdad, con su plazo, no una excepción: se ve en el mismo tablero de accesos que las
concesiones de pago y se renueva igual.

Lo que **no** hace este caso de uso, a propósito: no emite tokens. El registro crea la cuenta
y quien la creó entra por el camino normal, iniciando sesión. Fabricar una sesión aquí abriría
un segundo camino de autenticación, y los segundos caminos son los que se olvidan de comprobar
algo.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.casos_uso.consentimiento import marcar_lo_obligatorio_pendiente
from contratacion.aplicacion.puertos.negocios import (
    AltaEmpresa,
    NegocioGuardado,
    RepositorioNegocios,
)
from contratacion.aplicacion.puertos.politicas import (
    RepositorioConsentimientos,
    RepositorioPoliticas,
)
from contratacion.aplicacion.puertos.seguridad import ServicioContrasenas
from contratacion.dominio.acceso import Plazo, Vista
from contratacion.dominio.credenciales import (
    CARACTERES_DISTINTOS_MINIMOS,
    LONGITUD_MAXIMA,
    LONGITUD_MINIMA,
    validar_contrasena,
)
from contratacion.dominio.errores import DatoInvalido, NoEncontrado
from contratacion.dominio.negocios import (
    DatosEmpresa,
    construir_datos_empresa,
    limpiar_texto,
    validar_correo,
)
from contratacion.dominio.roles import Rol

registro = logging.getLogger(__name__)

# Plazo de la prueba inicial. Es un plazo de los que existen —treinta días— y no un número inventado
# para esta operación: así la concesión aparece en el mismo tablero que las demás y se puede renovar
# con el mismo botón, sin un caso especial que mantener.
PLAZO_PRUEBA = Plazo.D30

# Todas las vistas del catálogo. Se concede la lista entera a propósito: una prueba a medias
# hace que la persona no pueda saber si el producto le sirve, que es lo único que una prueba
# tiene que resolver.
VISTAS_DE_PRUEBA: tuple[Vista, ...] = tuple(Vista)

LONGITUD_MAXIMA_EMAIL = 254
LONGITUD_MAXIMA_NOMBRE_PERSONA = 120


@dataclass(frozen=True, slots=True)
class ResultadoRegistro:
    """Confirmación del alta, sin credenciales."""

    negocio_id: UUID
    admin_id: UUID
    email: str
    nombre_empresa: str
    vistas_prueba: tuple[str, ...]
    prueba_vence_en: datetime

    def como_diccionario(self) -> dict[str, Any]:
        return {
            "negocio_id": str(self.negocio_id),
            "admin_id": str(self.admin_id),
            "email": self.email,
            "nombre_empresa": self.nombre_empresa,
            "vistas_prueba": list(self.vistas_prueba),
            "prueba_vence_en": self.prueba_vence_en.isoformat(),
        }


def validar_nombre_persona(valor: str | None) -> str:
    """Nombre de la persona que se registra.

    Si no viene, se usa el correo. Es una decisión deliberada: pedir el nombre es razonable, pero
    bloquear el registro por no escribirlo, no. La dirección de correo ya identifica a la persona en
    el listado de usuarios, y se puede corregir después.
    """
    limpio = limpiar_texto(valor)
    if len(limpio) > LONGITUD_MAXIMA_NOMBRE_PERSONA:
        raise DatoInvalido(
            f"El nombre no puede superar {LONGITUD_MAXIMA_NOMBRE_PERSONA} caracteres."
        )
    return limpio


def requisitos() -> dict[str, Any]:
    """La política de contraseñas y las vistas de la prueba, para que el formulario las enseñe.

    Se sirve desde el dominio y no se escribe en el formulario por una razón concreta: la política
    vive en el código del servidor, y una copia en el frontend se queda atrás el día que se cambie.
    El formulario que dice «mínimo 8 caracteres» mientras el servidor exige 12 es un formulario que
    rechaza lo que acaba de considerar válido.
    """
    return {
        "contrasena": {
            "longitud_minima": LONGITUD_MINIMA,
            "longitud_maxima": LONGITUD_MAXIMA,
            "caracteres_distintos_minimos": CARACTERES_DISTINTOS_MINIMOS,
        },
        "vistas_prueba": [str(vista) for vista in VISTAS_DE_PRUEBA],
        "plazo_prueba": str(PLAZO_PRUEBA),
        "dias_prueba": 30,
    }


async def registrar_empresa(
    *,
    nombre_empresa: str | None,
    admin_email: str | None,
    contrasena: str | None,
    admin_nombre: str | None = None,
    ruc: str | None = None,
    email_contacto: str | None = None,
    telefono: str | None = None,
    direccion: str | None = None,
    ciudad: str | None = None,
    negocios: RepositorioNegocios,
    contrasenas: ServicioContrasenas,
    politicas: RepositorioPoliticas,
    consentimientos: RepositorioConsentimientos,
    vistas_prueba: tuple[Vista, ...] = VISTAS_DE_PRUEBA,
    plazo_prueba: Plazo = PLAZO_PRUEBA,
    momento: datetime | None = None,
) -> ResultadoRegistro:
    """Registra la empresa, su administrador y la prueba de las vistas.

    El orden de las comprobaciones está pensado para que el primer error que se vea sea el más útil:
    primero los datos de la empresa, después el correo y por último la contraseña. Al revés, alguien
    podría escribir una contraseña perfecta y descubrir al final que el RUC estaba mal.
    """
    datos: DatosEmpresa = construir_datos_empresa(
        nombre=nombre_empresa,
        ruc=ruc,
        email_contacto=email_contacto,
        telefono=telefono,
        direccion=direccion,
        ciudad=ciudad,
    )

    correo = validar_correo(admin_email, obligatorio=True)
    if len(correo) > LONGITUD_MAXIMA_EMAIL:
        raise DatoInvalido(f"El correo no puede superar {LONGITUD_MAXIMA_EMAIL} caracteres.")

    texto_contrasena = contrasena or ""
    # Se valida contra el correo para rechazar una contraseña que lo contenga: una clave que
    # lleva el propio correo es pública para cualquiera que lo conozca.
    validar_contrasena(texto_contrasena, email=correo)

    instante = momento or datetime.now(UTC)
    negocio_id = uuid4()
    admin_id = uuid4()

    alta = AltaEmpresa(
        negocio_id=negocio_id,
        datos=datos,
        admin_id=admin_id,
        admin_email=correo,
        admin_nombre=validar_nombre_persona(admin_nombre) or correo,
        admin_rol=Rol.ADMIN_NEGOCIO,
        huella=contrasenas.hash(texto_contrasena),
        vistas_prueba=vistas_prueba,
        plazo_prueba=plazo_prueba,
        momento=instante,
    )
    await negocios.crear(alta)

    # La cuenta nace debiendo aceptar los términos. Sin esta línea, el bloqueo no la vería: la
    # puerta lee el marcador de la cuenta, y el marcador solo se escribía al publicar una versión
    # de los términos, de modo que todas las cuentas creadas después de la última publicación
    # quedaban exentas. Ver `marcar_lo_obligatorio_pendiente`.
    await marcar_lo_obligatorio_pendiente(
        negocio_id=negocio_id,
        usuario_id=admin_id,
        politicas=politicas,
        consentimientos=consentimientos,
    )

    registro.info(
        "Empresa registrada desde el formulario: negocio=%s nombre=%r", negocio_id, datos.nombre
    )
    return ResultadoRegistro(
        negocio_id=negocio_id,
        admin_id=admin_id,
        email=correo,
        nombre_empresa=datos.nombre,
        vistas_prueba=tuple(str(vista) for vista in vistas_prueba),
        prueba_vence_en=plazo_prueba.calcular(instante),
    )


@dataclass(frozen=True, slots=True)
class FichaEmpresa:
    """Datos de la empresa más el margen del plan."""

    negocio: NegocioGuardado
    uso: dict[str, Any]

    def como_diccionario(self) -> dict[str, Any]:
        return {
            **self.negocio.como_diccionario(),
            "activo": self.negocio.activo,
            "uso": self.uso,
        }


async def consultar_empresa(actor: Actor, *, negocios: RepositorioNegocios) -> FichaEmpresa:
    """Datos de la propia empresa y cuántas plazas de usuario quedan.

    Se exige ser administrativo: los datos de contacto y el límite del plan son información de
    gestión, no de consulta, y un lector no tiene nada que hacer con ellos.
    """
    actor.exigir_administrativo()
    negocio = await negocios.obtener(negocio_id=actor.negocio_id)
    if negocio is None:
        raise NoEncontrado("La empresa de esta sesión ya no existe.")
    return FichaEmpresa(
        negocio=negocio, uso=await negocios.resumen_uso(negocio_id=actor.negocio_id)
    )


async def actualizar_empresa(
    actor: Actor,
    *,
    nombre_empresa: str | None,
    ruc: str | None = None,
    email_contacto: str | None = None,
    telefono: str | None = None,
    direccion: str | None = None,
    ciudad: str | None = None,
    negocios: RepositorioNegocios,
    momento: datetime | None = None,
) -> FichaEmpresa:
    """Cambia los datos de la propia empresa.

    Se permite corregir el nombre y el RUC porque al registrarse se escribe con prisa y una razón
    social mal tecleada es lo más habitual. Lo que **no** se puede cambiar desde aquí es el
    estado ni el plan: son decisiones de la plataforma, y dejar que el cliente se ampliara su
    propio límite convertiría el plan en una sugerencia.
    """
    actor.exigir_administrativo()
    datos = construir_datos_empresa(
        nombre=nombre_empresa,
        ruc=ruc,
        email_contacto=email_contacto,
        telefono=telefono,
        direccion=direccion,
        ciudad=ciudad,
    )
    instante = momento or datetime.now(UTC)
    await negocios.actualizar_datos(negocio_id=actor.negocio_id, datos=datos, momento=instante)

    negocio = await negocios.obtener(negocio_id=actor.negocio_id)
    if negocio is None:
        raise NoEncontrado("La empresa de esta sesión ya no existe.")
    registro.info("Datos de empresa actualizados: negocio=%s", actor.negocio_id)
    return FichaEmpresa(
        negocio=negocio, uso=await negocios.resumen_uso(negocio_id=actor.negocio_id)
    )
