"""Traducción del choque con el correo único a un error de dominio.

Vive en su propio archivo porque lo necesitan **dos** adaptadores: el de usuarios, cuando un
administrador crea una cuenta, y el de negocios, cuando alguien se registra desde el formulario
público. Tenerlo duplicado sería peor que tenerlo aquí: son tres piezas —el nombre del índice,
el detector y el mensaje— que tienen que decir lo mismo en los dos sitios, y basta con que una
de las dos copias se quede atrás para que uno de los dos caminos devuelva un error interno en
vez de una explicación.

Por qué se detecta por el nombre del índice y no por el texto del mensaje
-----------------------------------------------------------------------
El texto del error de PostgreSQL cambia entre versiones, cambia con el idioma del servidor y cambia
según por cuántas capas haya pasado el error. El nombre de la restricción, en cambio, lo elegimos
nosotros en la migración 0007 y no cambia solo.

Y por qué no se comprueba antes de insertar
------------------------------------------
Porque entre la comprobación y la inserción cabe otra petición. Dos registros simultáneos con
el mismo correo pasarían los dos la comprobación previa; el índice único no los deja pasar. Es
decir: la comprobación previa daría una falsa tranquilidad y habría que hacerla igualmente. Se
intenta insertar y se traduce el fallo, que es lo único que no tiene carreras.
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError

# Nombre del índice único que hace que un correo no pueda pertenecer a dos empresas. Tiene que
# coincidir con el de la migración 0007: si allí se renombrara y aquí no, el correo repetido dejaría
# de traducirse y saldría como un error interno.
INDICE_CORREO_GLOBAL = "ux_usuario_email_global"

MENSAJE_CORREO_EN_USO = (
    "Ese correo ya tiene una cuenta en la plataforma. Un correo solo puede pertenecer a una "
    "empresa: si quieres usar esta cuenta aquí, pide que la den de baja en la otra."
)


def es_correo_repetido(error: IntegrityError) -> bool:
    """¿El fallo de integridad es la unicidad del correo?

    Se comprueban las dos formas que puede tomar según el controlador y según cuántas capas haya
    atravesado el error: el atributo `constraint_name`, que es la forma correcta, y el nombre dentro
    del texto, que es lo que queda cuando el objeto original ya no está disponible.

    Reconocer el caso importa: sin esto, un correo repetido —que es un error de la persona y tiene
    arreglo inmediato— se presentaría como un fallo del servidor, y quien lo lee no sabría que lo
    único que tiene que hacer es usar otro correo.
    """
    original = getattr(error, "orig", None)
    if getattr(original, "constraint_name", None) == INDICE_CORREO_GLOBAL:
        return True
    return INDICE_CORREO_GLOBAL in str(original or error)
