# Fase 3 — Sesiones: caducidad, rotación y varias pestañas

> Documento de fase según la plantilla de `documentacion.md` § 9.2.
>
> **Nota sobre el nombre:** esta es la **tercera fase del plan de trabajo** acordado (la primera fue
> el rendimiento de las consultas, la segunda la clasificación y las palabras clave). No tiene nada
> que ver con `docs/03-fase-3.md`, que es la fase 3 del proyecto original —Redis-first: caché,
> filtros y búsqueda multi-palabra—.

**Fecha:** 2026-10-06 · **Estado:** implementado y verificado contra la API y la base reales; falta la
comprobación de dos pestañas en un navegador, que necesita una sesión con la que entrar.

## 1. Objetivo

**Que una sesión dure lo que dura la jornada y aguante varias pestañas abiertas.** Los dos síntomas
que se estaban viendo en el panel no parecían el mismo problema y lo eran:

- «De vez en cuando me saca y me habla de tokens.» Aparecía en la tabla de sesiones con motivo
  `reuso_detectado`: el servidor cerraba **todas** las sesiones de la cuenta por haber visto dos
  copias del token de renovación en circulación.
- «Llevo un rato con el panel abierto y me dice que no tengo permiso.» El mensaje no tenía nada que
  ver con permisos: el token de acceso caducaba a los quince minutos y el panel no renovaba.

Hay tres causas distintas detrás de los dos síntomas, y las tres se arreglan aquí.

## 2. Alcance

**Incluido**

- Un error de dominio propio para el token caducado, con su código y su **401**, para que el cliente
  distinga «renueva y sigue» de «vuelve a entrar».
- Renovación **anticipada**: el panel pide el par nuevo un minuto antes de que caduque el de acceso,
  en lugar de esperar a que una petición falle.
- Cinco minutos de ventana de gracia en la rotación (eran treinta segundos), con el motivo escrito.
- Un canal entre las pestañas del mismo navegador para que la rotación se comparta: la que renueva
  publica el par nuevo y las demás lo adoptan. Por el mismo canal se avisa del cierre de sesión.
- Descarte de respuestas que llegan tarde: una renovación que termina **después** de que la sesión se
  cerró no puede devolverla a la vida.

**Excluido (deliberadamente)**

- Compartir el token de renovación por `localStorage`. Sería lo más simple —una sola copia para todas
  las pestañas— y está descartado a propósito: `localStorage` sobrevive al cierre del navegador
  durante meses, y con él un token robado sigue sirviendo al día siguiente. El canal consigue lo mismo
  sin esa persistencia.
- Reconectar el canal de eventos (SSE) cuando la sesión se cae. Con la renovación anticipada el token
  del canal está fresco mientras la pestaña vive; la reconexión es otra cosa y queda como pendiente.
- Tocar el plazo de inactividad (`sesion_inactividad_min`, ocho horas) o el tope de sesiones por
  usuario (dos). No están en el problema.

## 3. Implementaciones realizadas

| Qué | Dónde |
|---|---|
| El error `TokenCaducado` y el porqué de que sea un tipo propio | `dominio/errores.py` |
| La caducidad se distingue **antes** que el resto de rechazos de firma | `salida/seguridad/tokens.py` |
| La traducción a 401, con el razonamiento al lado del 403 | `infraestructura/app.py` (`CODIGOS_POR_ERROR`) |
| La ventana de gracia: cinco minutos y por qué no bastaban treinta segundos | `infraestructura/config/ajustes.py`, `.env.example` |
| Renovación anticipada, canal entre pestañas y descarte de respuestas tardías | `frontend/src/api/cliente.js` |
| Programar la renovación al entrar y avisar del cierre | `frontend/src/stores/sesion.js` |
| Tres pruebas del contrato HTTP: 401 y su código, 403 en el manipulado, mismo mensaje | `pruebas/unidad/test_token_caducado_http.py` |
| Una prueba de que la caducidad no es un `SinPermiso` | `pruebas/unidad/test_seguridad_adaptadores.py` |
| Tres pruebas del valor por defecto y de los límites de la ventana | `pruebas/unidad/test_ajustes.py` |
| Un apartado 11 en el guion de plataforma: caducidad visible, rotación y ventana | `scripts/verificar_plataforma.py` |

## 4. Decisiones tomadas y justificación

### 4.1 Un token caducado no es «sin permiso»

El verificador rechazaba **igual** un token manipulado y uno caducado: mismo mensaje y mismo tipo,
así que el transporte devolvía **403** en los dos casos. Y el cliente solo intenta renovar ante un
**401**, porque un 403 significa «esto no se arregla volviendo a entrar». Resultado: la renovación
silenciosa **no llegaba a ejecutarse nunca**. Con el token de acceso caducado —quince minutos— cada
petición devolvía «no tienes permiso para esto», que es un mensaje que el usuario no puede entender ni
usar, y que además le manda a pedirle permisos al administrador por haber dejado la pestaña abierta.

Ahora la caducidad se captura **antes** que `InvalidTokenError` —es su clase madre, así que al revés
nunca se distinguiría— y sale un `TokenCaducado` con código `token_caducado` y respuesta **401**.

Lo que **no** cambia es el texto que lee la persona: sigue siendo el mismo («Tu sesión ha caducado.
Vuelve a entrar.»). No es un descuido, y hay una prueba que lo fija: contar en pantalla qué es un
token no ayuda a nadie —al que intenta forzar el sistema tampoco, ya sabe lo que hacía— y sí confunde
a quien no ha hecho nada. La diferencia va donde decide el programa: en el tipo y en el código.

Comprobado contra la API en marcha:

| Petición | Antes | Ahora |
|---|---|---|
| Token de acceso caducado | 403 `sin_permiso` | **401 `token_caducado`** |
| Token manipulado | 403 `sin_permiso` | 403 `sin_permiso` |
| Token de renovación caducado | 403 `sin_permiso` | **401 `token_caducado`** |
| Sin cabecera | 401 | 401 |

### 4.2 Renovar **antes** de que caduque

Esperar al 401 funciona —y se sigue haciendo, porque un temporizador de navegador no es una alarma—,
pero cuesta: la petición que llega justo después de la caducidad viaja con un token muerto, espera un
rechazo, renueva y repite. La respuesta del inicio de sesión ya traía `acceso_expira_en`, así que el
panel programa la renovación **un minuto antes**: sobran catorce de los quince minutos para trabajar y
la renovación ocurre sin nadie mirando.

Dos detalles que importan:

- **La hora la pone el servidor.** El reloj del navegador puede ir adelantado o atrasado, y no es de
  fiar para decidir cuándo caduca algo que emitió otro.
- **Hay un suelo de quince segundos** entre dos renovaciones programadas. Si el reloj del servidor
  diera una caducidad ya pasada, sin ese suelo la renovación se pediría una y otra vez sin pausa.

Y lo que **no** garantiza: una pestaña en segundo plano se estrangula y un portátil suspendido no
ejecuta el temporizador hasta que despierta. Cuando eso pasa, el camino del 401 sigue ahí y es el que
termina de arreglarlo.

### 4.3 Cinco minutos de gracia en vez de treinta segundos

La ventana de gracia existe por un falso positivo que se da solo: el servidor rota el token y la
respuesta se pierde —se corta la conexión, se suspende el portátil, un proxy cierra—, así que el
navegador reintenta con el viejo. Sin ventana, eso se lee como «hay dos copias en circulación» y el
servidor cierra **todas** las sesiones de la cuenta. Ya había pasado tres veces en un día.

Estaba en treinta segundos, y el reintento legítimo no siempre tarda segundos: un portátil que se
suspende o un ascensor sin cobertura dejan la respuesta perdida **minutos**. Ahora son cinco minutos,
que siguen siendo un intervalo en el que un reintento y un robo son indistinguibles.

Lo que **no** arregla, y conviene no confundirlo: una pestaña que lleva horas con un token viejo y que
además nunca recibió el aviso de rotación. Eso lo resuelve el canal del § 4.4; la gracia solo cubre el
hueco de minutos.

### 4.4 Las pestañas se cuentan lo que pasa

El token de renovación **rota en cada uso**, y cada pestaña guarda su propia copia (en
`sessionStorage`, por la razón del § 2). Con dos pestañas abiertas eso era una trampa: la pestaña A
renueva, la copia de B queda atrás, y cuando B renueva con ella el servidor ve dos copias en
circulación y cierra las sesiones de la cuenta. El panel funcionaba bien con una pestaña y se
expulsaba solo con dos.

Ahora, cuando una pestaña renueva, **publica el par nuevo** por un `BroadcastChannel` y las demás lo
adoptan en el acto. La petición va con el token que hay en el almacén, así que la siguiente renovación
de cualquier pestaña parte de la copia buena.

Por el mismo canal viaja el **cierre de sesión**: cerrar sesión revoca la sesión —que es la misma para
todas las pestañas del navegador, porque comparten el token— así que las otras dejan de fingir que
siguen dentro. Sin el aviso seguirían enseñando el panel y fallando petición tras petición hasta que
caducara su token de acceso, que son hasta quince minutos de pantallas rotas por haber pulsado
«Salir». El aviso que se enseña lo dice: «Se cerró la sesión en otra pestaña.»

Dos decisiones más, en la misma línea:

- **Las dos piezas se necesitan.** Si dos pestañas renuevan en el mismo instante, las dos rotaciones
  parten de la misma generación anterior: la segunda la acepta la ventana de gracia del § 4.3 y su
  publicación gana. El canal resuelve el caso de minutos y la gracia el de milisegundos.
- **Una respuesta que llega tarde se descarta.** Cada cierre de sesión abre una generación nueva, y
  una renovación que termina después de él no guarda el par que acaba de recibir: si lo guardara,
  devolvería a la vida la sesión que el usuario acababa de cerrar y las peticiones siguientes
  llevarían un token que el servidor ya no reconoce.

### 4.5 Dónde vive el canal, y qué pasa donde no hay

El canal se abre con `BroadcastChannel`, disponible en todos los navegadores que el panel soporta. La
construcción va dentro de un `try` y el resultado se comprueba antes de usarlo: en un navegador que no
lo tenga —o que lo bloquee— el panel sigue funcionando con el comportamiento de antes, apoyado en la
ventana de gracia. Se pierde la coordinación entre pestañas, que es una mejora, no un requisito.

## 5. Casos de uso y requisitos cubiertos

- **Trabajar una jornada con el panel abierto**: el token de acceso se renueva solo cada quince
  minutos, sin avisos y sin que la persona note nada.
- **Dejar el portátil suspendido y volver**: si el temporizador llegó tarde, la primera petición
  recibe un 401 `token_caducado`, el cliente renueva y repite la petición. La persona ve el resultado.
- **Tener dos pestañas abiertas**: la segunda adopta la rotación de la primera y no se cierra ninguna
  sesión.
- **Cerrar sesión en una pestaña**: las demás vuelven a la pantalla de acceso diciendo por qué.
- **Un token manipulado**: sigue siendo un 403, no se intenta renovar y no se entra en un bucle.

## 6. Verificación

### 6.1 Contra la API en marcha

Sonda directa sobre `/v1/auth/sesion` y `/v1/auth/sesion/renovacion`, con tokens emitidos con el mismo
secreto de la aplicación:

```
caducado               -> 401 token_caducado  Tu sesión ha caducado. Vuelve a entrar.
manipulado             -> 403 sin_permiso     Tu sesión ha caducado. Vuelve a entrar.
sin cabecera           -> 401 -               Falta la cabecera `Authorization` con un token de acceso válido.
renovación caducada    -> 401 token_caducado  Tu sesión ha caducado. Vuelve a entrar.
WWW-Authenticate del 401: 'Bearer'
```

### 6.2 El guion de plataforma, con su apartado 11

`scripts/verificar_plataforma.py` crea dos empresas temporales, comprueba lo que hay que comprobar y
las borra. El apartado 11 trabaja sobre la sesión real:

```
OK  el inicio de sesión dice cuándo caduca cada token
  el acceso caduca en 2026-10-06T21:53:29 y la renovación en 2026-11-05T21:38:29
OK  POST /v1/auth/sesion/renovacion -> 200
OK  el token de renovación rota: el nuevo no es el mismo que el usado
OK  el token de acceso recién emitido sirve para leer
  esperando 35 s para volver a presentar el token anterior...
OK  el token de la generación anterior sigue valiendo a los 35 s -> 200
OK  la otra sesión de la cuenta sigue viva: dentro de la ventana no se cierra nada
```

La espera de 35 segundos es el corazón de la comprobación: **es más larga que la ventana anterior de
treinta segundos**, así que con el valor viejo presentar el token de la generación anterior habría
cerrado todas las sesiones de la cuenta. La última línea comprueba el efecto, no la causa: la otra
sesión de la misma cuenta —la del apartado 2— tiene que seguir viva.

### 6.3 Comprobaciones automáticas

- `ruff check` → `All checks passed` · `ruff format --check` → 236 archivos
- `mypy` → `Success: no issues found in 211 source files`
- `pytest pruebas/unidad` → **766 pasan** (7 nuevas)
- `vite build` → 88 módulos

Las siete pruebas nuevas cubren la costura que fallaba: que la caducidad tenga **tipo propio** y que
el transporte devuelva 401 con su código (tres, contra la aplicación montada), que no sea un
`SinPermiso` (una) y que la ventana de gracia valga cinco minutos por defecto, se pueda desactivar y
no admita una hora (tres).

### 6.4 Lo que no se ha podido comprobar aquí

- **Dos pestañas en un navegador de verdad.** El canal, la adopción del par nuevo y el aviso de
  cierre no tienen prueba automática: el panel no tiene marco de pruebas —se verifica con guiones y a
  mano, como el resto— y entrar necesita credenciales que no están en el repositorio. Lo que sí está
  comprobado es cada mitad por su lado: la rotación y la ventana contra la API real (§ 6.2), y que el
  panel arranca con el canal construido (§ 6.5).
- **Una jornada entera con el panel abierto.** La renovación anticipada se ve funcionar en las
  pruebas y en el arranque del panel; verla ejecutarse sola cada quince minutos necesita dejar el
  panel abierto.

### 6.5 El panel arranca con el código nuevo

`vite build` compila 88 módulos y el panel responde en `http://localhost:5174` mostrando la pantalla
de acceso. Importa porque el canal se construye **al cargar el módulo** del cliente HTTP: si
`BroadcastChannel` fallara sin protección, el panel no llegaría a dibujarse.

## 7. Evidencia de aceptación

- El 401 con código `token_caducado` y el 403 con `sin_permiso` conviven, con el mismo mensaje y
  distinto código (§ 6.1).
- La respuesta del inicio de sesión trae `acceso_expira_en` y `renovacion_expira_en`.
- El token de la generación anterior sigue valiendo a los 35 segundos, y la otra sesión de la cuenta
  sigue viva (§ 6.2).
- 766 pruebas unitarias, `ruff` y `mypy` limpios.

## 8. Deuda técnica y pendientes

1. **El canal de eventos no se reconecta** si la sesión se cae mientras está abierto: el flujo se
   queda en error y la presencia deja de actualizarse hasta recargar. Con la renovación anticipada el
   caso es raro, y por eso se deja aquí escrito en lugar de arreglarlo a medias.
2. **Una pestaña que no reciba el canal** —navegador sin `BroadcastChannel`, o pestaña abierta antes
   de un despliegue— depende de la ventana de gracia: si renueva después de cinco minutos con una
   copia vieja, el servidor cierra las sesiones de la cuenta. Es el comportamiento de antes y solo
   aplica a esos casos.
3. **La renovación anticipada no está probada por el navegador** (§ 6.4).
4. Las pruebas de carga con k6 siguen pendientes; el panel abre una petición de renovación cada
   quince minutos por sesión, que es un coste despreciable pero conviene tenerlo en la cuenta.

## 9. Riesgos abiertos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Un 401 podría interpretarlo el cliente como «sesión perdida» y sacar al usuario | El 401 de caducidad y el de sesión revocada se distinguen por código: `token_caducado` renueva, `sesion_revocada` no lo intenta y conserva el motivo que mandó el servidor |
| Un token manipulado tratado como caducado entraría en un bucle de renovación | Es un `SinPermiso` (403) y no se renueva; hay prueba del contrato HTTP |
| El temporizador del navegador no se ejecuta (pestaña dormida) | El camino del 401 sigue siendo el respaldo, y es el que se probó antes |
| Una respuesta de renovación tardía resucita una sesión cerrada | Cada cierre abre una generación y la respuesta se descarta si cambió |
| Algún día alguien «mejora» el mensaje separando los textos | Una prueba fija que el texto es el mismo para caducado y manipulado, con el motivo escrito al lado |

## 10. Aprobación

| Campo | Valor |
|---|---|
| Estado | **Completada** — 2026-10-06 |
| Migraciones | ninguna (es una fase de contrato, configuración y cliente) |
| Comprobaciones | ruff, ruff format, mypy, 766 pruebas unitarias, sonda contra la API viva y `verificar_plataforma.py` § 11 |
| Pendiente del usuario | abrir el panel en **dos pestañas** y comprobar que ninguna se cierra sola (§ 6.4) |
