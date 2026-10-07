"""Puerto de persistencia de las empresas.

Sobre el método de alta, y por qué hace tres cosas a la vez
---------------------------------------------------------
`crear` escribe en tres tablas: la empresa, su administrador y las vistas de prueba. Podría parecer
que la frontera correcta es una operación por tabla y que la coordinación le toca a una unidad de
trabajo. Se descartó por un motivo concreto: **una empresa sin administrador no sirve para nada y no
se puede arreglar desde la interfaz**. Nadie puede entrar, porque para entrar hay que ser
usuario de ella. Lo mismo con una empresa cuyo administrador existe pero no tiene ninguna vista: se
puede entrar, pero el panel aparece vacío y no hay forma de concedérselas desde dentro.

Es decir, los tres datos no son tres pasos de un proceso: son un único hecho. Que se escriban en una
transacción es la forma de que ese hecho exista completo o no exista.

El precio es que este puerto conoce las vistas, que no son cosa suya. Se acepta a cambio de que la
alternativa —una unidad de trabajo expuesta hacia arriba— obligue a cada caso de uso a acordarse de
abrir la transacción correctamente, y ese «acordarse» es lo que un día se olvida.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from contratacion.dominio.acceso import Plazo, Vista
from contratacion.dominio.negocios import DatosEmpresa
from contratacion.dominio.roles import Rol


@dataclass(frozen=True, slots=True)
class NegocioGuardado:
    """Una empresa tal y como está registrada."""

    negocio_id: UUID
    nombre: str
    ruc: str | None
    estado: str
    plan: str
    limite_usuarios: int
    email_contacto: str | None
    telefono: str | None
    direccion: str | None
    ciudad: str | None
    creado_en: datetime

    @property
    def activo(self) -> bool:
        """¿Puede entrar gente de esta empresa?

        «Prueba» cuenta como activo: es el estado con el que nace una empresa recién registrada y
        negarle el paso dejaría el registro inservible. Los estados que sí cierran la puerta son
        suspensión, cancelación y eliminación programada.
        """
        return self.estado in {"prueba", "activo"}

    def como_diccionario(self) -> dict[str, Any]:
        """Datos de la empresa para el panel. No incluye nada de su facturación ni de su plan."""
        return {
            "negocio_id": str(self.negocio_id),
            "nombre": self.nombre,
            "ruc": self.ruc,
            "estado": self.estado,
            "plan": self.plan,
            "limite_usuarios": self.limite_usuarios,
            "email_contacto": self.email_contacto,
            "telefono": self.telefono,
            "direccion": self.direccion,
            "ciudad": self.ciudad,
            "creado_en": self.creado_en.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class AltaEmpresa:
    """Todo lo que se escribe de una vez al registrar una empresa.

    El rol del primer usuario es un dato y no una constante del adaptador porque hay dos altas
    distintas: la del formulario público, que crea un administrador de empresa, y la de la línea de
    órdenes, que crea el superadministrador de la plataforma. Compartiendo el mismo camino se
    garantiza que las dos dejan la empresa y su primera cuenta en el mismo estado consistente; si
    fueran dos caminos, el segundo sería el que se olvide de conceder la prueba o de fijar el
    contexto de negocio.
    """

    negocio_id: UUID
    datos: DatosEmpresa
    admin_id: UUID
    admin_email: str
    admin_nombre: str
    admin_rol: Rol
    huella: str
    vistas_prueba: Sequence[Vista]
    plazo_prueba: Plazo
    momento: datetime


@dataclass(frozen=True, slots=True)
class EmpresaDePlataforma:
    """Una empresa vista desde la plataforma, con el tamaño de su plantilla.

    Es una ficha distinta de `NegocioGuardado` a propósito. Esta la lee el dueño del sistema para
    decidir a quién dar acceso y a quién suspender, así que necesita cosas que la empresa no ve de
    sí misma —cuántas cuentas tiene— y **ninguna** de las que no debe ver: no hay correos de sus
    usuarios, ni sus nombres, ni sus datos de contacto personales. Solo el tamaño de la plantilla y
    el estado de la empresa.
    """

    negocio_id: UUID
    nombre: str
    ruc: str | None
    estado: str
    plan: str
    limite_usuarios: int
    email_contacto: str | None
    telefono: str | None
    direccion: str | None
    ciudad: str | None
    creado_en: datetime
    cuentas: int
    cuentas_activas: int

    @property
    def activa(self) -> bool:
        """¿Puede entrar su gente? Mismo criterio que `NegocioGuardado.activo`."""
        return self.estado in {"prueba", "activo"}

    def como_diccionario(self) -> dict[str, Any]:
        return {
            "negocio_id": str(self.negocio_id),
            "nombre": self.nombre,
            "ruc": self.ruc,
            "estado": self.estado,
            "activa": self.activa,
            "plan": self.plan,
            "limite_usuarios": self.limite_usuarios,
            "email_contacto": self.email_contacto,
            "telefono": self.telefono,
            "direccion": self.direccion,
            "ciudad": self.ciudad,
            "creado_en": self.creado_en.isoformat(),
            "cuentas": self.cuentas,
            "cuentas_activas": self.cuentas_activas,
        }


class RepositorioNegocios(Protocol):
    """Lectura y escritura de las empresas."""

    async def listar(self) -> Sequence[EmpresaDePlataforma]:
        """**Todas** las empresas, para el panel de la plataforma.

        Es la única lectura del sistema que cruza negocios, y por eso el `SELECT` vive en una
        función `SECURITY DEFINER` que devuelve una lista de columnas fija y cerrada. La
        alternativa —quitar RLS de `negocio` o conectarse con un rol que se salte RLS— anularía el
        aislamiento de esta tabla o de todas, según cuál se eligiera.
        """
        ...

    async def cambiar_estado(self, *, negocio_id: UUID, estado: str, momento: datetime) -> None:
        """Suspende o reactiva una empresa.

        A diferencia de `listar`, esta sí puede atravesar RLS por la puerta: se fija el contexto de
        negocio al de la propia empresa que se está modificando, y la política `id = contexto` deja
        pasar el `UPDATE`.
        """
        ...

    async def eliminar(self, *, negocio_id: UUID) -> None:
        """Retira una empresa y **todo** lo que cuelga de ella.

        Es la operación más destructiva del sistema y no se deshace. Se lleva las cuentas, sus
        sesiones, sus concesiones de vistas, sus conjuntos de términos, sus exportaciones, su
        plantilla de Excel y su registro de aceptación de los términos.

        Lo que **no** toca: el histórico de contratación, que es de la plataforma y no de la empresa
        —borrar un cliente no puede restar datos a los demás—, y la auditoría, que sobrevive a
        propósito para poder decir quién lo hizo.

        Atraviesa RLS por la misma puerta que `cambiar_estado`: el contexto se fija al negocio que
        se borra, y las acciones referenciales de las claves ajenas no pasan por las políticas.
        """
        ...

    async def crear(self, alta: AltaEmpresa) -> UUID:
        """Registra la empresa, su administrador y las vistas de prueba, todo o nada.

        El identificador lo genera quien llama, no la base de datos, y no es un detalle: al crear
        la empresa hay que fijar el contexto de negocio **antes** de insertar sus primeras filas, y
        para eso hace falta conocer el identificador de antemano.

        Es la pieza que permite que el alta atraviese el aislamiento sin debilitarlo. Las políticas
        comparan `negocio_id` con el contexto, así que una inserción sin contexto se rechaza; si el
        contexto apunta al identificador que se acaba de generar, la comprobación pasa por sí sola y
        no hace falta ni abrir la tabla ni una función con privilegios elevados.
        """
        ...

    async def obtener(self, *, negocio_id: UUID) -> NegocioGuardado | None:
        """Datos de la empresa. `None` si el contexto no da acceso a ella."""
        ...

    async def actualizar_datos(
        self, *, negocio_id: UUID, datos: DatosEmpresa, momento: datetime
    ) -> None:
        """Sustituye los datos de contacto. El nombre, el RUC y el estado no se tocan desde aquí."""
        ...

    async def resumen_uso(self, *, negocio_id: UUID) -> dict[str, Any]:
        """Cuántos usuarios activos hay y cuántos admite el plan, para que el panel avise a tiempo.

        Los dos números viajan juntos porque el que se enseña solo no dice nada: «3 usuarios» es
        tranquilizador o alarmante según el límite, y el límite vive en la fila de la empresa.
        """
        ...
