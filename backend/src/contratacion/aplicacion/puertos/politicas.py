"""Puertos de políticas y consentimientos.

Son **dos** puertos porque viven en planos distintos del sistema, y confundirlos sería un error de
aislamiento serio:

- Las **políticas** son globales: el mismo texto rige para todos los negocios. Su tabla no lleva
  `negocio_id` y no está sujeta a RLS. Publicar una versión nueva afecta a todo el mundo.
- Los **consentimientos** son de cada persona y de cada negocio. Su tabla sí lleva `negocio_id` y
  está protegida por políticas: la aceptación de un usuario de una empresa no puede verse, ni
  contarse, ni modificarse desde otra.

Un solo puerto con métodos de las dos cosas invitaría a escribir la consulta de consentimientos sin
contexto de negocio, y esa consulta devolvería cero filas sin dar ningún error.

El marcador `usuario.debe_aceptar_politica_version`
--------------------------------------------------
Es un valor **materializado**, no una copia. Solo lo escriben las dos operaciones que pueden
cambiarlo, y cada transición tiene un único escritor:

- publicar una versión nueva → se marca la versión pendiente a todas las cuentas;
- aceptar → se limpia el marcador de esa cuenta.

Se materializa porque la puerta de bloqueo lo consulta en cada petición y no puede permitirse
componer el estado desde dos tablas cada vez. Y como todo valor materializado puede desviarse, hay
una prueba que comprueba que coincide con el estado derivado: si alguna vez deja de coincidir, la
prueba lo dice en lugar de que lo descubra un usuario al que no se le pidió aceptar nada.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from contratacion.dominio.politicas import Consentimiento, Politica, TipoPolitica


class RepositorioPoliticas(Protocol):
    """Versiones publicadas de los textos legales. Plano compartido."""

    async def vigentes(self) -> Sequence[Politica]:
        """Todas las políticas con su versión más alta. Son pocas y se leen juntas."""
        ...

    async def vigente(self, tipo: TipoPolitica) -> Politica | None:
        """La última versión publicada de un texto. `None` si todavía no se publicó ninguna."""
        ...

    async def publicar(self, *, tipo: TipoPolitica, texto: str, momento: datetime) -> Politica:
        """Publica el texto como la versión siguiente y devuelve lo publicado.

        El número de versión lo decide el repositorio, sumando uno a la última: si lo decidiera
        quien llama, dos publicaciones simultáneas podrían reutilizar el mismo número y una de las
        dos quedaría sin publicar en silencio.

        La huella se calcula aquí, sobre el texto que se acaba de guardar. Calcularla en otro sitio
        dejaría abierta la posibilidad de guardar un texto y registrar la huella de otro.
        """
        ...

    async def marcar_pendientes(self, *, tipo: TipoPolitica, version: int) -> int:
        """Marca el texto como pendiente en **todas** las cuentas. Devuelve cuántas se marcaron.

        Es lo que obliga a re-aceptar al publicar una versión nueva. Va sobre todas las cuentas y no
        solo las activas: alguien que vuelva dentro de un mes tiene que encontrarse la aceptación
        pendiente, no entrar directamente con una aceptación de la versión anterior.
        """
        ...


class RepositorioConsentimientos(Protocol):
    """Aceptaciones y revocaciones. Plano de negocio, protegido por RLS."""

    async def registrar(
        self,
        *,
        negocio_id: UUID,
        usuario_id: UUID,
        tipo: TipoPolitica,
        version: int,
        hash_texto: str,
        momento: datetime,
        ip: str | None = None,
        user_agent: str | None = None,
        metodo: str = "formulario",
    ) -> UUID:
        """Registra una aceptación con su evidencia.

        Se guarda **la huella del texto**, no solo la versión. Es lo que permite demostrar cuál de
        las redacciones se aceptó el día que se aceptó, aunque después se haya corregido el texto
        sin cambiar el número de versión.
        """
        ...

    async def del_usuario(self, *, negocio_id: UUID, usuario_id: UUID) -> Sequence[Consentimiento]:
        """Historial completo de una cuenta: aceptaciones y revocaciones, en orden.

        Devuelve también las revocadas. El historial es la prueba de lo que ocurrió, así que no se
        filtra: quien lo consulte decide qué mirar.
        """
        ...

    async def revocar(
        self, *, negocio_id: UUID, usuario_id: UUID, tipo: TipoPolitica, momento: datetime
    ) -> int:
        """Retira el consentimiento. Devuelve cuántas aceptaciones quedaron revocadas.

        Retirar el consentimiento es un derecho, no una comodidad: la fila **no se borra**, se marca
        como revocada y con su fecha. Borrarla destruiría la prueba de que existió, que es justo lo
        que hay que poder demostrar.
        """
        ...

    async def pendiente_de(self, *, negocio_id: UUID, usuario_id: UUID) -> int | None:
        """Versión que esa cuenta tiene pendiente de aceptar, o `None` si no debe ninguna.

        Es la lectura que hace la puerta de bloqueo: una sola consulta a una columna de la propia
        fila del usuario, en el camino de todas las peticiones.
        """
        ...

    async def marcar_pendiente(self, *, negocio_id: UUID, usuario_id: UUID, version: int) -> None:
        """Marca una sola cuenta como pendiente de aceptar la versión indicada.

        Se usa al **retirar** el consentimiento: quien lo retira deja de poder usar el aplicativo, y
        eso se expresa volviendo a poner el bloqueo, no con una bandera aparte.
        """
        ...

    async def limpiar_pendiente(self, *, negocio_id: UUID, usuario_id: UUID) -> None:
        """Quita el marcador de pendiente de esa cuenta.

        Se llama al aceptar. La operación no comprueba nada: la decisión de si la aceptación valía
        ya se tomó antes, en el caso de uso, contra el texto publicado.
        """
        ...
