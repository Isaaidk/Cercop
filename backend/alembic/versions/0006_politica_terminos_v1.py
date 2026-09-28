"""Publica la versión 1 de los términos y condiciones.

Por qué el texto vive en una migración
-------------------------------------
El texto que se muestra tiene que ser **el mismo** que se guarda, y el que se guarda lleva su huella.
Si el texto viviera en un archivo del código y la publicación fuera un script que alguien tiene que
acordarse de ejecutar, el sistema podría estar en producción sin ningún texto publicado —y entonces
la pantalla de aceptación no tendría nada que mostrar— o con una versión distinta de la que el
repositorio dice.

Poniéndolo aquí, publicar es desplegar: la migración calcula la huella y la guarda con el texto, en la
misma sentencia. Una prueba comprueba que la huella guardada coincide con la que calcula el dominio
para ese mismo texto, que es lo que impide que las dos formas de calcularla se separen con el tiempo.

Por qué se marca como pendiente a todas las cuentas
--------------------------------------------------
Publicar una versión nueva obliga a re-aceptarla. En el despliegue inicial no hay ninguna cuenta, así
que el marcado no afecta a nadie; se deja escrito igualmente porque es lo que hay que hacer **cada
vez** que este patrón se repita, y el día que se publique la versión 2 la mitad del trabajo tiene que
estar ya hecha.

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

import hashlib

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

TIPO = "terminos_uso"

# El texto íntegro. Va aquí y no en un archivo aparte porque es un dato que se publica, no un
# documento que se edite: cambiarlo es una migración nueva, con su número de versión, y así queda
# registrado quién aceptó qué redacción.
TEXTO = """\
TÉRMINOS Y CONDICIONES DE USO
=============================

Última revisión: 27 de septiembre de 2026

Antes de usar este aplicativo, lee estas condiciones con calma. Al marcar la casilla de aceptación
confirmas que las has leído y que estás de acuerdo con ellas.


1. Qué es este aplicativo
-------------------------

Es una herramienta de consulta y seguimiento de contratación pública. Reúne y ordena información
que las entidades del Estado ecuatoriano publican en sus portales oficiales, y avisa a sus usuarios
cuando aparece algo relacionado con las palabras clave que han configurado.

No somos una entidad contratante ni formamos parte del proceso de contratación. La información que
ves proviene de la fuente oficial y **la fuente oficial es la que manda**: si hubiera cualquier
diferencia entre lo que muestra este aplicativo y lo que publica el portal del Estado, vale lo que
publica el portal. No tomes decisiones jurídicas o económicas basándote únicamente en lo que ves
aquí: contrasta siempre con el documento oficial.


2. Tu cuenta
------------

Eres responsable de mantener tu contraseña en secreto y de todo lo que ocurra desde tu cuenta.
Puedes tener como máximo dos sesiones abiertas a la vez; al iniciar una tercera, se cierra la que
llevabas más tiempo sin usar. Si detectamos un uso indebido de tus credenciales, cerraremos todas tus
sesiones y te lo comunicaremos.

Tu cuenta es personal. Compartir el acceso con otras personas —dentro o fuera de tu organización— es
un incumplimiento de estas condiciones y puede suponer la suspensión del servicio.


3. Uso de tus datos para enviarte ofertas y notificaciones
----------------------------------------------------------

Al aceptar estas condiciones autorizas expresamente el tratamiento de tus datos de contacto
—nombre, correo electrónico y, si lo facilitas, teléfono— con las siguientes finalidades:

  a) Enviarte **ofertas comerciales** relacionadas con el aplicativo: nuevos módulos, planes,
     condiciones especiales y servicios que puedan resultarte útiles para tu actividad.

  b) Enviarte **notificaciones del aplicativo**: avisos de funcionamiento, cambios en estas
     condiciones, incidencias del servicio, vencimiento de tus accesos a las vistas del panel y
     nuevas contrataciones que coincidan con las palabras clave que hayas configurado. Las
     notificaciones de vencimiento y las de incidencias del servicio **no** se pueden desactivar:
     son parte del funcionamiento del producto y sin ellas no podríamos prestártelo de forma
     responsable.

  c) Elaborar estadísticas internas agregadas —cuántas consultas se hacen, qué provincias se
     siguen más— para mejorar el producto. Estas estadísticas **no te identifican** y no se ceden a
     terceros.

Las ofertas comerciales del punto (a) sí puedes rechazarlas en cualquier momento, desde la
configuración de tu cuenta o escribiéndonos. Rechazarlas no afecta a tu acceso al aplicativo: seguirás
recibiendo las notificaciones del apartado (b), que son las que mantienen el servicio funcionando.


4. Uso responsable de tus datos
-------------------------------

Nos comprometemos a tratar tus datos personales de forma responsable y conforme a la Ley Orgánica de
Protección de Datos Personales del Ecuador. En concreto:

  - **Finalidad limitada.** Usamos tus datos para lo que dice el punto 3 y para nada más. No los
    vendemos, no los alquilamos y no los cedemos a terceros con fines publicitarios.

  - **Seguridad.** Tu contraseña se guarda cifrada con un algoritmo diseñado para ello, y **nunca**
    en texto legible. Ni nosotros podemos leerla. Los accesos se registran en un historial de
    auditoría para poder investigar cualquier incidente.

  - **Minimización.** No pedimos datos que no necesitemos. No pedimos tu número de identificación ni
    tus datos bancarios.

  - **Conservación limitada.** Conservamos tus datos mientras tu cuenta esté activa y durante los
    plazos legales aplicables. Después se eliminan o se anonimizan.

  - **Tus derechos.** Puedes solicitar acceso, rectificación, cancelación, oposición y portabilidad
    de tus datos, así como retirar este consentimiento en cualquier momento. Para ejercerlos,
    escríbenos; responderemos en el plazo legal. Ten en cuenta que **retirar el consentimiento
    bloquea el acceso al aplicativo**, porque sin él no podemos tratar los datos que su uso implica.

  - **Trazabilidad.** Cuando aceptas estas condiciones se guarda, junto a tu aceptación, la versión
    exacta del texto que estabas leyendo y su huella digital, además de la fecha y la dirección desde
    la que aceptaste. Es lo que nos permite demostrar qué aceptaste y cuándo, y a ti te permite
    comprobarlo.


5. Información sobre terceros que aparece en el panel
-----------------------------------------------------

El aplicativo muestra datos de contacto de funcionarios públicos que las propias entidades publican
en sus portales, en el marco de los procedimientos de contratación. Es información **pública** y se
muestra con la única finalidad de que puedas dirigirte a la entidad sobre un procedimiento concreto.

Está prohibido usar esos datos para cualquier fin distinto: elaborar listas de contactos, enviar
comunicaciones comerciales a funcionarios públicos o cualquier tratamiento que no esté relacionado
con el procedimiento de contratación al que pertenecen. Hacerlo es un incumplimiento grave de estas
condiciones y puede acarrearte responsabilidad legal, además de la suspensión inmediata del servicio.

Eres responsable del uso que hagas de la información que consultas.


6. Límites del servicio
-----------------------

El servicio se presta «como está». Dependemos de portales de terceros: si la fuente oficial deja de
publicar, cambia su formato o limita el acceso, la información puede llegar con retraso o no llegar.
Hacemos lo razonable por detectarlo y avisarte, pero no podemos garantizar la disponibilidad
ininterrumpida ni la ausencia de errores.

No respondemos de los daños indirectos derivados del uso del aplicativo, en la medida en que la ley
lo permita.


7. Cambios en estas condiciones
-------------------------------

Podemos actualizar estas condiciones para reflejar cambios legales o del servicio. Cuando publiquemos
una versión nueva, el aplicativo **te pedirá que la aceptes antes de seguir usándolo**: no se aplica
de forma retroactiva silenciosa, y tu aceptación anterior queda registrada tal y como la diste.

Si no estás de acuerdo con una versión nueva, puedes retirar tu consentimiento y dejar de usar el
servicio.


8. Aceptación
-------------

Al marcar la casilla y continuar, declaro que:

  - He leído y comprendido estos términos y condiciones.
  - Acepto el uso de mis datos de contacto en los términos del punto 3, incluido el envío de ofertas
    comerciales y de notificaciones del aplicativo.
  - Entiendo que retirar este consentimiento bloquea mi acceso al aplicativo.
"""


def _normalizar(texto: str) -> str:
    """La misma normalización que aplica el dominio antes de calcular la huella.

    Se repite aquí, y no se importa, por una razón concreta: una migración tiene que seguir
    produciendo **el mismo resultado** dentro de dos años, cuando el código del dominio haya cambiado.
    Si esta migración importara el código vivo, una modificación posterior de la normalización
    cambiaría la huella de un texto ya publicado y obligaría a todo el mundo a aceptar de nuevo una
    redacción que nadie tocó.

    Para que la repetición no se convierta en una divergencia silenciosa, hay una prueba que compara
    la huella guardada con la que calcula el dominio para este mismo texto.
    """
    unificado = texto.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(linea.rstrip() for linea in unificado.strip().split("\n"))


def upgrade() -> None:
    huella = hashlib.sha256(_normalizar(TEXTO).encode("utf-8")).hexdigest()

    conexion = op.get_bind()

    # Si ya existe una versión 1 de este tipo —porque alguien la publicó a mano— no se duplica: la
    # restricción de unicidad lo impediría y la migración fallaría en un despliegue que, por lo demás,
    # estaría bien. Se deja como está y se avisa.
    existente = conexion.execute(
        sa.text(
            "SELECT version, hash FROM politica_version WHERE tipo = :tipo ORDER BY version DESC"
        ),
        {"tipo": TIPO},
    ).first()
    if existente is not None:
        if existente.hash != huella:
            raise RuntimeError(
                "Ya hay una política de términos publicada con un texto distinto al de esta "
                "migración. No se sobrescribe: si el cambio es intencionado, publica una versión "
                "nueva en lugar de reescribir la que los usuarios ya aceptaron."
            )
        return

    conexion.execute(
        sa.text(
            """
            INSERT INTO politica_version (tipo, version, texto, hash, vigente_desde)
            VALUES (:tipo, 1, :texto, :hash, now())
            """
        ),
        {"tipo": TIPO, "texto": TEXTO, "hash": huella},
    )

    # Y se marca como pendiente a las cuentas que ya existieran. En un despliegue inicial no hay
    # ninguna; en una base que ya estaba en marcha, esto es lo que obliga a sus usuarios a leer la
    # versión nueva antes de seguir.
    conexion.execute(
        sa.text(
            """
            UPDATE usuario
            SET debe_aceptar_politica_version = 1
            WHERE debe_aceptar_politica_version IS NULL
               OR debe_aceptar_politica_version < 1
            """
        )
    )


def downgrade() -> None:
    """Retira la versión publicada.

    Se niega a hacerlo si **alguien ya la aceptó**. Borrar el texto del que existe una aceptación
    dejaría la evidencia apuntando a un documento que ya no está en la base: la aceptación seguiría
    ahí, pero nadie podría demostrar qué se aceptó, que es lo único que la hace valiosa.
    """
    conexion = op.get_bind()
    aceptaciones = conexion.execute(
        sa.text(
            """
            SELECT count(*) FROM consentimiento
            WHERE tipo = :tipo AND version_texto = '1'
            """
        ),
        {"tipo": TIPO},
    ).scalar_one()
    if aceptaciones:
        raise RuntimeError(
            f"Hay {aceptaciones} aceptaciones registradas de esta versión. No se puede retirar el "
            "texto mientras exista la evidencia: dejaría aceptaciones de un documento inexistente."
        )

    conexion.execute(
        sa.text("DELETE FROM politica_version WHERE tipo = :tipo AND version = 1"),
        {"tipo": TIPO},
    )
    conexion.execute(sa.text("UPDATE usuario SET debe_aceptar_politica_version = NULL"))
