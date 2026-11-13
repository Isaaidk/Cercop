# 40 · Cumplimiento de la LOPDP y textos legales

Fecha: 13 de noviembre de 2026.

> **Aviso.** Este documento y los textos que acompaña son un borrador técnico-jurídico preparado a
> partir de la ley y del funcionamiento real del código. **No sustituyen la revisión de un abogado
> ecuatoriano** y **ningún texto garantiza la inmunidad frente a reclamos o sanciones**: el
> cumplimiento depende sobre todo de lo que se haga fuera del código (designaciones, contratos,
> registros, procedimientos) y de que lo que dicen los textos siga siendo cierto con el tiempo.

## Normas de referencia

- **Ley Orgánica de Protección de Datos Personales (LOPDP)**, Registro Oficial, Quinto Suplemento
  459, 26-may-2021. Artículos usados: 7 (bases de legitimación), 8 (consentimiento y revocatoria),
  9 (interés legítimo), 10 (principios), 12 (derecho a la información: contenido mínimo del aviso),
  13 a 17 (acceso, rectificación y actualización, eliminación, oposición, portabilidad), 18
  (excepciones), 19 (suspensión), 20 (decisiones automatizadas), 33 a 36 (transferencia y acceso del
  encargado), 37, 39 a 42 (seguridad, diseño y por defecto, riesgos, evaluación de impacto), 43 y 46
  (notificación de vulneraciones: Autoridad y ARCOTEL en el término de 5 días; titulares en el
  término de 3 días cuando hay riesgo), 47 (obligaciones de responsable y encargado), 48 a 50
  (delegado), 51 (Registro Nacional), 55 a 60 (transferencias internacionales), 62 (requerimiento
  directo: término de 10 días para contestar), 64 (reclamo ante la Autoridad).
- **Reglamento General de la LOPDP**, Decreto Ejecutivo 904, Registro Oficial, Tercer Suplemento
  435, 13-nov-2023. Artículos usados: 5 y 6 (recogida y revocatoria del consentimiento), 8 a 11
  (conservación, eliminación, anonimización), 12 a 16 (medios, contenido de la solicitud, pedido de
  información adicional en 5 días, registro de solicitudes, reclamo), 24 a 28 (vulneraciones), 29 a
  32 (evaluación de impacto), 38 (registro de actividades, obligatorio desde 100 trabajadores), 41
  (contrato escrito responsable–encargado), 48 a 57 (delegado), 74 (instrumentos para transferencias
  con garantías adecuadas), 86 (inscripción en el Registro Nacional en el término de 10 días desde el
  inicio del tratamiento).
- **Ley de Comercio Electrónico, Firmas y Mensajes de Datos**: art. 2 (valor jurídico de los
  mensajes de datos), 45 y 46 (contratos electrónicos), 47 (jurisdicción: en contratos con
  consumidores, el domicilio del consumidor), 48 a 50 (consentimiento e información al consumidor
  en servicios electrónicos). Su art. 9 (protección de datos) está **derogado** por la LOPDP.
- **Código Orgánico de la Economía Social de los Conocimientos, Creatividad e Innovación**: protección
  del software y las bases de datos por derecho de autor (se cita la norma, sin número de artículo).
- **Ley Orgánica de Defensa del Consumidor**: se salvan expresamente los derechos del consumidor
  (sin número de artículo).

Fuentes consultadas: textos consolidados de la LOPDP (Lexis, vía repositorio de la UTPL), del
Reglamento General (Ediciones Legales, vía repositorio de ESPOL) y de la Ley de Comercio Electrónico
(Lexis, vía ARCOTEL). Antes de publicar, **comprobar si hubo reformas posteriores**.

## Qué se implementó

### Textos (migración `backend/alembic/versions/0044_politicas_lopdp.py`)

| Tipo (`politica_version.tipo`) | Versión | Título | Obligatoria |
|---|---|---|---|
| `terminos_uso` | 3 | Términos y condiciones de uso | Sí |
| `tratamiento_datos` | 1 | Política de privacidad y tratamiento de datos personales | Sí (nueva) |

- Mismo mecanismo que la `0006` y la `0022`: texto y huella SHA-256 (misma normalización que el
  dominio) en la misma sentencia, y marcado de todas las cuentas como pendientes.
- Defensiva: si la versión ya existe con la misma huella no hace nada; si existe con otra, o hay una
  versión mayor publicada, se detiene (es una decisión humana). El marcado no supone nada sobre las
  cuentas existentes.
- **Se niega a correr con `ENTORNO=produccion` mientras queden marcadores `«[…]»`** en los textos.
  Una versión publicada no se puede corregir sin obligar a todos a aceptar otra.
- Los términos v3 dejan de contener la información de datos personales (pasa a la política) y dejan
  de empaquetar el consentimiento para ofertas comerciales: hoy el servicio no envía publicidad y,
  si algún día lo hace, pedirá un consentimiento separado (art. 8: consentimiento específico).

### Dominio y casos de uso

- `TipoPolitica.TRATAMIENTO_DATOS` ya existía y la restricción `CHECK` de `consentimiento` ya lo
  admitía desde la `0001`: no hubo cambios de esquema.
- `POLITICAS_OBLIGATORIAS = (TERMINOS_USO, TRATAMIENTO_DATOS)` y `POLITICAS_PUBLICAS` (las que se
  leen sin cuenta) en `dominio/politicas.py`.
- **Corrección de seguridad:** `aceptar` limpiaba el marcador de bloqueo al aceptar *cualquier*
  texto. Con dos obligatorios, aceptar los términos habría dejado entrar sin aceptar la política de
  privacidad. Ahora recalcula los pendientes y solo levanta el bloqueo cuando no falta ninguno.

### Endpoint público

`GET /v1/politicas/publicas/{tipo}` (sin cuenta): devuelve `tipo`, `titulo`, `version`, `hash`,
`vigente_desde` y `texto`. Solo sirve `POLITICAS_PUBLICAS` (otro tipo → 404). Freno por IP de 60
peticiones cada 10 minutos (`proteccion.py`). Pruebas en `pruebas/unidad/test_politicas_lopdp.py`.

### Panel

- `PantallaPolitica.vue` pinta un texto por tipo con su versión, fecha y huella, y permite imprimir
  o guardar en PDF (art. 49 LCE: obtener copia).
- Rutas públicas `/terminos` y `/privacidad` (`utils/enrutado.js`, `App.vue`), visibles con o sin
  sesión, también con la aceptación pendiente. Fichas SEO y `sitemap.xml` actualizados.
- `AceptacionTerminos.vue` ya encadenaba los pendientes; ahora la casilla y el enlace dicen el
  nombre del documento que se está aceptando en lugar de «términos y condiciones» siempre.
- **Pendiente para quien edita `PiePublico.vue` y `PantallaRegistro.vue`:** enlazar `/terminos` y
  `/privacidad` en el pie público y junto al botón de registro (art. 12: informar en el momento de
  la recogida). No se tocaron aquí porque otra tarea los estaba editando.

## Datos que trata la aplicación (inventario verificado en el código)

| Categoría | Origen | Dónde | Conservación hoy |
|---|---|---|---|
| Cuenta: nombre, correo, teléfono, rol, hash Argon2 | Usuario | `usuario` | Mientras exista la cuenta |
| Empresa: RUC, razón social, dirección, RUP, contactos, representante legal (nombre, cédula) | Usuario y catastro SRI | perfil | Mientras exista la empresa |
| Sesiones: IP, agente de usuario | Técnico | `sesion` | Renovación 30 días; **sin purga de filas** |
| Auditoría | Técnico | `auditoria` (particionada) | **Sin purga** |
| Evidencia de aceptación (versión, huella, IP, UA) | Técnico | `consentimiento` | Indefinida (prueba) |
| Pliegos/anexos subidos | Usuario | `archivo_tdr` | 2 días |
| Conversaciones del asistente | Usuario | `asistente_*` | Hasta 50 por usuario |
| Procesos SERCOP con contactos de funcionarios | Datos abiertos | `registro` | Ínfimas: 7 días tras plazo (`PURGA_PLAZO_DIAS`) |
| Certificado .p12 y clave | Usuario | Solo memoria | No se guarda |
| Créditos de IA | Usuario / super admin | créditos | Mientras exista la empresa |

Almacenamiento en el navegador: `sessionStorage` (token de renovación) y `localStorage` (tema,
preferencias, última conversación). Sin cookies ni analítica de terceros.

Encargados / destinos: Railway (EE. UU., aplicación, PostgreSQL y Redis), alojamiento del sitio web
(el repo trae `vercel.json`), servidor SMTP de alertas, proveedor del modelo de IA configurado en
`IA_URL` (API compatible con OpenAI: Groq, Gemini, DeepSeek, OpenRouter…). **Todos ellos implican
transferencia internacional.**

## Lista de lo que debe hacer el titular (fuera del código)

1. **Rellenar los marcadores** de `0044_politicas_lopdp.py` antes de desplegar: nombre o razón
   social, RUC, domicilio, teléfono, correo de contacto, delegado (nombre y correo), proveedores
   reales de alojamiento web, de correo y de IA con su país, plazo de conservación de registros y
   ciudad para la jurisdicción. Los términos v2 ya publicaron un nombre y un correo de contacto;
   comprobar que siguen siendo correctos. Sin rellenarlos, la migración no corre en producción.
2. **Revisión por un abogado ecuatoriano** de los dos textos, de este inventario y de las bases de
   legitimación elegidas. Comprobar reformas posteriores de la LOPDP y del Reglamento.
3. **Delegado de protección de datos** (art. 48 LOPDP; arts. 48 a 57 del Reglamento): valorar si
   el tratamiento es «control permanente y sistematizado» (art. 53 del Reglamento) —el servicio
   trata datos de forma continua y metódica— y designarlo, o documentar por qué no procede. En
   cualquier caso, mantener un contacto de privacidad atendido.
4. **Registro Nacional de Protección de Datos Personales** (art. 51 LOPDP; art. 86 del Reglamento:
   término de 10 días desde el inicio del tratamiento) ante la Superintendencia de Protección de
   Datos Personales, cuando el registro esté habilitado; incluir las transferencias internacionales
   (art. 59 LOPDP; art. 78 del Reglamento).
5. **Contratos de encargo** (art. 41 del Reglamento) con Railway, el proveedor de alojamiento web,
   el de correo y cada proveedor de IA: aceptar sus DPA / anexos de tratamiento de datos y guardar
   copia. Para transferencias, preferir proveedores con cláusulas tipo u otras garantías del art. 74
   del Reglamento. Revisar en cada proveedor de IA que **no use los datos para entrenar** (la
   política lo afirma) y, si alguno no lo garantiza, cambiarlo o cambiar el texto.
6. **Registro de actividades de tratamiento**: obligatorio desde 100 trabajadores (art. 38 del
   Reglamento); recomendable siempre como prueba de responsabilidad proactiva. Puede partir de la
   tabla de inventario de arriba.
7. **Evaluación de impacto** (art. 42 LOPDP; arts. 29 a 32 del Reglamento): valorar si aplica
   (perfiles de empresas, tratamiento a gran escala de datos públicos de funcionarios). Si hay duda,
   la Autoridad debe contestar la consulta en 5 días (art. 31 del Reglamento).
8. **Procedimiento de vulneraciones**: quién detecta, quién decide, plantilla de notificación con el
   contenido del art. 26 del Reglamento, notificación a la Autoridad y a ARCOTEL en el término de 5
   días y a los titulares en 3 días cuando haya riesgo (arts. 43 y 46 LOPDP). Exigir a los
   encargados aviso en 2 días (art. 43).
9. **Procedimiento de derechos**: buzón atendido, registro de solicitudes (art. 15 del Reglamento),
   respuesta en el término de 10 días (art. 62 LOPDP), formato de exportación para la portabilidad.
   La tabla `solicitud_arco` existe en el esquema pero **no hay flujo en la aplicación**: se atiende
   a mano por correo.
10. **Conservación real** (arts. 8 a 11 del Reglamento): hoy no se purgan `sesion` ni `auditoria`,
    y `RETENCION_DIAS_DATOS_PERSONALES` (365) no se aplica en ningún sitio. Decidir el plazo,
    ponerlo en el marcador de la política e implementar la purga; mientras tanto, el texto debe
    decir la verdad.
11. **Eliminación al dar de baja**: verificar que borrar una empresa o un usuario elimina también
    perfiles, documentos y conversaciones (hoy depende de `ON DELETE CASCADE`), y documentar qué se
    conserva por obligación legal.
12. **Enlaces visibles** a `/terminos` y `/privacidad` en el pie público y en el registro (ver
    arriba), y un aviso breve junto al formulario de registro.
13. **Facturación y consumo**: si se cobra a consumidores, revisar con el abogado la información
    precontractual, devoluciones y comprobantes electrónicos (LODC y normativa tributaria).
14. **Mantener los textos al día**: cada cambio de proveedor, finalidad o plazo exige una versión
    nueva (migración nueva, nunca editar una publicada).
