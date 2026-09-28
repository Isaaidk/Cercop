"""Puerto de persistencia de los accesos a vistas.

Devuelve **objetos del dominio**, no filas: el adaptador es el único que conoce el esquema y la
conversión de los códigos de texto a los enumerados. Así una vista mal escrita en la base no puede
propagarse como un valor válido por la lógica de autorización.

Todas las operaciones llevan `negocio_id` explícito porque el aislamiento es por negocio y no por
usuario: dos negocios distintos pueden tener usuarios con el mismo identificador sólo si son el
mismo registro, pero la barrera debe ser explícita y quedar a la vista al leer el código.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from contratacion.dominio.acceso import AccesoVista, Plazo, Vista


class RepositorioAccesos(Protocol):
    """Concesiones de acceso a vistas."""

    async def conceder(
        self,
        *,
        negocio_id: UUID,
        usuario_id: UUID,
        vista: Vista,
        plazo: Plazo,
        otorgado_en: datetime,
        vence_en: datetime,
        otorgado_por: UUID,
    ) -> UUID:
        """Inserta una concesión. Extender es volver a llamar: añade una fila, no sobrescribe."""
        ...

    async def retirar(
        self,
        *,
        negocio_id: UUID,
        usuario_id: UUID,
        vista: Vista,
        momento: datetime,
        retirado_por: UUID,
    ) -> int:
        """Marca como retiradas todas las concesiones activas de ese par. Devuelve cuántas tocó."""
        ...

    async def obtener(self, *, negocio_id: UUID, usuario_id: UUID) -> Sequence[AccesoVista]:
        """Todas las concesiones de un usuario, vigentes o no: el dominio decide cuáles valen."""
        ...

    async def historial(
        self, *, negocio_id: UUID, usuario_id: UUID, limite: int = 100
    ) -> Sequence[Mapping[str, Any]]:
        """Concesiones y retiradas en orden cronológico inverso, para auditar."""
        ...

    async def usuarios(self, *, negocio_id: UUID, limite: int = 200) -> Sequence[Mapping[str, Any]]:
        """Usuarios **registrados** del negocio, con su rol y su estado.

        No es lo mismo que «usuarios conectados»: la presencia vive en el caché y la resuelve la
        fase 4. Aquí solo están las cuentas que existen, que es lo que el administrador debe ver.
        """
        ...

    async def usuario(self, *, negocio_id: UUID, usuario_id: UUID) -> Mapping[str, Any] | None:
        """Datos mínimos de un usuario del negocio. `None` si no pertenece a él."""
        ...
