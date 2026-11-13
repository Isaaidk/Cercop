"""Publica los términos v3 y la política de privacidad v1 (adecuación a la LOPDP).

Revision ID: 0044
Revises: 0043
Create Date: 2026-11-13

Qué publica
-----------
1. **Términos y condiciones de uso, versión 3** (`terminos_uso`). Sustituye a la 2: separa el
   contrato de uso de la información sobre datos personales, añade el uso de la inteligencia
   artificial, los créditos de IA, la propiedad intelectual del software y la prohibición expresa
   de copia, raspado e ingeniería inversa, y ajusta la jurisdicción a la Ley de Comercio
   Electrónico (art. 47: en contratos con consumidores, el domicilio del consumidor).
2. **Política de privacidad y tratamiento de datos personales, versión 1** (`tratamiento_datos`).
   Es el texto de información que exige el art. 12 de la Ley Orgánica de Protección de Datos
   Personales (LOPDP): responsable, finalidades, bases de legitimación (art. 7), categorías y
   fuentes de datos, encargados, transferencias internacionales (arts. 55 a 60), conservación,
   derechos (arts. 13 a 20) y cómo ejercerlos, seguridad y notificación de vulneraciones (arts. 43
   y 46).

Desde esta revisión las dos son obligatorias (`POLITICAS_OBLIGATORIAS` en el dominio), así que se
marcan como pendientes en todas las cuentas y el panel encadena las dos aceptaciones. El tipo
`tratamiento_datos` ya estaba admitido por la restricción `CHECK` de `consentimiento` desde la
`0001`, y `politica_version.tipo` no tiene restricción: no hace falta tocar el esquema.

Los marcadores «[…]»
--------------------
Los textos llevan marcadores entre comillas angulares —«[NOMBRE O RAZÓN SOCIAL DEL RESPONSABLE]»,
«[RUC DEL RESPONSABLE]»…— para los datos que solo puede dar el titular del negocio. **No se
inventan.** Como una versión publicada no se reescribe (ver la `0022`), publicar con marcadores
obligaría a sacar otra versión y a pedir a todo el mundo que acepte otra vez. Por eso la migración
**se niega a correr en producción** mientras quede alguno: hay que rellenarlos aquí, antes de
desplegar. En desarrollo se publican tal cual, para poder ver las pantallas. Ver
`docs/40-cumplimiento-lopdp.md`.

Defensiva frente a datos de producción
--------------------------------------
- Si la versión ya existe con **la misma** huella, no se hace nada (idempotente).
- Si existe con otra huella, o ya hay una versión **mayor** publicada, se detiene: alguien publicó
  otra redacción por otro camino y elegir entre las dos es una decisión humana, no de una
  migración.
- El marcado de pendientes no supone que haya cuentas ni qué valor tengan: solo sube el marcador
  de quien lo tenga vacío o por debajo.

La huella se calcula con la misma normalización que el dominio, copiada y no importada, por la razón
que explica la `0006`.
"""

from __future__ import annotations

import hashlib
import os

import sqlalchemy as sa
from alembic import op

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None

MARCADOR = "«["

TERMINOS_V3 = """\
TÉRMINOS Y CONDICIONES DE USO DE CERCOAPP
Versión 3 · Vigente desde el 13 de noviembre de 2026

Lee estas condiciones antes de usar CercoApp. Al marcar la casilla de aceptación declaras que las
has leído, que las entiendes y que las aceptas. Si no estás de acuerdo, no marques la casilla y no
uses el aplicativo. El tratamiento de tus datos personales se explica aparte, en la Política de
privacidad y tratamiento de datos personales, que también se te pide aceptar.


1. QUIÉN PRESTA EL SERVICIO

El aplicativo CercoApp (en adelante, «el Servicio») lo presta «[NOMBRE O RAZÓN SOCIAL DEL
RESPONSABLE]», con RUC «[RUC DEL RESPONSABLE]» y domicilio en «[DIRECCIÓN DEL DOMICILIO LEGAL]»,
Ecuador (en adelante, «el Prestador»).

Canal de contacto y domicilio electrónico: «[CORREO DE CONTACTO]», teléfono «[TELÉFONO DE
CONTACTO]». Ambas partes aceptan ese correo como medio válido para notificaciones y reclamaciones,
conforme a la Ley de Comercio Electrónico, Firmas y Mensajes de Datos, que reconoce a los mensajes
de datos el mismo valor jurídico que a los documentos escritos (art. 2). Cualquier cambio de este
canal se avisará en el propio aplicativo.


2. QUÉ ES EL SERVICIO

CercoApp es una herramienta privada de consulta y seguimiento de la contratación pública del
Ecuador. Lee datos que las entidades del Estado publican en abierto —el catálogo de procesos en
formato OCDS y el listado de necesidades de contratación del SERCOP— y los ordena en tablas,
gráficas y un mapa; avisa cuando aparece algo relacionado con las palabras clave que configures; y
ofrece herramientas de apoyo para preparar ofertas: lectura de pliegos y anexos, proformas,
asistente con inteligencia artificial y firma electrónica de documentos con tu propio certificado.

El Prestador no es una entidad contratante, no participa en ningún procedimiento de contratación y
no es un sitio oficial del Estado. No representa ni sustituye al Servicio Nacional de Contratación
Pública (SERCOP) ni al Servicio de Rentas Internas (SRI).


3. PRIMACÍA DE LA FUENTE OFICIAL

La información del Servicio proviene de fuentes oficiales, pero puede llegar con retraso,
incompleta o con errores de lectura. Si hay cualquier diferencia entre lo que muestra CercoApp y lo
que publica el portal oficial, prevalece siempre el portal oficial.

El Servicio es una ayuda de consulta, no una asesoría jurídica, contable ni técnica. No tomes
decisiones jurídicas, económicas o de participación basándote solo en lo que ves aquí: contrasta
siempre con los documentos oficiales y con los plazos que publique la entidad.


4. REQUISITOS PARA USAR EL SERVICIO

El Servicio está dirigido a empresas y profesionales. Puedes usarlo si eres mayor de dieciocho
años, tienes capacidad legal para contratar y, si actúas en nombre de una empresa, estás facultado
para obligarla. No está dirigido a menores de edad.

Al registrar una cuenta declaras que los datos que facilitas son verdaderos, exactos y actuales, y
te comprometes a mantenerlos así. Si registras datos de otras personas —por ejemplo, del
representante legal o de los contactos de tu empresa—, declaras que tienes una base legítima para
facilitarlos y que les has informado de ello.


5. TU CUENTA Y TUS CREDENCIALES

La cuenta es personal e intransferible. Eres responsable de custodiar tu contraseña y de lo que
ocurra desde tu cuenta. Compartir el acceso con otras personas, dentro o fuera de tu organización,
incumple estas condiciones.

Puedes tener como máximo dos sesiones abiertas a la vez; al iniciar una tercera se cierra la que
lleves más tiempo sin usar. Si detectas o sospechas un uso indebido de tus credenciales, avísanos
de inmediato por el canal de contacto.

El administrador de cada empresa crea y da de baja las cuentas de su equipo y responde por el uso
que esas cuentas hagan del Servicio.


6. PRUEBA GRATUITA, PLANES Y CRÉDITOS DE IA

Al registrar la empresa, esta empieza con 7 días de acceso a todas las vistas, sin coste y sin
compromiso. Al terminar ese plazo, el acceso a las vistas de pago se suspende hasta que se contrate
un plan; los datos de la cuenta no se borran por ese motivo.

El alcance, el precio y la duración de cada plan se comunican antes de contratarlo. No se cobra
ningún importe sin tu aceptación previa y expresa. Los precios se entienden sin impuestos, que se
añadirán cuando la ley lo exija.

Algunas funciones de inteligencia artificial consumen créditos. Los paquetes de créditos se
solicitan desde el panel; el pago se realiza fuera del aplicativo, por los medios que el Prestador
te indique, y los créditos se acreditan cuando el Prestador confirma el pago. El aplicativo no pide
ni guarda datos de tarjetas ni de cuentas bancarias. El coste en créditos de cada función se
muestra antes de usarla.

Nada de lo anterior limita los derechos que la Ley Orgánica de Defensa del Consumidor reconozca a
quien contrate como consumidor.


7. USO DE LA INTELIGENCIA ARTIFICIAL

Algunas funciones —el asistente, el resumen de pliegos, la redacción de ofertas y proformas— usan
modelos de lenguaje de proveedores externos. Ten en cuenta que:

   - Lo que genera la inteligencia artificial es un BORRADOR. Puede contener errores, omisiones o
     datos inventados, y no sustituye la lectura de los pliegos ni el criterio de un profesional.
     Tú decides qué usas y eres responsable de revisarlo antes de presentarlo ante cualquier
     entidad.
   - El Servicio no toma por ti ninguna decisión con efectos jurídicos: no presenta ofertas, no se
     inscribe en procesos ni firma nada sin una acción tuya.
   - Para funcionar, el texto que envías y los documentos que eliges analizar se transmiten al
     proveedor del modelo, que puede estar fuera del Ecuador. Los detalles están en la Política de
     privacidad. No incluyas en el asistente datos personales que no sean necesarios.


8. FIRMA ELECTRÓNICA

Si firmas documentos desde el Servicio, el archivo del certificado (.p12 o .pfx) y su clave se usan
solo en memoria durante la operación y no se guardan. Eres el único responsable de la custodia de
tu certificado y de lo que firmes con él.


9. USO PERMITIDO Y USO PROHIBIDO

Puedes usar el Servicio para consultar y seguir la contratación pública, preparar tus ofertas y
exportar resultados para analizarlos dentro de tu actividad.

No puedes, entre otras cosas:
   - revender, sublicenciar, alquilar o ceder el acceso al Servicio a terceros;
   - extraer contenido de forma masiva o automatizada (raspado, robots, scripts o cualquier medio
     similar), ni reconstruir la base de datos del Servicio, ni usarlo para entrenar sistemas de
     inteligencia artificial o crear un producto competidor;
   - copiar, descompilar, desensamblar o aplicar ingeniería inversa al software, salvo en los casos
     en que la ley lo permita expresamente;
   - eludir los límites técnicos del Servicio —sesiones, consultas, exportaciones, frenos de
     uso— ni acceder o intentar acceder a datos de otra empresa;
   - introducir código malicioso, intentar vulnerar la seguridad del Servicio o hacer pruebas de
     penetración sin autorización escrita previa;
   - subir contenidos sobre los que no tengas derechos o que sean ilícitos;
   - usar el Servicio para fines ilícitos o contrarios a la ley ecuatoriana.

El incumplimiento de esta cláusula faculta al Prestador para suspender o cancelar la cuenta y,
cuando corresponda, para reclamar los daños causados.


10. DATOS DE TERCEROS QUE APARECEN EN EL PANEL

El Servicio muestra datos de contacto de funcionarios públicos que las propias entidades publican
en el marco de los procedimientos de contratación, y datos del catastro público del SRI. Se muestran
con la única finalidad de que puedas relacionarte con la entidad en un procedimiento concreto o
completar los datos de tu propia empresa.

Está prohibido usar esos datos para cualquier otro fin: elaborar listas de contactos, enviar
comunicaciones comerciales a funcionarios o cualquier tratamiento ajeno al procedimiento al que
pertenecen. Si lo haces, actúas como responsable de ese tratamiento y respondes de él frente a los
titulares y a la Autoridad de Protección de Datos Personales.


11. PROPIEDAD INTELECTUAL

El software del Servicio, su código fuente y objeto, su diseño, sus bases de datos en cuanto a su
selección y disposición, sus textos, gráficos y su marca están protegidos por el Código Orgánico de
la Economía Social de los Conocimientos, Creatividad e Innovación y pertenecen al Prestador o a
quien le haya cedido los derechos. Estas condiciones no te transfieren ningún derecho sobre ellos:
solo te conceden una licencia de uso limitada, no exclusiva, intransferible y revocable, válida
mientras tu cuenta esté activa.

Los datos públicos que se muestran pertenecen a sus fuentes. Los documentos que subes y lo que
generas con el Servicio para tu empresa son tuyos; nos concedes únicamente el permiso necesario para
tratarlos con el fin de prestarte el Servicio.


12. CONFIDENCIALIDAD

Cada parte mantendrá en reserva la información confidencial de la otra a la que acceda por razón del
Servicio y la usará solo para lo previsto aquí. La obligación se mantiene durante tres años después
de terminar la relación.


13. DISPONIBILIDAD Y CAMBIOS DEL SERVICIO

El Servicio depende de portales de terceros. Si la fuente oficial deja de publicar, cambia su formato
o limita el acceso, la información puede llegar con retraso o no llegar; hacemos lo razonable por
detectarlo y avisarte, pero no podemos garantizar la disponibilidad ininterrumpida ni la ausencia
de errores.

Podemos hacer mantenimiento, actualizar el Servicio o modificar sus funciones. Cuando un cambio
reduzca de forma sustancial lo que se ofrece, lo comunicaremos con antelación razonable y podrás
cancelar la cuenta sin coste.


14. GARANTÍAS Y LÍMITE DE RESPONSABILIDAD

El Servicio se presta «tal cual» y «según disponibilidad». En la medida en que la ley lo permita, el
Prestador no garantiza que los datos sean completos o exactos, ni que el uso del Servicio o de los
borradores generados con inteligencia artificial te reporte un resultado comercial o administrativo
concreto, como la adjudicación de un contrato.

En la medida en que la ley lo permita, el Prestador no responde de daños indirectos, lucro cesante
ni pérdida de oportunidades derivados del uso del Servicio o de la imposibilidad de usarlo. La
responsabilidad total del Prestador se limita al importe que hayas pagado por el Servicio en los
doce meses anteriores a la reclamación o, si el uso ha sido gratuito, a cien dólares de los Estados
Unidos de América.

Nada en esta cláusula excluye la responsabilidad que la ley no permita limitar —en particular la
derivada de dolo o culpa grave, o la que corresponda por infracciones a la normativa de protección
de datos personales— ni afecta a los derechos que la ley reconoce a los consumidores.


15. INDEMNIDAD

Te comprometes a mantener indemne al Prestador frente a reclamaciones de terceros —incluidos los
gastos de defensa razonables— que se deriven del uso que hagas del Servicio, de los datos o
documentos que introduzcas o del incumplimiento de estas condiciones, en particular de los puntos 9
y 10.


16. SUSPENSIÓN Y TERMINACIÓN

Puedes dejar de usar el Servicio y solicitar la baja de tu cuenta o de la de tu empresa cuando
quieras, por el canal de contacto.

El Prestador puede suspender o cancelar el acceso, con aviso previo cuando sea posible, si se
incumplen estas condiciones, si hay un riesgo para la seguridad del Servicio o de terceros, si lo
exige una autoridad competente o si no se paga un plan contratado. En los casos graves, y cuando la
ley lo permita, la suspensión puede ser inmediata.

Al terminar, se desactiva el acceso y los datos se tratan conforme a la Política de privacidad. Las
obligaciones que por su naturaleza deban sobrevivir —confidencialidad, propiedad intelectual,
indemnidad y límite de responsabilidad— siguen vigentes.


17. CAMBIOS EN ESTAS CONDICIONES

Podemos actualizar estas condiciones por cambios legales, técnicos o del Servicio. Cada versión
nueva se publica con su número y su fecha, y el aplicativo te pedirá aceptarla antes de seguir
usándolo; tu aceptación anterior queda registrada tal y como la diste. Si no estás de acuerdo con
una versión nueva, puedes dejar de usar el Servicio y pedir la baja sin coste.

Para aceptar y conservar estas condiciones basta un navegador web actual; puedes leer en todo
momento la versión vigente en la dirección /terminos del sitio y pedir una copia por el canal de
contacto (arts. 48 y 49 de la Ley de Comercio Electrónico, Firmas y Mensajes de Datos).


18. CESIÓN, NULIDAD PARCIAL E INTEGRIDAD

No puedes ceder tu posición en estas condiciones sin autorización escrita del Prestador. El
Prestador puede cederlas a quien continúe el Servicio, avisándote con antelación razonable.

Si alguna cláusula se declara nula o inaplicable, se tendrá por no puesta y el resto seguirá
vigente. Estas condiciones, la Política de privacidad y las condiciones económicas del plan
contratado son el acuerdo completo entre las partes.


19. LEY APLICABLE, JURISDICCIÓN Y RECLAMACIONES

Estas condiciones se rigen por la ley de la República del Ecuador. Antes de acudir a un juez, las
partes intentarán resolver cualquier controversia de buena fe por el canal de contacto.

Si no hay acuerdo, se someten a los jueces competentes de «[CIUDAD DEL DOMICILIO DEL
RESPONSABLE]», Ecuador. Si contratas como consumidor, será competente el juez de tu domicilio,
como dispone el art. 47 de la Ley de Comercio Electrónico, Firmas y Mensajes de Datos.

Las reclamaciones sobre datos personales pueden presentarse además ante la Superintendencia de
Protección de Datos Personales, como se explica en la Política de privacidad.


20. ACEPTACIÓN

Al marcar la casilla y continuar, declaro que he leído, comprendido y aceptado estos términos y
condiciones de uso.
"""

PRIVACIDAD_V1 = """\
POLÍTICA DE PRIVACIDAD Y TRATAMIENTO DE DATOS PERSONALES DE CERCOAPP
Versión 1 · Vigente desde el 13 de noviembre de 2026

Esta política explica qué datos personales trata CercoApp, para qué, con qué base legal, con quién
se comparten, cuánto tiempo se guardan y cómo puedes ejercer tus derechos. Se dicta en cumplimiento
de la Ley Orgánica de Protección de Datos Personales (en adelante, «LOPDP»; Registro Oficial,
Quinto Suplemento 459, de 26 de mayo de 2021), en especial de su artículo 12, y de su Reglamento
General (Registro Oficial, Tercer Suplemento 435, de 13 de noviembre de 2023).


1. RESPONSABLE DEL TRATAMIENTO

Responsable: «[NOMBRE O RAZÓN SOCIAL DEL RESPONSABLE]»
RUC: «[RUC DEL RESPONSABLE]»
Domicilio legal: «[DIRECCIÓN DEL DOMICILIO LEGAL]», Ecuador
Teléfono: «[TELÉFONO DE CONTACTO]»
Correo electrónico: «[CORREO DE CONTACTO]»

Delegado de protección de datos personales: «[NOMBRE DEL DELEGADO DE PROTECCIÓN DE DATOS]»,
correo «[CORREO DEL DELEGADO DE PROTECCIÓN DE DATOS]».

Cada empresa cliente decide qué datos de su propio personal y de sus contactos introduce en el
Servicio. Respecto de esos datos, la empresa cliente es responsable y CercoApp actúa como encargado
del tratamiento, siguiendo sus instrucciones y solo para prestarle el Servicio.


2. QUÉ DATOS TRATAMOS Y DE DÓNDE SALEN

a) Datos que nos das al registrarte y al usar tu cuenta: nombre, correo electrónico, teléfono, cargo
   y rol dentro de la empresa, y tu contraseña, que se guarda transformada con un algoritmo de
   derivación de claves (Argon2) y nunca en texto legible.

b) Datos de tu empresa: RUC, razón social, nombre comercial, dirección, ciudad, actividad económica,
   datos del Registro Único de Proveedores (RUP), experiencia y contactos. Entre ellos pueden estar
   el nombre y el número de cédula del representante legal y los datos de contacto de las personas
   que tu empresa registre.

c) Datos que se obtienen de fuentes de acceso público: al registrar el RUC, el Servicio consulta el
   catastro público del Servicio de Rentas Internas (SRI) para completar los datos de la empresa,
   incluido el nombre e identificación del representante legal; y lee los datos abiertos del SERCOP
   sobre procesos de contratación, que incluyen nombres y datos de contacto de funcionarios de las
   entidades contratantes.

d) Datos técnicos y de seguridad: dirección IP, agente de usuario (navegador y sistema), fecha y hora
   de inicio y cierre de sesión, registro de auditoría de acciones relevantes y la evidencia de cada
   aceptación de estas políticas (versión, huella digital del texto, fecha, IP y agente de usuario).

e) Contenidos que subes o generas: pliegos, términos de referencia y anexos que decides analizar,
   documentos del RUP en PDF, proformas y ofertas, palabras clave, búsquedas y alertas guardadas, y
   las conversaciones con el asistente de inteligencia artificial.

f) Créditos de IA: solicitudes de paquetes, saldo y movimientos. No pedimos ni guardamos datos de
   tarjetas ni de cuentas bancarias.

No pedimos datos sensibles (salud, origen étnico, religión, opiniones políticas, datos biométricos,
etc.). No los incluyas en el Servicio. El certificado de firma electrónica y su clave, cuando firmas
un documento, se usan solo en memoria durante la operación y no se guardan.


3. PARA QUÉ LOS USAMOS Y CON QUÉ BASE LEGAL

   - Crear y gestionar tu cuenta y la de tu empresa, y prestarte el Servicio: búsquedas, alertas,
     estadísticas, documentos, proformas y exportaciones. Base: ejecución del contrato que aceptas
     con los Términos y condiciones (art. 7, numeral 5, LOPDP).
   - Completar los datos de la empresa desde el catastro del SRI y mostrar la información pública
     de contratación del SERCOP. Base: tratamiento de datos que constan en bases de datos de acceso
     público (art. 7, numeral 7) y ejecución del contrato.
   - Enviarte avisos del Servicio por correo electrónico: alertas de nuevas contrataciones según tus
     palabras clave, vencimientos e incidencias. Base: ejecución del contrato.
   - Funciones de inteligencia artificial que tú pides (asistente, lectura de pliegos, redacción de
     ofertas). Base: ejecución del contrato y tu consentimiento, que otorgas al aceptar esta política
     y que incluye la transferencia internacional descrita en el punto 5 (art. 7, numerales 1 y 5).
   - Seguridad del Servicio: control de sesiones, prevención de accesos indebidos, de fraude y de
     extracción masiva de datos, y registro de auditoría. Base: interés legítimo del responsable en
     proteger el Servicio y a sus usuarios (arts. 7, numeral 8, y 9).
   - Conservar la prueba de qué textos aceptaste y cuándo. Base: interés legítimo y el deber de
     poder demostrar el cumplimiento de la ley (art. 10, letra k, responsabilidad proactiva).
   - Cumplir obligaciones legales, tributarias o requerimientos de autoridad competente. Base:
     obligación legal (art. 7, numeral 2).
   - Elaborar estadísticas internas agregadas que no te identifican.

Hoy el Servicio no envía comunicaciones comerciales ni publicidad. Si en el futuro quisiéramos
hacerlo, te pediremos un consentimiento separado, que podrás negar o retirar sin que afecte a tu
acceso al Servicio.

Si no nos das los datos marcados como obligatorios, no podremos crear la cuenta ni prestarte el
Servicio. Si los datos que nos das son erróneos o inexactos, las búsquedas, alertas y documentos que
prepares pueden salir con errores, y respondes de los perjuicios que eso cause a terceros.


4. CON QUIÉN COMPARTIMOS LOS DATOS

No vendemos ni alquilamos datos personales. Solo acceden a ellos, por cuenta nuestra y para prestar
el Servicio, estos encargados del tratamiento (art. 34 LOPDP):

   - Infraestructura en la nube donde se ejecutan la aplicación, la base de datos PostgreSQL y el
     almacén Redis: Railway Corp., con servidores en los Estados Unidos de América.
   - Alojamiento y entrega del sitio web: «[PROVEEDOR DEL ALOJAMIENTO WEB Y SU PAÍS]».
   - Envío de correos electrónicos de aviso: «[PROVEEDOR DE CORREO SMTP Y SU PAÍS]».
   - Proveedores de modelos de lenguaje para las funciones de inteligencia artificial:
     «[PROVEEDORES DE IA EN USO Y SU PAÍS]».

Dentro de tu empresa, el administrador y los usuarios que él autorice ven los datos de la empresa
según su rol. Los datos de cada empresa están aislados de los de las demás.

También comunicaremos datos a autoridades públicas cuando una ley u orden competente lo exija.


5. TRANSFERENCIAS INTERNACIONALES

Los proveedores del punto 4 pueden tratar los datos fuera del Ecuador, principalmente en los Estados
Unidos de América. Mientras la Autoridad de Protección de Datos Personales no declare a esos países
con nivel adecuado de protección (art. 56 LOPDP), la transferencia se apoya en que es necesaria para
ejecutar el contrato que celebras con nosotros (art. 60, numeral 4) y en tu consentimiento explícito
(art. 60, numeral 2), que otorgas al aceptar esta política tras haber sido informado de que en esos
países la protección puede no ser equivalente a la ecuatoriana. Además, procuramos que cada
proveedor ofrezca garantías contractuales adecuadas (art. 57 LOPDP).

En concreto, cuando usas una función de inteligencia artificial, el texto que escribes y el
contenido de los documentos que eliges analizar se envían al proveedor del modelo para obtener la
respuesta. Si no quieres esa transferencia, no uses las funciones de inteligencia artificial: el
resto del Servicio funciona sin ellas.


6. CUÁNTO TIEMPO LOS GUARDAMOS

   - Datos de la cuenta y de la empresa: mientras la cuenta esté activa. Cuando se da de baja la
     cuenta o la empresa, se eliminan, salvo lo que debamos conservar por obligación legal o para
     formular o defender reclamaciones.
   - Sesiones: la credencial de renovación caduca a los 30 días como máximo, o antes si cierras la
     sesión o pasa el tiempo de inactividad.
   - Registros de acceso, de auditoría y evidencia de aceptaciones: «[PLAZO DE CONSERVACIÓN DE
     REGISTROS]», porque son la prueba de lo ocurrido.
   - Archivos de pliegos y anexos subidos para su lectura: se borran automáticamente a los dos días.
   - Exportaciones a Excel generadas en segundo plano: caducan a las 24 horas.
   - Conversaciones con el asistente: hasta que las borres; se guardan como máximo las 50 más
     recientes de cada usuario y las más antiguas se eliminan solas.
   - Procesos de ínfima cuantía y sus contactos públicos: se retiran por defecto 7 días después de
     vencido el plazo de proformas.

Cumplido el plazo, los datos se eliminan de forma segura o se anonimizan (arts. 9 y 11 del
Reglamento General).


7. TUS DERECHOS

La LOPDP te reconoce, de forma gratuita, los derechos de:
   - información (art. 12);
   - acceso a tus datos (art. 13);
   - rectificación y actualización (art. 14);
   - eliminación (art. 15);
   - oposición (art. 16);
   - portabilidad: recibir tus datos en un formato estructurado y de uso común (art. 17);
   - suspensión del tratamiento (art. 19);
   - no ser objeto de decisiones basadas únicamente en valoraciones automatizadas que produzcan
     efectos jurídicos en ti o afecten a tus derechos (art. 20);
   - revocar tu consentimiento en cualquier momento, sin efectos retroactivos (art. 8).

Cómo ejercerlos: escribe a «[CORREO DEL DELEGADO DE PROTECCIÓN DE DATOS]» o a «[CORREO DE
CONTACTO]» indicando tus nombres y apellidos, el número de cédula o pasaporte, un correo para
notificaciones, el derecho que quieres ejercer y lo que pides, y acompaña un documento que acredite
tu identidad o tu representación (arts. 12 y 13 del Reglamento General). Muchos datos puedes
corregirlos tú mismo desde el perfil del panel. Si falta información, te la pediremos una sola vez
dentro de los cinco días siguientes (art. 14 del Reglamento General).

Responderemos dentro del término de diez (10) días desde que recibamos la solicitud completa
(art. 62 LOPDP), y en ningún caso después de los plazos que la LOPDP fija para cada derecho.

Si no respondemos o no estás de acuerdo con la respuesta, puedes presentar un reclamo ante la
Superintendencia de Protección de Datos Personales (art. 64 LOPDP), sin perjuicio de las acciones
judiciales que te correspondan.

Retirar el consentimiento o pedir la eliminación de los datos imprescindibles para la cuenta impide
seguir prestando el Servicio, y el aplicativo quedará bloqueado hasta que se resuelva. Hay casos en
los que la ley permite conservar datos pese a la solicitud, por ejemplo para cumplir una obligación
legal o defender reclamaciones (art. 18 LOPDP); si es tu caso, te lo explicaremos de forma motivada.


8. DECISIONES AUTOMATIZADAS E INTELIGENCIA ARTIFICIAL

El Servicio ordena procesos y sugiere oportunidades según tus palabras clave, códigos CPC y el perfil
de tu empresa, y usa inteligencia artificial para redactar borradores. Son sugerencias: no se toma
ninguna decisión que produzca efectos jurídicos sobre ti sin intervención humana, y siempre puedes
pedir una explicación de cómo funcionan, presentar observaciones o impugnarlas (art. 20 LOPDP).

No usamos tus datos ni tus documentos para entrenar modelos de inteligencia artificial propios.


9. SEGURIDAD

Aplicamos medidas técnicas y organizativas proporcionales al riesgo (art. 37 LOPDP), entre ellas:
cifrado de las comunicaciones (HTTPS), contraseñas guardadas con Argon2, sesiones con caducidad y un
máximo de dos sesiones por cuenta, bloqueo tras intentos fallidos, frenos de uso por usuario y por
dirección IP, aislamiento de los datos de cada empresa en la base de datos y registro de auditoría
de las acciones relevantes.

Ningún sistema es invulnerable. Si se produce una vulneración de seguridad que afecte a tus datos,
la notificaremos a la Autoridad de Protección de Datos Personales y a la Agencia de Regulación y
Control de las Telecomunicaciones a más tardar en el término de cinco días desde que tengamos
constancia (art. 43 LOPDP) y, cuando suponga un riesgo para tus derechos, te la comunicaremos a ti
dentro del término de tres días (art. 46 LOPDP).


10. ALMACENAMIENTO EN TU NAVEGADOR

El Servicio no usa cookies de publicidad ni de analítica, ni herramientas de seguimiento de
terceros. Para funcionar guarda en tu navegador:
   - en el almacenamiento de sesión (sessionStorage), la credencial de renovación de tu sesión, que
     se borra al cerrar el navegador;
   - en el almacenamiento local (localStorage), preferencias de la interfaz —tema claro u oscuro,
     menú plegado, filtros y gráficas visibles— y la última conversación abierta del asistente.
Puedes borrarlos desde la configuración de tu navegador; si lo haces, tendrás que volver a iniciar
sesión y se perderán esas preferencias.


11. MENORES DE EDAD

El Servicio está dirigido a empresas y profesionales mayores de edad. No recogemos a sabiendas datos
de niñas, niños ni adolescentes; si detectamos que se han registrado, los eliminaremos.


12. CAMBIOS EN ESTA POLÍTICA

Si cambiamos esta política, publicaremos una versión nueva con su número y fecha y te pediremos que
la aceptes antes de seguir usando el Servicio. La versión vigente puede leerse en todo momento, sin
iniciar sesión, en la dirección /privacidad del sitio.


13. ACEPTACIÓN

Al marcar la casilla y continuar, declaro que he leído y comprendido esta política y que consiento,
de forma libre, específica, informada e inequívoca, el tratamiento de mis datos personales en los
términos descritos, incluida la transferencia internacional explicada en el punto 5.
"""

# (tipo, versión, texto). El orden es el de publicación.
PUBLICACIONES: tuple[tuple[str, int, str], ...] = (
    ("terminos_uso", 3, TERMINOS_V3),
    ("tratamiento_datos", 1, PRIVACIDAD_V1),
)

# El marcador de la cuenta guarda **una** versión: basta con que no sea nula para que la puerta
# bloquee. Se usa la mayor de las publicadas aquí, como hace el dominio con las obligatorias.
VERSION_MARCADOR = max(version for _, version, _ in PUBLICACIONES)

_ENTORNOS_PRODUCCION = frozenset({"prod", "produccion", "production"})


def _normalizar(texto: str) -> str:
    """La misma normalización que aplica el dominio antes de calcular la huella (ver la 0006)."""
    unificado = texto.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(linea.rstrip() for linea in unificado.strip().split("\n"))


def _huella(texto: str) -> str:
    return hashlib.sha256(_normalizar(texto).encode("utf-8")).hexdigest()


def _es_produccion() -> bool:
    """¿Se está migrando la base de producción?

    Se lee de los ajustes de la aplicación —que es de donde lo lee también `env.py` para la URL— y,
    si no se pudieran cargar, de la variable de entorno. Ante la duda se responde «no» solo si
    ninguna de las dos fuentes dice producción.
    """
    try:
        from contratacion.infraestructura.config.ajustes import obtener_ajustes

        entorno = obtener_ajustes().entorno
    except Exception:  # noqa: BLE001 — sin ajustes se mira la variable directamente
        entorno = os.environ.get("ENTORNO", "")
    return entorno.strip().lower() in _ENTORNOS_PRODUCCION


def _faltan_datos_en_produccion() -> bool:
    """En producción, con marcadores sin rellenar, **no se publica** (pero el deploy sigue).

    Antes se lanzaba un error: con el arranque `alembic upgrade head && uvicorn`, eso tumbaba el
    deploy entero, y un deploy fallido en Railway puede dejar el API caído. Una política obligatoria
    sin publicar no se exige (`dominio/politicas.py::pendientes`), así que saltar la publicación es
    seguro: siguen vigentes los términos v2. Cuando estén los datos del responsable, los textos se
    publican con una migración **nueva** (esta ya habrá quedado aplicada). Ver docs/40.
    """
    pendientes = [tipo for tipo, _, texto in PUBLICACIONES if MARCADOR in texto]
    if pendientes and _es_produccion():
        print(  # se ve en el log del deploy
            "AVISO 0044: textos legales con marcadores «[…]» sin rellenar "
            f"({', '.join(pendientes)}): no se publican en producción. Ver docs/40."
        )
        return True
    return False


def upgrade() -> None:
    if _faltan_datos_en_produccion():
        return
    conexion = op.get_bind()

    for tipo, version, texto in PUBLICACIONES:
        huella = _huella(texto)
        existente = conexion.execute(
            sa.text(
                "SELECT texto, hash FROM politica_version WHERE tipo = :tipo AND version = :version"
            ),
            {"tipo": tipo, "version": version},
        ).first()
        if existente is not None:
            if existente.hash != huella:
                raise RuntimeError(
                    f"La versión {version} de «{tipo}» ya está publicada con un texto distinto al "
                    "de esta migración. No se sobrescribe: si el cambio es intencionado, publica "
                    "una versión nueva en lugar de reescribir la que los usuarios ya aceptaron."
                )
            continue

        mayor = conexion.execute(
            sa.text("SELECT max(version) FROM politica_version WHERE tipo = :tipo"),
            {"tipo": tipo},
        ).scalar_one_or_none()
        if mayor is not None and mayor >= version:
            raise RuntimeError(
                f"Ya hay publicada la versión {mayor} de «{tipo}», posterior a la {version} que "
                "trae esta migración. Publicarla dejaría vigente un texto más antiguo: revisa qué "
                "se publicó por otro camino antes de seguir."
            )

        conexion.execute(
            sa.text(
                """
                INSERT INTO politica_version (tipo, version, texto, hash, vigente_desde)
                VALUES (:tipo, :version, :texto, :hash, now())
                """
            ),
            {"tipo": tipo, "version": version, "texto": texto, "hash": huella},
        )

    # Todas las cuentas deben aceptar los dos textos. Solo se sube el marcador de quien lo tenga
    # vacío o por debajo; no se supone nada sobre cuántas cuentas hay ni qué valor tienen.
    conexion.execute(
        sa.text(
            """
            UPDATE usuario
            SET debe_aceptar_politica_version = :version
            WHERE debe_aceptar_politica_version IS NULL
               OR debe_aceptar_politica_version < :version
            """
        ),
        {"version": VERSION_MARCADOR},
    )


def downgrade() -> None:
    """Retira lo publicado, con la salvaguarda de la 0006: no si alguien ya lo aceptó."""
    conexion = op.get_bind()
    for tipo, version, _ in PUBLICACIONES:
        aceptaciones = conexion.execute(
            sa.text(
                """
                SELECT count(*) FROM consentimiento
                WHERE tipo = :tipo AND version_texto = :version
                """
            ),
            {"tipo": tipo, "version": str(version)},
        ).scalar_one()
        if aceptaciones:
            raise RuntimeError(
                f"Hay {aceptaciones} aceptaciones registradas de «{tipo}» versión {version}. No se "
                "puede retirar el texto mientras exista la evidencia."
            )

    for tipo, version, _ in PUBLICACIONES:
        conexion.execute(
            sa.text("DELETE FROM politica_version WHERE tipo = :tipo AND version = :version"),
            {"tipo": tipo, "version": version},
        )

    # Quien tenía aceptada y vigente la versión 2 de los términos vuelve a estar al día; el resto
    # sigue debiendo la 2, que vuelve a ser la vigente.
    conexion.execute(
        sa.text(
            """
            UPDATE usuario u
            SET debe_aceptar_politica_version = NULL
            WHERE EXISTS (
                SELECT 1 FROM consentimiento c
                WHERE c.usuario_id = u.id
                  AND c.tipo = 'terminos_uso'
                  AND c.version_texto = '2'
                  AND c.revocado_en IS NULL
            )
            """
        )
    )
    conexion.execute(
        sa.text(
            """
            UPDATE usuario
            SET debe_aceptar_politica_version = 2
            WHERE debe_aceptar_politica_version IS NOT NULL
            """
        )
    )
