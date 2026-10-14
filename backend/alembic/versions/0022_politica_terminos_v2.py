"""Publica la versión 2 de los términos y condiciones.

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-14

Por qué una versión nueva y no una corrección de la 0006
-------------------------------------------------------
La 0006 ya se ejecutó en la base desplegada, y una migración aplicada **no se reescribe**: si se
cambiara su texto, el repositorio diría una cosa, la base tendría otra y la huella guardada dejaría
de corresponder al documento que los usuarios aceptaron. Aquí ocurre además algo que el diseño del
sistema anticipa a propósito: publicar una versión nueva es la forma de cambiar un texto legal, y
obliga a los usuarios a volver a aceptarlo, con su evidencia separada de la anterior.

Qué corrige esta versión
------------------------
1. **La presentación.** El texto se pinta dentro de un `pre` con `white-space: pre-wrap`, así que
   las marcas de formato de la versión 1 salían literales: los asteriscos de negrita y las líneas de
   signos iguales y guiones bajo los títulos se leían tal cual. Aquí no hay ninguna marca de
   formato: la jerarquía se marca con títulos en mayúsculas, líneas en blanco y guiones de lista,
   que es lo que el recuadro respeta sin transformar nada.

2. **La redacción y la cobertura.** Se completa lo que faltaba para que el documento se sostenga
   solo: quién presta el servicio y con qué canal de notificaciones, requisitos y capacidad para
   contratar, prueba gratuita y condiciones económicas, uso permitido y prohibido, propiedad
   intelectual, confidencialidad, disponibilidad, garantías, límite de responsabilidad, indemnidad,
   suspensión y terminación, fuerza mayor, cesión, nulidad parcial, ley aplicable y jurisdicción.

3. **Un dato que ya no era cierto.** La versión 1 decía, al enumerar lo que no se pide, que no se
   pedía «tu número de identificación». Al registrar la empresa se solicita el RUC, que es un número
   identificativo, así que la frase afirmaba algo que el propio formulario desmentía. Se sustituye
   por lo que sí ocurre: el RUC se pide y se explica para qué.

Lo que **no** cambia: el tipo (`terminos_uso`), el nombre que se le muestra al usuario y el hecho de
que sea la única política obligatoria. Solo cambia el texto, y por eso cambia su huella.

La huella se calcula aquí y se guarda con el texto en la misma sentencia, igual que en la 0006, para
que no puedan separarse: la pantalla de aceptación declara la huella que el servidor le entregó, y es
esa coincidencia la que convierte la aceptación en evidencia.
"""

from __future__ import annotations

import hashlib

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

TIPO = "terminos_uso"
VERSION = 2

# El texto íntegro, sin ninguna marca de formato. Va aquí y no en un archivo aparte porque es un dato
# que se publica, no un documento que se edite: cambiarlo es otra migración, con su número de
# versión, y así queda registrado quién aceptó qué redacción.
TEXTO = """\
TÉRMINOS Y CONDICIONES DE USO DE CERCOAPP
Última revisión: 14 de octubre de 2026 · Versión 2

Lee estas condiciones antes de usar CercoApp. Al marcar la casilla de aceptación declaras que las
has leído, que las entiendes y que las aceptas. Si no estás de acuerdo, no marques la casilla y no
uses el aplicativo.


1. QUIÉN PRESTA EL SERVICIO

El aplicativo CercoApp (en adelante, «el Servicio») lo presta Isaac Puga, persona natural que
actúa en el Ecuador (en adelante, «el Prestador»), con RUC en trámite de inscripción en la fecha de
esta revisión. Para toda comunicación, notificación, reclamación o ejercicio de derechos, el
Prestador señala el correo electrónico isaacpuga661@gmail.com como domicilio electrónico, que ambas
partes aceptan como medio válido. Cualquier cambio de este canal se avisará en el propio
aplicativo.


2. QUÉ ES EL SERVICIO

CercoApp es una herramienta privada de consulta y seguimiento de la contratación pública del
Ecuador. Lee datos que las entidades del Estado publican en abierto —el catálogo de procesos en
formato OCDS y el listado de necesidades de contratación—, los ordena y los muestra en tablas,
gráficas y un mapa, y avisa cuando aparece algo relacionado con las palabras clave que hayas
configurado.

El Prestador no es una entidad contratante, no participa en ningún procedimiento de contratación y
no es un sitio oficial del Estado. No representa ni sustituye al Servicio Nacional de Contratación
Pública (SERCOP).


3. PRIMACÍA DE LA FUENTE OFICIAL

La información del Servicio proviene de fuentes oficiales, pero puede llegar con retraso, incompleta
o con errores de lectura. Si existe cualquier diferencia entre lo que muestra CercoApp y lo que
publica el portal oficial, prevalece siempre lo que publica el portal oficial.

El Servicio es una ayuda de consulta, no una asesoría jurídica, contable ni técnica. No tomes
decisiones jurídicas, económicas o de participación basándote únicamente en lo que ves aquí:
contrasta siempre con los documentos oficiales y con los plazos que publique la entidad.


4. REQUISITOS PARA USAR EL SERVICIO

Puedes usar el Servicio si eres mayor de edad y tienes capacidad legal para contratar y, si actúas
en nombre de una empresa o entidad, si estás facultado para obligarla. Al registrar una cuenta
declaras que los datos que facilitas son verdaderos, exactos y están actualizados, y te comprometes
a mantenerlos así.


5. TU CUENTA Y TUS CREDENCIALES

La cuenta es personal e intransferible. Eres responsable de custodiar tu contraseña y de todo lo que
ocurra desde tu cuenta. Compartir el acceso con otras personas, dentro o fuera de tu organización,
incumple estas condiciones y puede provocar la suspensión del Servicio.

La contraseña se guarda cifrada con un algoritmo diseñado para ello y nunca en texto legible. Ni el
Prestador puede leerla. Si detectas un uso indebido de tus credenciales, avísanos de inmediato.

Puedes tener como máximo dos sesiones abiertas a la vez. Al iniciar una tercera se cierra la que
lleves más tiempo sin usar. Si detectamos un uso indebido, cerraremos todas tus sesiones y te lo
comunicaremos.

El administrador de cada empresa crea y da de baja las cuentas de su equipo, y responde por el uso
que esas cuentas hagan del Servicio.


6. PRUEBA GRATUITA Y CONDICIONES ECONÓMICAS

Al registrar la empresa, esta empieza con 7 días de acceso a todas las vistas, sin coste y sin
compromiso de compra. Al terminar ese plazo, el acceso a las vistas que sean de pago se suspende
hasta que se contrate un plan; los datos de la cuenta no se borran por ese motivo.

El alcance, el precio y la duración de cada plan se comunican antes de contratarlo y quedan
recogidos en la propuesta o en el panel. No se cobra ningún importe sin aceptación previa y expresa.
Los precios se entienden sin impuestos, que se añadirán cuando la ley lo exija.


7. USO PERMITIDO Y USO PROHIBIDO

Puedes usar el Servicio para consultar y seguir la contratación pública y para exportar los
resultados a Excel con el fin de analizarlos dentro de tu actividad.

No puedes, entre otras cosas:
   - revender, sublicenciar, alquilar o ceder el acceso al Servicio a terceros;
   - extraer el contenido de forma masiva o automatizada para reconstruir la base de datos,
     entrenar sistemas automáticos o crear un producto competidor;
   - eludir los límites técnicos del Servicio, incluidos los de sesiones, consultas y exportaciones,
     ni acceder a datos de otra empresa;
   - introducir código malicioso, intentar vulnerar la seguridad del Servicio ni realizar pruebas de
     penetración sin autorización escrita previa;
   - usar el Servicio para fines ilícitos o contrarios a la ley ecuatoriana.

El incumplimiento de esta cláusula faculta al Prestador para suspender o cancelar la cuenta de
inmediato y, cuando corresponda, para reclamar los daños causados.


8. DATOS DE TERCEROS QUE APARECEN EN EL PANEL

El Servicio muestra datos de contacto de funcionarios públicos que las propias entidades publican en
el marco de los procedimientos de contratación. Es información pública y se muestra con la única
finalidad de que puedas dirigirte a la entidad por un procedimiento concreto.

Está prohibido usar esos datos para cualquier otro fin: elaborar listas de contactos, enviar
comunicaciones comerciales a funcionarios públicos o cualquier tratamiento ajeno al procedimiento al
que pertenecen. Hacerlo es un incumplimiento grave de estas condiciones, puede acarrearte
responsabilidad legal y provoca la suspensión inmediata del Servicio. Eres responsable del uso que
hagas de la información que consultas.


9. TUS DATOS PERSONALES

El Prestador trata tus datos personales conforme a la Ley Orgánica de Protección de Datos
Personales del Ecuador y su normativa de desarrollo. En concreto:

   - Responsable y finalidad. Los datos se tratan para prestar el Servicio, gestionar tu cuenta y tu
     acceso, atender tus solicitudes y enviarte las comunicaciones del punto 10. No se usan para
     fines distintos ni se venden, alquilan o ceden con fines publicitarios.
   - Datos tratados. Nombre, correo electrónico, teléfono, datos de la empresa —nombre o razón
     social, RUC, ciudad, dirección y correo de contacto—, credenciales cifradas, direcciones IP y
     registros de acceso y de uso del Servicio.
   - Minimización. Solo se piden los datos necesarios para identificar a la empresa y prestar el
     Servicio. Al registrar la cuenta se solicita el RUC de la empresa, que es el número con el que
     esta se identifica ante la administración tributaria; cada campo del formulario indica si es
     obligatorio. No se piden datos bancarios ni el número de identificación personal de la persona
     que se registra.
   - Base legal. La ejecución del contrato y tu consentimiento, que otorgas al aceptar estas
     condiciones y que puedes retirar en cualquier momento.
   - Encargados del tratamiento. El Servicio se aloja en proveedores de infraestructura en la nube
     que tratan los datos por cuenta del Prestador, con contratos que les exigen confidencialidad y
     medidas de seguridad. Alguno de esos proveedores puede estar fuera del Ecuador; en tal caso, la
     transferencia se ampara en las garantías que exige la ley.
   - Conservación. Los datos se conservan mientras la cuenta esté activa y, después, durante el
     plazo de retención configurado —por defecto, 365 días— y los plazos legales aplicables; luego se
     eliminan o se anonimizan.
   - Seguridad. Se aplican medidas técnicas y organizativas razonables, entre ellas el cifrado de
     las contraseñas, el aislamiento de los datos de cada empresa y un registro de auditoría de los
     accesos.
   - Tus derechos. Puedes ejercer los derechos de acceso, rectificación, actualización, eliminación,
     oposición, portabilidad y los demás que reconoce la ley escribiendo a
     isaacpuga661@gmail.com. Responderemos dentro del plazo legal. Ten en cuenta que retirar el
     consentimiento bloquea el acceso al Servicio, porque sin él no es posible tratar los datos que
     su uso implica.
   - Trazabilidad. Al aceptar estas condiciones se guardan, junto a tu aceptación, la versión exacta
     del texto, su huella digital, la fecha, la dirección IP y el agente de usuario. Es lo que
     permite demostrar qué aceptaste y cuándo, y a ti comprobarlo.


10. OFERTAS Y NOTIFICACIONES

Al aceptar estas condiciones autorizas el tratamiento de tus datos de contacto para:

   a) enviarte ofertas comerciales relacionadas con el Servicio: nuevos módulos, planes, condiciones
      especiales y servicios que puedan resultarte útiles para tu actividad;
   b) enviarte notificaciones del Servicio: avisos de funcionamiento, cambios en estas condiciones,
      incidencias, vencimiento de la prueba o del plan y nuevas contrataciones que coincidan con las
      palabras clave que hayas configurado;
   c) elaborar estadísticas internas agregadas, que no te identifican y no se ceden a terceros.

Puedes rechazar las ofertas comerciales del apartado a) en cualquier momento, desde la configuración
de tu cuenta o escribiéndonos; rechazarlas no afecta a tu acceso al Servicio. Las notificaciones del
apartado b) son parte del funcionamiento del producto y no se pueden desactivar mientras la cuenta
esté activa.


11. PROPIEDAD INTELECTUAL

El Servicio, su código, su diseño, sus textos y su marca pertenecen al Prestador o a quien le haya
cedido los derechos. Estas condiciones no te transfieren ningún derecho sobre ellos: solo te
conceden una licencia de uso personal, limitada, no exclusiva ni transferible, válida mientras tu
cuenta esté activa y sujeta a lo pactado aquí.

Los datos públicos que se muestran pertenecen a sus fuentes. Las exportaciones que generes son tuyas
y puedes usarlas dentro de tu actividad.


12. CONFIDENCIALIDAD

Cada parte se obliga a mantener en reserva la información confidencial de la otra a la que acceda
por razón del Servicio y a usarla solo para lo previsto en estas condiciones. La obligación se
mantiene durante tres años después de terminar la relación.


13. DISPONIBILIDAD, CAMBIOS Y SOPORTE

El Servicio depende de portales de terceros. Si la fuente oficial deja de publicar, cambia su
formato o limita el acceso, la información puede llegar con retraso o no llegar; hacemos lo
razonable por detectarlo y avisarte, pero no podemos garantizar la disponibilidad ininterrumpida ni
la ausencia de errores.

Podemos realizar tareas de mantenimiento, actualizar el Servicio o modificar sus funciones. Cuando un
cambio reduzca de forma sustancial lo que se ofrece, se comunicará con antelación razonable y podrás
cancelar la cuenta sin coste.


14. GARANTÍAS

El Servicio se presta «tal cual» y «según disponibilidad». En la medida en que la ley lo permita, el
Prestador no garantiza que el Servicio esté libre de errores, que los datos sean completos o exactos
ni que el uso que hagas de él te reporte un resultado comercial o administrativo concreto.


15. LÍMITE DE RESPONSABILIDAD

En la medida en que la ley lo permita, el Prestador no responde de daños indirectos, lucro cesante ni
pérdida de oportunidades, de datos o de reputación derivados del uso del Servicio o de la
imposibilidad de usarlo.

La responsabilidad total del Prestador por cualquier reclamación derivada de estas condiciones se
limita al importe que hayas pagado por el Servicio en los doce meses anteriores a la reclamación. Si
el uso ha sido gratuito, el límite es de cien dólares de los Estados Unidos de América.

Nada en esta cláusula excluye la responsabilidad que la ley no permita limitar, en particular la
derivada de dolo o culpa grave, ni afecta a los derechos que la ley reconoce a los consumidores.


16. INDEMNIDAD

Te comprometes a mantener indemne al Prestador frente a reclamaciones de terceros —incluidos los
gastos de defensa razonables— que se deriven del uso que hagas del Servicio, de los datos que
introduzcas o del incumplimiento de estas condiciones, en particular del uso indebido de los datos
de contacto de funcionarios públicos al que se refiere el punto 8.


17. SUSPENSIÓN Y TERMINACIÓN

Puedes dejar de usar el Servicio y solicitar la baja de tu cuenta cuando quieras, escribiendo al
canal de contacto.

El Prestador puede suspender o cancelar el acceso, con aviso previo cuando sea posible, si se
incumplen estas condiciones, si existe un riesgo para la seguridad del Servicio o de terceros, si lo
exige una autoridad competente o si no se atiende el pago de un plan contratado. En los casos graves
y cuando la ley lo permita, la suspensión puede ser inmediata y sin aviso previo.

Al terminar, se desactiva tu acceso y los datos se tratan conforme al punto 9. Las obligaciones que
por su naturaleza deban sobrevivir —confidencialidad, propiedad intelectual, indemnidad y límite de
responsabilidad— siguen vigentes.


18. CAMBIOS EN ESTAS CONDICIONES

Podemos actualizar estas condiciones para reflejar cambios legales, técnicos o del Servicio. Cuando
publiquemos una versión nueva, el aplicativo te pedirá que la aceptes antes de seguir usándolo: no se
aplica de forma retroactiva silenciosa y tu aceptación anterior queda registrada tal y como la diste.

Si no estás de acuerdo con una versión nueva, puedes retirar tu consentimiento y dejar de usar el
Servicio.


19. FUERZA MAYOR

Ninguna parte responde por el incumplimiento debido a causas ajenas a su control razonable, como
catástrofes naturales, cortes prolongados de energía o de comunicaciones, ciberataques, cambios
normativos sobrevenidos o decisiones de terceros que afecten a las fuentes de datos.


20. CESIÓN

No puedes ceder a terceros tu posición en estas condiciones sin autorización escrita del Prestador.
El Prestador puede cederlas a una sociedad de su grupo o a quien continúe el servicio, avisándote con
antelación razonable.


21. NULIDAD PARCIAL E INTEGRIDAD DEL ACUERDO

Si alguna cláusula se declara nula o inaplicable, se tendrá por no puesta y el resto seguirá vigente.
Estas condiciones, junto con las condiciones económicas del plan contratado y las políticas que se
aceptan en el aplicativo, son el acuerdo completo entre las partes y sustituyen cualquier pacto
anterior sobre el mismo objeto.


22. LEY APLICABLE Y JURISDICCIÓN

Estas condiciones se rigen por la ley de la República del Ecuador. Para cualquier controversia, las
partes se someten a los jueces competentes del Ecuador y, antes de acudir a ellos, intentarán
resolverla de buena fe escribiendo al canal de contacto, sin perjuicio de los derechos que la ley
reconozca a los consumidores.


23. ACEPTACIÓN

Al marcar la casilla y continuar, declaro que:

   - he leído y comprendido estos términos y condiciones;
   - acepto el uso de mis datos de contacto en los términos de los puntos 9 y 10, incluido el envío
     de ofertas comerciales y de notificaciones del Servicio;
   - entiendo que retirar este consentimiento bloquea mi acceso al Servicio.
"""


def _normalizar(texto: str) -> str:
    """La misma normalización que aplica el dominio antes de calcular la huella.

    Se repite aquí, y no se importa, por la razón que ya explica la migración 0006: una migración
    tiene que producir el mismo resultado dentro de dos años, cuando el código del dominio haya
    cambiado. Si importara el código vivo, una modificación posterior de la normalización cambiaría
    la huella de un texto ya publicado y obligaría a todo el mundo a aceptar de nuevo una redacción
    que nadie tocó.
    """
    unificado = texto.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(linea.rstrip() for linea in unificado.strip().split("\n"))


def upgrade() -> None:
    huella = hashlib.sha256(_normalizar(TEXTO).encode("utf-8")).hexdigest()

    conexion = op.get_bind()

    # Mismo criterio que en la 0006: si la versión ya está publicada con otro texto, no se
    # sobrescribe. Reescribir una versión que los usuarios ya aceptaron dejaría sus aceptaciones
    # apuntando a un documento distinto del que leyeron.
    existente = conexion.execute(
        sa.text(
            "SELECT texto, hash FROM politica_version WHERE tipo = :tipo AND version = :version"
        ),
        {"tipo": TIPO, "version": VERSION},
    ).first()
    if existente is not None:
        if existente.hash != huella:
            raise RuntimeError(
                "La versión 2 de los términos ya está publicada con un texto distinto al de esta "
                "migración. No se sobrescribe: si el cambio es intencionado, publica una versión "
                "nueva en lugar de reescribir la que los usuarios ya aceptaron."
            )
        return

    conexion.execute(
        sa.text(
            """
            INSERT INTO politica_version (tipo, version, texto, hash, vigente_desde)
            VALUES (:tipo, :version, :texto, :hash, now())
            """
        ),
        {"tipo": TIPO, "version": VERSION, "texto": TEXTO, "hash": huella},
    )

    # Y se marca como pendiente en todas las cuentas: quien aceptó la versión 1 tiene que leer la 2
    # antes de seguir usando el aplicativo. La condición `< :version` deja fuera a quien ya tuviera
    # marcada una versión igual o posterior.
    conexion.execute(
        sa.text(
            """
            UPDATE usuario
            SET debe_aceptar_politica_version = :version
            WHERE debe_aceptar_politica_version IS NULL
               OR debe_aceptar_politica_version < :version
            """
        ),
        {"version": VERSION},
    )


def downgrade() -> None:
    """Retira la versión publicada, con la misma salvaguarda que la 0006.

    Se niega si **alguien ya la aceptó**: borrar el texto del que existe una aceptación dejaría la
    evidencia apuntando a un documento que ya no está en la base.
    """
    conexion = op.get_bind()
    aceptaciones = conexion.execute(
        sa.text(
            """
            SELECT count(*) FROM consentimiento
            WHERE tipo = :tipo AND version_texto = :version
            """
        ),
        {"tipo": TIPO, "version": str(VERSION)},
    ).scalar_one()
    if aceptaciones:
        raise RuntimeError(
            f"Hay {aceptaciones} aceptaciones registradas de esta versión. No se puede retirar el "
            "texto mientras exista la evidencia: dejaría aceptaciones de un documento inexistente."
        )

    conexion.execute(
        sa.text("DELETE FROM politica_version WHERE tipo = :tipo AND version = :version"),
        {"tipo": TIPO, "version": VERSION},
    )
    # Las cuentas vuelven a deber la versión anterior, que es la que queda vigente.
    conexion.execute(sa.text("UPDATE usuario SET debe_aceptar_politica_version = 1"))
