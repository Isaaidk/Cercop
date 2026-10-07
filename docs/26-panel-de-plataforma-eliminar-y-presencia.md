# Panel de la plataforma — presencia, empresas y eliminación

> Cierre de la tanda de trabajo pedida el 2026-10-05: «el apartado de los workers y la vista de
> empresas y usuarios conectados debe ser solo para el superadministrador (isaacpuga661), y mi
> perfil tiene que poder eliminar una empresa con sus usuarios o un usuario concreto».

## 1. Objetivo

Dos cosas que van juntas porque son la misma: **quién manda sobre la plataforma**.

1. **Lo que ve el dueño del sistema y nadie más.** Las empresas, el trabajo de los workers y **quién
   está conectado** pasan a ser de un solo rol. La presencia dejó de ser un dato que cada empresa ve
   de su propia gente.
2. **Lo que puede hacer el dueño del sistema.** Hasta ahora podía suspender una empresa, que se
   deshace. Ahora puede **eliminarla** —con sus cuentas— o eliminar **una cuenta concreta**, que no
   se deshace.

La segunda obligó a decidir qué es «borrar» en este sistema, y la respuesta no es la obvia: ver § 4.

## 2. Alcance (incluido / excluido)

**Incluido**

- Regla de rol nueva en el dominio: `es_de_plataforma`, en `dominio/roles.py`.
- Presencia (`GET /v1/presencia` y `GET /v1/presencia/eventos`) reservada al superadministrador. El
  **latido sigue siendo de todos**: es la señal de vida de la propia sesión.
- Borrado de una empresa con sus cuentas, sus sesiones, sus accesos y su plantilla.
- Borrado de una cuenta concreta de cualquier empresa.
- Botones y confirmaciones en el panel de empresas, con la confirmación escrita a mano.
- 39 pruebas unitarias nuevas entre las tres piezas (presencia, borrados, contrato de rutas).

**Excluido, a propósito**

- **La pestaña «Usuarios» de una empresa** (CU-14: un administrador gestiona su propia plantilla) no
  se ha tocado. Lo pedido era «usuarios **conectados**» —quién está dentro ahora mismo—, que es otra
  cosa. Un administrador de empresa sigue creando, dando de baja y borrando **su** gente; lo que ya
  no ve es quién está en línea.
- **El histórico de contratación y la auditoría no se borran** con la empresa. Ver § 4.
- Nada de borrado suave («papelera») ni de restauración: lo que se borra, se borra. Un borrado
  reversible que nadie restaura es un borrado que ocupa disco y engaña.

## 3. Implementaciones realizadas

| Componente | Archivo / símbolo | Qué hace |
|---|---|---|
| Regla de rol | `dominio/roles.py` · `es_de_plataforma` | Normaliza el rol y responde si es el dueño del sistema. Vive junto al resto de capacidades porque ahora la necesitan dos sitios. |
| Presencia (caso de uso) | `aplicacion/casos_uso/presencia.py` · `exigir_ver_el_cuadro` | Niega con `SinPermiso`, no con una lista vacía. Pública para que el enrutador la llame antes de abrir el flujo. |
| Presencia (cuadro) | `cuadro_del_negocio` · `cuadro_serializado` | Comprueban el permiso **antes** de mirar el almacén. |
| Presencia (rutas) | `routers/presencia.py` | `consultar_presencia` y `eventos` llaman al guardián antes de responder, para que la negativa sea un 403 y no un 200 que se muere por dentro. |
| Borrado de empresa (puerto) | `aplicacion/puertos/negocios.py` · `RepositorioNegocios.eliminar` | Describe el contrato y lo que **no** toca. |
| Borrado de empresa (adaptador) | `salida/bd/negocios.py` · `RepositorioNegociosBd.eliminar` | `DELETE FROM negocio` dentro del contexto de negocio: atraviesa RLS por la puerta, y las claves ajenas se llevan el resto. |
| Borrado de empresa (caso de uso) | `casos_uso/administrar_negocios.py` · `eliminar_empresa`, `ResultadoDeBorrado` | Tres guardas, lectura de cuentas, auditoría **antes** del borrado y cierre de las sesiones vivas. |
| Borrado de cuenta (caso de uso) | `casos_uso/administrar_negocios.py` · `eliminar_cuenta_de_empresa` | Las mismas guardas más «no dejar una empresa sin administradores». |
| Rutas | `routers/plataforma.py` | `DELETE /v1/plataforma/empresas/{id}` y `DELETE …/empresas/{id}/usuarios/{id}`, ambos con `confirmacion` obligatoria. |
| API del panel | `frontend/src/api/endpoints.js` | `eliminarEmpresa` y `eliminarUsuarioDeEmpresa`. |
| Rol en el panel | `frontend/src/utils/roles.js`, `stores/sesion.js` | `esDePlataforma`, distinto de `esAdministrativo`. |
| Presencia en el panel | `composables/usePresencia.js`, `BarraSuperior.vue`, `VistaPanel.vue` | El canal no se abre para quien no es de la plataforma, y el indicador no se pinta. |
| Borrado en el panel | `components/PanelEmpresas.vue` | Botón por empresa y por cuenta, confirmación en línea y recuento real de lo borrado. |

## 4. Decisiones tomadas y justificación

### 4.1 La presencia pasa a ser del dueño del sistema, y el latido no

El cuadro dice **quién está trabajando ahora mismo**. No es un dato de contratación: es información
sobre personas y sobre la operación —cuánta gente entra, cuándo—, y saberla no ayuda a contratar
mejor. Un administrador de empresa que lo veía ya no lo ve.

El **latido sí sigue siendo de todos**, y no es una incoherencia: el latido no cuenta nada de nadie,
es la señal de vida de la propia sesión y es lo que la mantiene viva en el almacén de sesiones vivas.
Quitárselo a un cliente lo expulsaría a los pocos minutos de inactividad. Lo que se corta es el
derecho a **mirar el cuadro**, no el deber de decir «sigo aquí».

Se niega con un error y no con una lista vacía. «No hay nadie conectado» y «no puedes ver esto» son
respuestas distintas, y confundirlas dejaría a un administrador creyendo que su gente no trabaja.

### 4.2 La negativa se comprueba antes de abrir el flujo

El canal de eventos (`/v1/presencia/eventos`) es un `StreamingResponse`: cuando el generador empieza,
la respuesta 200 ya se ha enviado. Si el permiso se comprobara solo al componer el cuadro, el cliente
recibiría **200 con un flujo que se muere por dentro**, y el navegador no tendría forma de distinguir
eso de una conexión correcta que terminó. Por eso el enrutador llama al guardián antes. La
comprobación del caso de uso se queda igual, que es la que protege a los otros caminos.

### 4.3 Borrar una empresa no borra las cuentas una a una

`DELETE FROM negocio WHERE id = …` se lleva cuentas, sesiones, concesiones de vistas, conjuntos de
términos, consentimientos, exportaciones y la plantilla de Excel, **en la misma transacción**. No hay
un bucle de borrados por cuenta, y es deliberado: un bucle dejaría la empresa medio vacía si algo
fallara a mitad, y la operación más destructiva del sistema no puede quedar a medias. Las acciones
referenciales de las claves ajenas las ejecuta el dueño de la tabla, así que no pasan por las
políticas de fila y el aislamiento no estorba.

Lo que el caso de uso sí hace **antes** es **leer** las cuentas, por dos razones: para poder decir
cuántas eran y para cerrarles la marca del almacén de sesiones vivas. Esa marca no se va con la fila,
y sin este paso alguien recién expulsado podría seguir renovando su token unos minutos.

### 4.4 Lo que no se borra: el histórico y la auditoría

- **El histórico de contratación** (`registro`) es de la plataforma, no de la empresa. Borrar un
  cliente no puede restar datos a los demás: los datos del SERCOP son públicos y compartidos.
- **La auditoría sobrevive** a propósito, para poder decir quién borró qué y cuándo. Es lo único que
  queda de esa empresa.

### 4.5 La auditoría se escribe antes de borrar

Igual que al borrar una cuenta (§ `gestionar_usuarios.eliminar_cuenta`): el fallo que importa es el
borrado que sí ocurrió y cuya anotación no. Escribir después lo produce exactamente al revés. Hay una
prueba que compara el **orden** de los pasos, no solo su presencia.

### 4.6 Tres guardas, y ninguna es ceremonia

1. **Solo el dueño de la plataforma.** La petición se pide sobre una empresa ajena y con el rol de
   administrador de negocio, y aun así se niega.
2. **No se puede borrar la empresa propia.** Quien lo pide se quedaría fuera del sistema sin forma de
   volver a entrar. El mensaje apunta a «suspender», que sí se deshace.
3. **Hay que escribir el nombre de la empresa** (o el correo de la cuenta). Se destruye el registro de
   aceptación de los términos de esas personas, y eso no se recupera. La comparación ignora
   mayúsculas y espacios de sobra: es una traba contra el descuido, no un examen de mecanografía. La
   comprobación de verdad está en el servidor, que la repite.

Y una cuarta regla que se conserva del borrado de cuentas de empresa: **una empresa no puede quedarse
sin administradores**. Sin ninguno no podría volver a gestionar sus cuentas desde dentro, y no habría
forma de arreglarlo salvo entrando a mano en la base. Si lo que se quiere es retirar la empresa
entera, está el borrado de la empresa, que sí se lo lleva todo.

### 4.7 Los endpoints van como `DELETE`, no como `POST /borrar`

El nombre de la empresa viaja como parámetro de la dirección porque no hay cuerpo que enviar: lo que
se pide no es crear un recurso, es que algo deje de existir. Un `POST` con la palabra «borrar» dentro
sería un verbo escondido en un sustantivo, y este es el único sitio del sistema donde esa diferencia
se nota.

### 4.8 En el panel, la confirmación es en línea y no un diálogo

Lo que hay que leer para confirmar es **de qué empresa se trata**, y un diálogo tapa justo la ficha
que permite comprobarlo. Misma elección que en la gestión de cuentas.

## 5. Casos de uso y requisitos cubiertos

| ID | Descripción | Estado |
|---|---|---|
| CU-14 | Un administrador de empresa gestiona su propia plantilla | **Sin cambios** (ver § 2) |
| — | Solo el superadministrador ve quién está conectado | Cubierto |
| — | Solo el superadministrador ve el panel de empresas y el trabajo de los workers | **Ya estaba**; se comprueba y se documenta |
| — | El superadministrador elimina una empresa con sus cuentas | Cubierto |
| — | El superadministrador elimina una cuenta concreta | Cubierto |

## 6. Pruebas ejecutadas y resultado real

| Prueba | Comando | Resultado |
|---|---|---|
| Estilo y formato | `ruff check src pruebas` · `ruff format --check src pruebas` | Limpio (192 archivos ya formateados) |
| Tipos | `mypy` | `Success: no issues found in 220 source files` |
| Unidad | `pytest pruebas\unidad` | **835 passed** (línea base antes de esta tanda: 796) |
| Compilación del panel | `npx vite build --outDir $env:TEMP\contratacion-dist-verif --emptyOutDir` | 95 módulos, construido en 3,20 s |

Las 39 pruebas nuevas se reparten así:

- `test_presencia_casos_uso.py` — el cuadro se niega a un lector **y** a un administrador de empresa;
  el dueño de la plataforma lo ve entero; el rechazo ocurre antes de leer el almacén; y la separación
  de claves por alcance se prueba donde vive (en `clave_cuadro`), porque hoy no hay ningún alcance
  distinto de `todos` al que llegar a través del caso de uso.
- `test_presencia_flujo.py` — el flujo en vivo es del dueño de la plataforma, y un administrador de
  empresa recibe un error **al abrir**, no un 200 moribundo.
- `test_administrar_negocios.py` — 25 pruebas nuevas: las tres guardas de cada borrado, el orden de
  la auditoría, que las cuentas se van con la empresa y no una a una, y que no se cierran sesiones de
  otra empresa.
- `test_plataforma_rutas.py` — las siete rutas de la plataforma existen y exigen autenticación;
  `confirmacion` está en el contrato y es obligatoria; y la negativa por falta de credenciales llega
  antes que la validación.

## 7. Evidencia de aceptación

```
$ .\.venv\Scripts\python.exe -m pytest pruebas\unidad --tb=line -rf
835 passed, 2 warnings in 35.82s

$ .\.venv\Scripts\python.exe -m pytest pruebas\unidad\test_plataforma_rutas.py -q
12 passed

$ npx vite build --outDir "$env:TEMP\contratacion-dist-verif" --emptyOutDir
✓ 95 modules transformed.
✓ built in 3.20s
```

## 8. Deuda técnica y pendientes

- **La prueba de integración del borrado real no existe.** El borrado contra Postgres —que las
  claves ajenas se lleven todo y que no queden huérfanos— se comprobó a mano con el script de
  empresas temporales (`scripts/preparar_carga.py --borrar`, 1 y 198 empresas), pero no hay ninguna
  prueba automática que lo fije. Es lo primero que hay que añadir si se toca el esquema.
- **Los `scripts/verificar_*.py` no cubren esto.** Ninguno de los verificadores manuales llama a los
  endpoints de la plataforma; el contrato queda fijado en `test_plataforma_rutas.py`, que es lo que
  se ejecuta siempre.
- **Cero acciones de interfaz para el usuario final en este documento.** El botón y la confirmación
  se han compilado y revisado, pero el recorrido completo (pulsar, escribir el nombre, ver el
  recuento) no se ha grabado contra datos reales: es lo que conviene hacer con el cliente delante,
  sobre una empresa de prueba, antes de dar la función por cerrada.

## 9. Riesgos abiertos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Un borrado por descuido | Confirmación escrita, comparada en el servidor; auditoría antes del borrado; el botón de eliminar está apagado hasta que el texto coincide. |
| El dueño de la plataforma se borra a sí mismo y deja el sistema sin puerta | La empresa propia no se puede borrar; la cuenta con la que se actúa tampoco. El mensaje apunta a suspender. |
| Una empresa se queda sin administradores | Guarda explícita, con contador consultado antes de tocar nada. |
| Alguien baja el guardián a `esAdministrativo` en el futuro | Hay una prueba por cada lado: un lector **y** un administrador de empresa reciben `SinPermiso`, y el administrador es el caso que distingue las dos reglas. |
| El navegador recibe un 403 y lo pinta como fallo del panel | El canal no se abre si no se puede tener, y el indicador no se pinta. La negativa del servidor se añadió igualmente, como segunda barrera. |

## 10. Aprobación

| Rol | Nombre | Fecha | Veredicto |
|---|---|---|---|
| Ingeniero QA | — | 2026-10-05 | Pruebas en verde; pendiente el recorrido manual del borrado sobre datos reales (§ 8) |
| Revisor de Código | — | 2026-10-05 | Réplica de la regla de rol en el frontend documentada como espejo, con el servidor como única barrera efectiva |
