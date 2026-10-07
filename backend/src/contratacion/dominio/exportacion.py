"""Desde cuándo se puede descargar el histórico en un archivo.

La descarga es la operación más cara del sistema y la única que **no se puede paginar**. Una
consulta del panel lee veinticinco filas de una página; una exportación lee todo lo que cumpla los
filtros, lo recorre entero, arma un libro con una hoja por familia y lo serializa en memoria antes
de enviarlo. Con el histórico completo —110.000 registros y 574 MB, de los que 180 son de `TOAST`—
eso son minutos de base de datos ocupada, memoria del proceso del API y un archivo que quien lo abre
casi nunca necesita entero: lo que se exporta es para trabajarlo **este trimestre**.

Por eso la descarga cubre como mucho los últimos **tres meses** de fecha de publicación.

Por qué «rechazar» y no «recortar»
----------------------------------
Recortar en silencio sería peor que no hacer nada: el archivo dejaría de coincidir con lo que hay
en pantalla, y esa coincidencia —el archivo trae exactamente las filas que se están viendo— es la
propiedad que se documentó y se probó cuando se añadieron los filtros a la exportación. Quien
recibe un archivo no tiene forma de saber que le falta lo que había antes del recorte. Así que la
petición se **rechaza** con el motivo y con la fecha desde la que sí se puede: la persona puede
volver a pedirlo bien en un clic, y nadie se queda con un archivo que miente.

La ventana se mide sobre la fecha de **publicación**, que es el criterio que el panel ofrece y el
que la descarga respeta. Una exportación sin fecha inicial abarcaría el histórico entero y por eso
también se rechaza: la respuesta dice exactamente qué fecha hay que poner.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from contratacion.dominio.acceso import momento_local
from contratacion.dominio.errores import DatoInvalido
from contratacion.dominio.plazos import sumar_meses

# Meses de histórico que cubre una descarga. Tres es lo que se trabaja de una vez —un trimestre—
# y lo que mantiene la consulta dentro de un rango de fechas con índice.
MESES_EXPORTABLES = 3


def inicio_exportable(momento: datetime | None = None) -> date:
    """Fecha de publicación más antigua que se puede descargar.

    Se cuenta en **meses de calendario** y en la zona del negocio, no en días ni en UTC: el panel
    filtra por días naturales de Ecuador, así que un límite calculado en otro huso dejaría fuera el
    primer día de la ventana para quien lo pidiera de madrugada. Es la misma cuenta que la de los
    plazos de las vistas, por eso está en un solo sitio.
    """
    instante = momento or datetime.now(UTC)
    return momento_local(sumar_meses(instante, -MESES_EXPORTABLES)).date()


def revisar_ventana(desde: date | None, *, momento: datetime | None = None) -> date:
    """Comprueba que la descarga no se remonte más allá de la ventana. Devuelve su límite.

    `desde` es la fecha inicial **aplicada** en el panel. Sin fecha, la descarga abarcaría todo el
    histórico y también se rechaza: no hay forma de saber por dónde empezar, así que se pide que se
    diga, en lugar de adivinar un rango que quizá no sea el que se quería.
    """
    limite = inicio_exportable(momento)
    if desde is None:
        raise DatoInvalido(
            f"La descarga cubre como mucho los últimos {MESES_EXPORTABLES} meses, para no cargar "
            f"el servidor con el histórico entero. Pon una fecha inicial a partir del "
            f"{limite.isoformat()} y vuelve a intentarlo."
        )
    if desde < limite:
        raise DatoInvalido(
            f"La descarga cubre como mucho los últimos {MESES_EXPORTABLES} meses: desde el "
            f"{limite.isoformat()}. Para lo anterior, acota por palabras clave, CPC o provincia —o "
            f"consúltalo en pantalla— y vuelve a intentarlo."
        )
    return limite
