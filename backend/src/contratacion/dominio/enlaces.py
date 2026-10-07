"""Enlaces al proceso original en el portal de la fuente.

El panel muestra el identificador de cada contratación —«NIC-1768120280001-2022-00003»—, pero lo que
alguien necesita cuando lo ve es **abrir esa ficha en el portal del SERCOP**: comprobar el estado,
leer el objeto de compra completo, descargar el documento. Copiar el código y volver a buscarlo a
mano en otro sitio es el paso que sobra.

Hay **dos** formas de llegar a esa dirección, y ninguna es inventar.

La primera es la que la fuente publica dentro del propio registro. La fuente NCO trae un enlace
**relativo** (`../NCO/NCORegistroDetalle.cpe?&id=...`) escrito para leerse desde la página de
listado del portal; aquí se convierte en absoluto con `urljoin` contra la dirección desde la que se
descargó el dato, que es la base correcta por construcción. Comprobado contra el portal, la
dirección resultante abre la ficha y contiene el código de la contratación.

La segunda es la de la fuente OCDS, que **no publica ninguna dirección** —se comprobó campo por
campo: la API devuelve `id`, `ocid`, año, mes, método, tipo, localidad, región, proveedores,
comprador, importe, fecha, título y descripción, y ninguna URL—. Lo que sí trae es el `ocid`, que es
el identificador con el que el propio portal abre el proceso: su buscador de procedimientos usa
`.../PLATAFORMA/ocds/<ocid>`. Medido el 2026-10-06 con un `ocid` real de la base, esa dirección
devuelve la ficha completa —objeto, entidad, etapas, presupuesto—; y `.../datos-abiertos/proceso/
<ocid>`, que es la que componía el sistema anterior, devuelve **404**, que es el defecto que se
está arreglando aquí. La diferencia entre las dos está en la ruta, no en el identificador.

Lo que sigue sin hacerse es inventar una dirección para un dato que no la admite: si la fuente no
publica enlace y el registro no trae identificador de proceso, no hay enlace. Un enlace roto es peor
que no tener enlace: quien lo pulsa cree que el proceso no existe, cuando lo que no existe es la
dirección que nos hemos inventado.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urljoin

# Solo se ofrecen enlaces http y https. No es una formalidad: el valor viene de una página externa,
# y un `javascript:` o un `data:` en un `href` pintado tal cual sería una vía de ejecución.
ESQUEMAS_PERMITIDOS = ("http://", "https://")

# La ruta del buscador de procedimientos del portal, con la que se abre un proceso por su `ocid`.
PORTAL_OCDS = "https://datosabiertos.compraspublicas.gob.ec/PLATAFORMA/ocds/"

# Un `ocid` es un identificador, no una ruta: se acepta solo lo que puede formar parte de un
# segmento de dirección, y se exige que empiece por letra o número. No es un formalismo; si el valor
# trajera una barra o un interrogante, la dirección compuesta apuntaría a otro sitio y el panel
# ofrecería un enlace roto, que es peor que no ofrecer ninguno.
PATRON_OCID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~:-]*$")


def enlace_ocds(ocid: str | None) -> str | None:
    """URL del proceso en el buscador de procedimientos del portal, o `None`.

    No es una dirección inventada: el `ocid` es el identificador que emite el propio portal y la
    ruta es la suya. Lo que no se hace es componerla con un dato que no sea un identificador, y por
    eso el valor se comprueba antes: con una barra dentro, la dirección apuntaría a otro sitio y el
    enlace saldría roto.
    """
    if not ocid:
        return None
    valor = str(ocid).strip()
    if not PATRON_OCID.match(valor):
        return None
    return f"{PORTAL_OCDS}{valor}"


def enlace_del_registro(elemento: Mapping[str, Any], base: str | None) -> str | None:
    """El enlace al proceso, venga de donde venga.

    Se prueba primero lo que **publica la fuente** —es lo que la fuente eligió, y sigue valiendo si
    un día cambia de ruta— y, si no hay, la dirección compuesta con el identificador. El orden deja
    el resultado igual cuando la fuente publica enlace, así que no habrá que tocar nada el día que
    una fuente deje de publicarlo.
    """
    publicado = enlace_publico(elemento.get("enlace"), base)
    if publicado:
        return publicado
    return enlace_ocds(elemento.get("ocid"))


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
