"""Quién ejecuta un caso de uso.

El actor se construye **siempre** a partir del token verificado, nunca a partir de un parámetro de
la petición. Es la regla R-04: el `negocio_id` no lo elige el cliente.

En la fase 3.5 el actor llega ya resuelto hasta los casos de uso; la fase 4 añadirá el adaptador que
lo extrae del JWT. Mantenerlo aquí, en la capa de aplicación, evita que la lógica de autorización
dependa de FastAPI o de cualquier framework web.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from contratacion.dominio.acceso import puede_gestionar
from contratacion.dominio.errores import SinPermiso
from contratacion.dominio.roles import puede_exportar


@dataclass(frozen=True, slots=True)
class Actor:
    """Usuario que ejecuta la operación, con su ámbito."""

    usuario_id: UUID
    negocio_id: UUID
    rol: str

    def exigir_administrativo(self) -> None:
        """Comprueba que el actor puede gestionar accesos de otros usuarios."""
        if not puede_gestionar(self.rol):
            raise SinPermiso("El rol de este usuario no puede conceder ni retirar accesos.")

    def exigir_exportador(self) -> None:
        """Comprueba que el actor puede descargar el histórico.

        Va aparte de `exigir_administrativo` porque no es lo mismo: un consultor exporta y no
        administra cuentas, y un lector administra nada y tampoco exporta. Se pregunta por la
        capacidad concreta y no por el rol, para que la lista de quién puede hacer qué siga viviendo
        en un solo sitio.
        """
        if not puede_exportar(self.rol):
            raise SinPermiso(
                "Tu rol puede consultar las contrataciones en pantalla, pero no descargarlas. "
                "Pídele al administrador de tu empresa un rol con permiso de exportación."
            )
