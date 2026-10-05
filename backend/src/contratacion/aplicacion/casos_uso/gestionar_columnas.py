"""Casos de uso: consultar y guardar las columnas que llevan las exportaciones de la empresa.

Misma regla que la plantilla, y por el mismo motivo: **solo un rol administrativo cambia lo que
sale de la empresa**. Aquí es menos vistoso —no se cambia el logo, sino las columnas— pero el
efecto es el mismo: si alguien con acceso de lectura pudiera quitar la columna del objeto de
compra, los archivos que la empresa manda a sus clientes saldrían sin la descripción de lo que se
compra, y quien los recibe no tendría forma de saber que falta. Consultar sí puede cualquiera: es
información sobre la configuración de la empresa, no un secreto.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.casos_uso.exportar_registros import revisar_columnas
from contratacion.aplicacion.puertos.exportacion import RepositorioColumnasExportacion


async def consultar(
    actor: Actor,
    *,
    repositorio: RepositorioColumnasExportacion,
) -> tuple[str, ...] | None:
    """Las columnas elegidas por la empresa, o `None` si nunca se eligió nada.

    Se devuelven las claves guardadas **sin filtrar por el catálogo actual**. Si una columna
    desapareciera del catálogo, la pantalla la enseñaría como desconocida en lugar de esconderla:
    es más fácil entender «esta columna ya no existe, quítala» que ver que la selección cambió sola.
    """
    guardada = await repositorio.obtener(negocio_id=actor.negocio_id)
    return None if guardada is None else guardada.columnas


async def guardar(
    actor: Actor,
    *,
    columnas: Sequence[str],
    repositorio: RepositorioColumnasExportacion,
    momento: datetime | None = None,
) -> tuple[str, ...]:
    """Reemplaza la selección de columnas de la empresa por la que se acaba de enviar.

    Una lista vacía significa «todas» y se guarda como tal. Es lo que hace el botón que deshace la
    selección, y distinguirlo de «no has elegido nada todavía» es lo que permite que la pantalla
    explique el estado sin adivinar.

    Las claves se validan contra el catálogo **antes** de escribir nada: una columna inventada sería
    una exportación silenciosamente incompleta, y el momento de avisar es este, no la descarga.
    """
    actor.exigir_administrativo()
    limpias = revisar_columnas(columnas)

    await repositorio.guardar(
        negocio_id=actor.negocio_id,
        columnas=limpias,
        actualizado_por=actor.usuario_id,
        momento=momento or datetime.now(UTC),
    )
    return limpias
