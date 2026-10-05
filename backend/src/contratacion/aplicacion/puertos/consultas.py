"""Puerto de consultas sobre los datos ya ingestados.

La aplicación describe **qué** necesita (una página de registros, el catálogo de filtros, las
estadísticas) y no **cómo** se obtiene. Gracias a eso los casos de uso se prueban con un doble en
memoria, sin base de datos, y cambiar el motor de almacenamiento no toca la lógica.

Todas las consultas se ejecutan dentro del contexto de negocio, que impone el aislamiento por RLS.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol

from contratacion.dominio.busqueda import Filtros


class RepositorioConsultas(Protocol):
    """Lecturas sobre el histórico ya ingestado."""

    async def buscar(self, filtros: Filtros) -> tuple[tuple[Mapping[str, Any], ...], int]:
        """Devuelve la página pedida y el total de coincidencias.

        El total se cuenta con los mismos criterios pero **sin** la ventana: es lo que permite al
        frontend mostrar «1 de 240» y calcular cuántas páginas hay.
        """
        ...

    async def catalogos(self) -> Mapping[str, Sequence[str]]:
        """Valores distintos de los campos filtrables, para poblar los desplegables."""
        ...

    async def todos(self, filtros: Filtros, limite: int) -> tuple[Mapping[str, Any], ...]:
        """Todas las filas que cumplen los filtros, sin paginar, hasta `limite`.

        Es lo que necesita la exportación: un archivo con la página que se está viendo no serviría
        de nada, porque el usuario pide «todo lo que sale con estos filtros». Va **con el mismo
        `WHERE`** que `buscar` —sale de la misma función— para que el archivo y la tabla no puedan
        contener conjuntos distintos.

        El orden es el de la consulta, no el de pantalla: `buscar` ordena por el criterio pedido y
        aquí se aplica el mismo, así que el archivo sale en el mismo orden que la tabla.

        `limite` no es una página: es una red de seguridad para que una exportación sin filtros no
        intente traer el histórico entero a memoria de una vez. Si se alcanza, quien llama lo sabe
        porque recibe exactamente ese número de filas.
        """
        ...

    async def estadisticas(self, filtros: Filtros) -> Mapping[str, Any]:
        """Agregados para la pestaña de gráficas, calculados sobre el resultado filtrado.

        Recibe los **mismos filtros que la búsqueda** y no solo la fuente. Es lo que hace que las
        gráficas y la tabla no puedan discrepar: si los totales ignoraran las palabras clave, el
        panel mostraría un reparto por provincia que no corresponde a lo que hay debajo, y el
        usuario no tendría forma de saber cuál de los dos números es el equivocado.

        La paginación y el orden no se tienen en cuenta: se resume todo lo que cumple los criterios.

        Las claves son un contrato de facto: `por_fuente`, `serie_mensual` y `por_provincia` son las
        gráficas, y **`por_fuente_sin_familia`** es el mismo conteo por fuente pero con la familia
        filtrada excluida. El caso de uso la convierte en los totales de cada pestaña —el número que
        se ve junto a «Ínfimas cuantías» y junto a «Ofertas»— y la retira de la respuesta, porque el
        panel no tiene por qué saber qué fuente alimenta cada familia. Si no se devuelve, los dos
        contadores salen en cero: se degrada, no se rompe.
        """
        ...

    async def estado_fuentes(self) -> Sequence[Mapping[str, Any]]:
        """Estado del último ciclo de cada fuente, para el tablero administrativo."""
        ...

    async def historial_sincronizaciones(self, por_fuente: int = 24) -> Sequence[Mapping[str, Any]]:
        """Los últimos ciclos de **cada** fuente, del más reciente al más antiguo.

        Es lo que dibuja la gráfica del trabajo de los workers: no el último ciclo —eso ya lo da
        `estado_fuentes`— sino la serie, para poder ver si la ingesta late, si un ciclo se quedó a
        medias o si uno de cada tres falla. Se piden por fuente y no un histórico global porque las
        dos fuentes tienen cadencias distintas y mezclarlas en la misma lista las desordenaría.
        """
        ...

    async def estado_fuente(self, codigo: str) -> Mapping[str, Any] | None:
        """Estado de una fuente concreta. `None` si no existe."""
        ...

    async def ultima_ingesta_de(self, terminos: Sequence[str]) -> datetime | None:
        """Momento de la ingesta más reciente de cualquiera de estos términos."""
        ...
