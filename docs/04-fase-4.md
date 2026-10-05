# Fase 4 — Autenticación, sesiones, presencia y super administrador

| Campo | Valor |
|---|---|
| Estado | **Completada** — 2026-09-29 |
| Depende de | F1 |
| Casos de uso | CU-01, CU-08, CU-10, CU-14 |
| Requisitos | RF-02, RF-03, RF-04, RF-14, RF-15, RNF-06, OE-7, OE-8 |

> **Este documento empezó como plan y acabó describiendo algo distinto.** Los apartados 1 a 4 se
> dejaron como se escribieron, porque son la intención original y sirven para entender por qué se
> tomaron las decisiones. El apartado 5 recoge **lo que de verdad se construyó**, incluido lo que se
> apartó del plan, que es lo que hay que leer antes de tocar nada de aquí.

## 1. Objetivo

Multiusuario seguro con visibilidad operativa en tiempo real: quién está conectado, quién no y
**por qué**.

## 2. Alcance

**Incluido:** login con Argon2id · access token JWT (claim `sid`) + refresh token opaco en Redis
con rotación y detección de reuso · máximo 2 sesiones simultáneas con evicción de la más antigua
por `ultimo_uso` · estados de usuario y de sesión · RBAC (`super_admin`, `admin_negocio`,
`consultor`, `lector`) · presencia en Redis con heartbeat · cierre inmediato por
`navigator.sendBeacon` · notificación asíncrona al panel del administrador mediante SSE
respaldado por Redis Pub/Sub · semáforo por colores · auditoría de acciones sensibles.

**Excluido:** gate de consentimiento (F5), gestión de exportaciones (F6).

## 3. Reglas de sesión y presencia

| Elemento | Definición |
|---|---|
| Estados de usuario | `activo`, `inactivo`, `bloqueado`, `pendiente` |
| Estados de sesión | `activa`, `inactiva`, `revocada`, `expirada`, `reemplazada` |
| Motivos de cierre | `logout`, `cierre_ventana`, `heartbeat_vencido`, `expirado`, `eviccion`, `admin` |
| Evicción | Al 3.er login se revoca la sesión activa con `ultimo_uso` más antiguo, se audita y se avisa al usuario expulsado |
| Presencia | Clave en Redis con TTL 60 s, refrescada por heartbeat cada 30 s |
| Verde | Presencia viva **y** token activo |
| Rojo | Sin presencia, o token revocado/expirado |
| Piso de detección | Cierre abrupto del navegador → el rojo se refleja al vencer el TTL (≤60 s) |

## 4. Criterios de aceptación

- [x] Un 3.er login revoca la sesión más antigua y deja registro en `auditoria` — comprobado en la
  base real: hay sesiones con motivo `eviccion`
- [x] El refresh token rota; reutilizar uno ya usado revoca la familia de sesiones — **con un matiz
  importante**, ver el apartado 5: se admite la generación anterior durante una ventana corta
- [ ] El panel del administrador cambia verde→rojo **sin recargar** la página — el canal de eventos
  está construido y el panel lo consume; **no se ha comprobado a mano en esta sesión**
- [ ] ~~Cerrar la ventana marca al usuario como desconectado de forma proactiva~~ — **se descartó a
  propósito**: `sendBeacon` y `pagehide` no admiten cabeceras de autenticación, y además `pagehide`
  salta al recargar, así que pulsar F5 cerraba la sesión. El rojo llega al vencer la señal
- [x] Un usuario de un negocio no puede ver sesiones de otro negocio — RLS forzado y pruebas de
  aislamiento
- [x] Los estados de sesión expiran por inactividad según configuración
- [x] Argon2id verificado: la base nunca almacena la contraseña en claro

## 5. Riesgos

| Riesgo | Mitigación |
|---|---|
| RS-07 Evicción usada como ataque | Auditoría + notificación + rate limit de login + bloqueo por intentos |
| SSE con varias réplicas | Redis Pub/Sub como bus de eventos |
| Falsos positivos de presencia en redes inestables | TTL como piso, no como medida exacta; documentado en la interfaz |

## 6. Lo que se construyó, y en qué se apartó del plan

Las decisiones del apartado 2 que **no** se siguieron, con su motivo. Es lo primero que hay que leer
antes de tocar esta fase, porque el plan describe un sistema que no es este.

| El plan decía | Se construyó | Por qué |
|---|---|---|
| Refresh token **opaco en Redis** | Huella del token **en la tabla `sesion`** | La rotación con detección de reutilización es una decisión de seguridad y no puede depender de que el almacén esté encendido: con el token en Redis, una caída del almacén deja a todo el mundo fuera |
| Cerrar la ventana con `navigator.sendBeacon` | Nada; el rojo llega al vencer el latido | `sendBeacon` no admite cabeceras, así que la única forma de autenticarlo sería el token en la URL —que acabaría en el registro de cada proxy—, y aceptar el token por el cuerpo abriría una segunda forma de autenticarse. Además `pagehide` también salta al recargar, así que F5 cerraba la sesión |
| Latido con **consulta a la base** | Latido contra el almacén, sin base | Es el camino más transitado del sistema (uno cada 30 s por persona conectada). La base solo se consulta si el almacén **no responde** |
| Instantánea de presencia por conexión | Instantánea **por empresa y alcance**, guardada 3 s | Era el 70 % de las consultas del sistema. La clave lleva el alcance —`todos` o el identificador de la persona— porque sin él se le serviría a un lector la lista completa del administrador |
| Motivo `heartbeat_vencido` | Motivo `sin_senal` | Se llama así porque es lo que es: el navegador dejó de responder. «Latido vencido» describe el mecanismo, no lo que le pasó a la persona |
| Estados de sesión `inactiva`, `reemplazada` | `activa` y `revocada`, con el **motivo** aparte | Un estado por cada forma de cerrarse multiplicaría los valores sin añadir información: el motivo ya dice cuál fue |

Y dos cosas que se añadieron después, al ver el sistema funcionando:

- **Ventana de gracia de 30 s en la rotación** (`refresh_gracia_seg`, migración `0010`). La detección
  estricta de reutilización trataba una **respuesta perdida** como un robo: el servidor rota, la
  respuesta no llega —se corta la conexión, se duerme el portátil— y el navegador reintenta con el
  token viejo, con lo que se cerraban **todas** las sesiones de la cuenta. Se midió en la base: tres
  cierres con motivo `reuso_detectado` en un día, en la cuenta de una persona usando el panel. La
  ventana admite **solo la generación anterior** y solo unos segundos, así que un token robado usado
  un minuto después sigue cerrando todo.
- **Reposición de la clave de sesión perdida.** La comprobación daba por hecho que lo único que
  borra la clave sin cambiar el estado de la sesión es el plazo de inactividad, y es falso: una
  política de memoria que desaloje claves o un reinicio del almacén también la borran. Ahora, si la
  sesión se usó hace poco, la clave se repone **con el tiempo que le queda** y la persona no nota
  nada; si se agotó el plazo, se cierra con su motivo.

Y una tercera tanda, a raíz de exportar contra las plantillas que hay subidas de verdad. Las dos
fallen de maneras que ninguna prueba veía, porque las pruebas las escribimos nosotros y usan
plantillas que nos inventamos:

- **La plantilla manda sobre todo el archivo, y su cabecera no tiene por qué estar en la fila 1.**
  Una de las plantillas reales pone el nombre del informe y el de la familia en las filas 1 a 3, y
  los títulos de verdad en la 4. Buscando solo en la primera fila no se reconocía nada y el sistema
  escribía su propia cabecera **al final** del archivo: el cliente veía dos cabeceras y ningún dato
  bajo la suya.
- **Los títulos de verdad no son los del archivo genérico.** Las plantillas subidas escriben
  «Entidad Contratante», «Estado de la necesidad», «Descripción del Objeto de compra» o «Provincia -
  Cantón». Reconocer solo las etiquetas propias equivale a no reconocer la plantilla.
- **Los datos anteriores se sustituyen, no se arrastran.** Una plantilla nace casi siempre de una
  descarga anterior a la que la empresa dio formato —la subida tiene **1.406 filas** dentro—, así que
  escribiendo debajo la descarga «con los filtros aplicados» llevaba media base histórica dentro.
- **Cada familia a su pestaña.** La plantilla real dedica una hoja a cada familia y sus columnas no
  son las mismas: antes, al descargar ofertas, los datos caían en la hoja de ínfimas.
- **El botón de descarga sigue a la vista.** El botón dominante era «Todo», así que desde la pestaña
  de ínfimas se descargaban las dos familias. Ahora el botón principal manda la familia que se está
  viendo, y «Todo» aparece como alternativa solo cuando de verdad cambia el resultado.
- **El mapa se marca y se desmarca con un solo clic**, sin doble clic. El rectángulo negro que
  aparecía era el contorno de foco del navegador sobre un trazado ancho —más la selección de texto al
  arrastrar sobre el mapa—, y las dos cosas se corrigieron donde se originaban.

## 7. Implementaciones realizadas

Backend (`backend/src/contratacion/`):

| Pieza | Archivo |
|---|---|
| Cómo se llama y qué guarda una sesión viva | `dominio/sesiones_vivas.py` |
| Abrir, seguir y olvidar sesiones; envoltorio del repositorio | `aplicacion/sesiones_vivas.py` |
| Rotación con ventana de gracia | `aplicacion/casos_uso/autenticar.py`, `infraestructura/.../bd/cuentas.py` |
| Comprobación en la puerta y reposición de la clave | `infraestructura/.../http/dependencias.py` |
| Presencia: dominio, puertos, casos de uso, adaptadores y enrutador | `dominio/presencia.py`, `aplicacion/puertos/presencia.py`, `aplicacion/casos_uso/presencia.py`, `salida/presencia/`, `routers/presencia.py` |
| Super administrador de plataforma | `aplicacion/casos_uso/administrar_negocios.py`, `routers/plataforma.py`, migración `0008` |
| Reparto de los datos en la plantilla del cliente | `aplicacion/casos_uso/exportar_registros.py` |
| Migraciones | `0005_resolver_cuenta`, `0006_politica_terminos_v1`, `0007_empresa_y_correo_unico`, `0008_admin_plataforma`, `0009_plantilla_excel`, `0010_gracia_rotacion` |

Frontend (`frontend/src/`):

| Pieza | Archivo |
|---|---|
| Canal de eventos y latido | `composables/usePresencia.js` |
| Renovación silenciosa y mensajes de sesión | `api/cliente.js` |
| Estado de la sesión | `stores/sesion.js` |
| Pestañas, familia de contratación y selector del mapa | `components/VistaPanel.vue` |
| Plantilla de Excel por empresa | `components/PlantillaExcel.vue` |
| Marcado y desmarcado de provincias con un solo clic | `components/MapaEcuador.vue` |
| Botones de descarga según la familia que se está viendo | `components/TablaRegistros.vue`, `stores/datos.js` |
| Campo de contraseña con botón de ver | `components/CampoContrasena.vue` |

## 8. Pruebas ejecutadas y resultado real

| Comprobación | Resultado |
|---|---|
| `ruff check` / `ruff format --check` | limpio · 180 archivos |
| `mypy` | sin errores · 166 archivos |
| `pytest pruebas/unidad` | **568 pasan** |
| `pytest pruebas/integracion` (con `PRUEBAS_INTEGRACION=1`, contra Supabase real) | **54 pasan · 9 omitidas · 0 fallan** (8:31) |
| Las dos áreas tocadas al final, vueltas a comprobar contra la base real | **19 pasan · 1 omitida** (`test_cola_terminos.py` y `test_autenticacion_sesion.py`) |
| `alembic upgrade head` | `0010 (head)` aplicado |
| `/listo` | `postgres: ok`, `cache: ok` · 40 rutas |
| Panel en el navegador | Ínfimas cuantías **2.210** · Ofertas **53** · Mapa con «Ambas» **2.263** |
| Listado de palabras clave | **16,7 s → 3,0 s** al quitar el N+1 de los suscriptores |
| Filtro por familia contra la base | `todas 2263 · infimas 2210 · ofertas 53` |
| Exportación contra las **dos plantillas reales** subidas | cabecera detectada en la fila 4 (antes: ninguna) · 8 campos · cada dato bajo su título · 1.404 filas anteriores sustituidas · los tres títulos del informe intactos |
| Reparto por familia con la plantilla real | ínfimas → hoja `ÍNFIMAS` · ofertas → hoja `OFERTAS ` (cabecera en la fila 7), con `Provincia/Cantón` → `PICHINCHA/QUITO` y la columna propia `Presupuesto…` sin tocar |
| Plantilla que no crea ni borra pestañas | `hojas resultantes == ['ÍNFIMAS', 'OFERTAS ', 'PARTICIPACION']` idénticas a las subidas |

## 9. Evidencia de aceptación

```
ruff check .                     -> All checks passed!
ruff format --check .            -> 180 files already formatted
mypy                             -> Success: no issues found in 166 source files
pytest pruebas/unidad            -> 568 passed
pytest pruebas/integracion       -> 54 passed, 9 skipped, 0 failed
alembic current                  -> 0010 (head)
GET /listo                       -> {"listo": true, "dependencias": {"postgres": "ok", "cache": "ok"}}
```

Y la comprobación de la familia de contratación contra la base real, que es lo que sostiene las
pestañas: `todas 2263 · ínfimas 2210 · ofertas 53`.

Y la de la plantilla, ejecutada contra los dos archivos que hay subidos —no contra una plantilla de
prueba—, que es la única forma de que estos fallos se vean:

```
plantilla 23dc82a3…  ÍNFIMAS       cabecera en la fila 4, 8 campos reconocidos
                     OFERTAS       cabecera en la fila 7, 6 campos
                     PARTICIPACION cabecera en la fila 4, 5 campos
  exportar ínfimas -> hoja 'ÍNFIMAS'    fila 5: NIC-001 bajo «Código Necesidad…»,
                                        'PICHINCHA - QUITO' en «Provincia - Cantón»
  exportar ofertas -> hoja 'OFERTAS '   fila 8: SIE-001 bajo «Código»,
                                        'PICHINCHA/QUITO' en «Provincia/Cantón»
  hojas resultantes -> ['ÍNFIMAS', 'OFERTAS ', 'PARTICIPACION']  (ni una más, ni una menos)

plantilla c3c5cdf5…  Contrataciones  cabecera en la fila 1, 16 campos, 1.406 filas dentro
  exportar ínfimas -> fila 2: NIC-001 · fila 3: NIC-002 · fila 4 en adelante: vacío
```

## 10. Deuda técnica y pendientes

- **El rol de aplicación sigue sin quitarse `BYPASSRLS`** (F5). Es la razón por la que 9 pruebas de
  integración se omiten: comprueban que el aislamiento funciona contra un rol que no lo salta.
- **La exportación es síncrona**: `openpyxl` bloquea el proceso mientras escribe el archivo. El
  umbral para pasar a asíncrona (`export_async_umbral_filas`) existe pero no se ha subido.
- **La prueba de carga con k6 (900 paneles con flujo de eventos) sigue sin ejecutarse.** Los números
  de `docs/07-capacidad-y-concurrencia.md` son un modelo razonado, no una medición.
- **La contraseña de Redis compartida por chat no se ha rotado.**
- No se ha comprobado a mano, en el navegador, que la presencia pase a rojo sin recargar.
- **La zona de datos de la plantilla se sustituye entera en cada descarga**, así que una nota o un
  total escritos *dentro* de esa zona se pierden: el sitio para eso es encima de la fila de
  encabezados —que sí se respeta— o en otra hoja. Se eligió así porque las dos alternativas dejaban
  el archivo peor (una etiqueta huérfana o no vaciar nada en silencio); está razonado en
  `_vaciar_bajo_la_cabecera`. Lo que sí falta es decírselo al usuario en la propia pantalla de la
  plantilla, que hoy no lo explica.
- Las filas de la descarga anterior quedan **vacías pero presentes** en la hoja —se vacían celdas, no
  se borran filas, para no perder su formato—, así que el rango usado del archivo sigue siendo el
  viejo. Es cosmético, pero un archivo con 1.400 filas vacías al final se nota.
