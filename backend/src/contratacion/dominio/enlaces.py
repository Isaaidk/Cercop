"""Enlaces al proceso original en el portal de la fuente.

El panel muestra el identificador de cada contratación —«NIC-1768120280001-2022-00003»—, pero lo que
alguien necesita cuando lo ve es **abrir esa ficha en el portal del SERCOP**: comprobar el estado,
leer el objeto de compra completo, descargar el documento. Copiar el código y volver a buscarlo a
mano en otro sitio es el paso que sobra.

Lo que no se puede hacer es inventar la dirección. La fuente NCO publica, dentro del propio
registro, un enlace **relativo** (`../NCO/NCORegistroDetalle.cpe?&id=...`) escrito para leerse desde
la página de listado del portal. Aquí se convierte en absoluto con `urljoin` contra la dirección
desde la que se descargó el dato, que es la base correcta por construcción: el enlace es relativo a
esa página porque es ahí donde la fuente lo escribe. Comprobado contra el portal, la dirección
resultante abre la ficha y contiene el código de la contratación.

Las fuentes que **no** publican enlace se quedan sin él, y es deliberado. La fuente OCDS trae `ocid`
e `id`, pero ninguna dirección; componer una a partir del identificador daría una URL con pinta de
buena que llevaría a una página de error. Un enlace roto es peor que no tener enlace: quien lo pulsa
que el proceso no existe, cuando lo que no existe es la dirección que nos hemos inventado.
"""

from __future__ import annotations

from urllib.parse import urljoin

# Solo se ofrecen enlaces http y https. No es una formalidad: el valor viene de una página externa,
# y un `javascript:` o un `data:` en un `href` pintado tal cual sería una vía de ejecución.
ESQUEMAS_PERMITIDOS = ("http://", "https://")


def enlace_publico(relativo: str | None, base: str | None) -> str | None:
    """URL absoluta del proceso, o `None` si no se puede construir con seguridad.

    `base` es la dirección de la que se descargó el dato —el `endpoint` de la fuente— y `relativo`
    es lo que la propia fuente publica en el registro.

    Se devuelve `None` en tres casos, y los tres importan:

    - **No hay enlace.** La fuente no lo publica; eso no es un error y no debe inventarse nada.
    - **El destino no es http o https.** Se descarta en lugar de ofrecerlo.
    - **El destino es relativo al protocolo** (`//otro-sitio/x`). `urljoin` lo resolvería como
      absoluto y el enlace apuntaría fuera del portal oficial. Se rechaza explícitamente en vez de
      confiar en que la fuente nunca lo haga.
    """
    if not relativo or not base:
        return None

    destino = str(relativo).strip()
    if not destino or destino.startswith(("#", "//")):
        return None

    # Un enlace que ya viene absoluto se respeta: la fuente puede cambiarlo cuando quiera.
    if destino.lower().startswith(ESQUEMAS_PERMITIDOS):
        return destino

    raiz = str(base).strip()
    if not raiz.lower().startswith(ESQUEMAS_PERMITIDOS):
        return None

    absoluto = urljoin(raiz, destino)
    # `urljoin` no valida el esquema del resultado: si el destino trae el suyo, manda el suyo.
    if not absoluto.lower().startswith(ESQUEMAS_PERMITIDOS):
        return None
    return absoluto
