# Fase 4d — Vigilancia del listado, recuperación de la ingesta y arreglos de operación

**Fecha:** 2026-10-01 · **Estado:** implementado y verificado; aprobación de negocio pendiente en dos
puntos (marcados al final).

Esta fase no añade producto: **devuelve la confianza en lo que ya había**. Empezó levantando el
sistema para verlo funcionar y encontró tres cosas que llevaban tiempo mal y ninguna se anunciaba —
la ingesta caída sin síntoma, una funcionalidad escrita a medias que las pruebas ya exigían, y un
filtro que se guardaba pero no se aplicaba—.

---

## 1. La ingesta estaba caída y parecía sana

### Lo que se observó

Al levantar el sistema con `.\levantar.ps1`, el worker arrancaba, registraba un ciclo cada quince
minutos, el panel respondía y la tabla de sincronizaciones crecía. Todo parecía correcto salvo los
números:

```
NCO: error · 0 nuevos, 0 actualizados, 0 iguales, 0 sin mapear (1 pet.)
AttributeError: 'ResultadoExtraccion' object has no attribute 'terminos_completos'
```

### La causa

Cinco llamadas del caso de uso a código que no existía: el lado que llama de un refactor estaba
escrito y el repositorio no. La primera tapaba las otras cuatro, porque el `except Exception` del
ciclo las convierte en «fallo inesperado» y cierra la sincronización como `error`.

| Llamada | Qué faltaba |
|---|---|
| `extraccion.terminos_completos` | El campo no estaba declarado en `ResultadoExtraccion`; solo lo escribía OCDS, así que la lectura reventaba en cualquier otra fuente |
| `repositorio.guardar_registros` | Escritura por lotes: solo existía la versión de una fila |
| `repositorio.refrescar_volatiles` | Refresco del enlace de la ficha, que la fuente regenera en cada listado |
| `repositorio.agregar_historial_en_lote` | Histórico por lotes |
| `repositorio.marcar_fuera_de_listado` | Vigencia: cerrar lo que deja de aparecer |

### Lo que se hizo

- `ResultadoExtraccion` declara `terminos_completos: tuple[str, ...] = ()`. Una fuente que no busca
  por término devuelve la tupla vacía, que es la verdad y no un olvido.
- Los cuatro métodos por lotes, en `adaptadores/salida/bd/ingesta.py`, a **una sentencia por tanda**,
  troceada en `FILAS_POR_LOTE = 500` por el tope de 65.535 parámetros de PostgreSQL. El refresco de
  volátiles va con `datos || volatiles`, porque los volátiles son campos canónicos **dentro** de
  `datos` y enumerarlos en el SQL sería tener dos listas de campos que mantener en sincronía.
- `pruebas/unidad/test_fuente_nco.py`: seis pruebas nuevas. La de OCDS que ya existía solo probaba la
  fuente que sí escribía el campo, que es justo lo que dejó pasar el fallo.

### Evidencia

```
NCO: ok · 143 nuevos, 0 actualizados, 1562 iguales, 0 sin mapear (1 pet.)
```

1.705 filas escritas en **6 segundos** (10:02:18 → 10:02:24) y ninguna excepción en el registro. Los
143 «nuevos» son necesidades publicadas mientras la ingesta estaba caída: con la fuente que solo
publica lo vigente, se habrían perdido en cuanto salieran del listado.

---

## 2. Vigilancia del listado: dos cadencias en el worker

### Por qué

La fuente no publica histórico. Una necesidad que entra y sale entre dos ciclos completos no se
puede recuperar después, y el hueco de un cuarto de hora se paga en datos que no vuelven: con el
worker parado 49 horas se perdieron 19 necesidades del Excel del cliente, 14 de ellas con el plazo de
proformas vencido dentro del hueco.

### Lo que se hizo

`worker.bucle()` ya no tiene una sola cadencia:

| Vuelta | Cada | Qué hace | Qué **no** hace |
|---|---|---|---|
| Corta (vigilancia) | `intervalo_vigilancia_seg` = **150 s** | Solo el listado de NCO | Cola de términos, fichas de CPC, invalidación de caché, precalentado |
| Larga (ciclo completo) | `intervalo_ingesta_min` = **15 min** | OCDS por términos, fichas de CPC, precalentado | — |

Tres decisiones que se pueden romper sin que nada falle a la vista, y por eso están probadas:

1. **La vuelta corta no consulta la cola de términos** (`incluir_ocds=False`). Consultarla cada dos
   minutos y medio sería leer y escribir la base para decidir algo que nadie va a usar.
2. **La vuelta corta no invalida la caché.** Subir la generación a esa cadencia dejaría inservible
   todo lo cacheado cada 150 s, y el catálogo de desplegables —que recorre el histórico entero— se
   pagaría detrás de cada vuelta.
3. **La hora del ciclo completo se da por servida antes de intentarlo.** Si solo avanzara al salir
   bien, un ciclo que falla se reintentaría en la vuelta siguiente —con las búsquedas y las fichas
   dentro, que es lo que la fuente castiga con 429— y la vigilancia no llegaría a correr nunca.

Cuando las dos horas coinciden manda el ciclo completo: se trae el listado de todos modos, así que la
vuelta corta no tendría nada que hacer.

### Verificación

`pruebas/unidad/test_vigilancia_listado.py` (7 pruebas, con reloj falso) estaba escrita desde antes y
es la especificación: dos vueltas cortas cada cinco de vigilancia, ciclo completo a los 900 s, y una
vuelta que falla devolviendo la vez. **Las 7 pasan.**

---

## 3. La vigencia: cerrar lo que se va y **reabrir lo que vuelve**

`DefinicionFuente.listado_completo` nunca se ponía a `True` para NCO, así que
`marcar_fuera_de_listado` no se llamaba nunca y `cerrados` era siempre cero: la única señal de que
una necesidad se cerró no se estaba grabando, y el histórico entero parecía abierto para siempre.

Al activarlo apareció la mitad que faltaba. Reabrir **no** puede colgar de la escritura del registro:
si la necesidad vuelve con el mismo contenido, la clasificación la da por «igual» y no se escribe,
así que el `upsert` no llega a tocarla. Por eso la reconciliación con el listado hace las dos
direcciones en una sola sentencia:

```sql
UPDATE registro
   SET es_vigente = (clave_natural = ANY(:claves))
 WHERE fuente_id = :fuente
   AND es_vigente IS DISTINCT FROM (clave_natural = ANY(:claves))
```

`IS DISTINCT FROM` deja intactas las ~1.700 filas que siguen iguales —que es la mayoría en cada
vuelta— y el `RETURNING` permite contar solo las que se cerraron, que es el dato de negocio: las
reabiertas no son novedad, son una corrección.

Queda una prueba de integración nueva (`test_una_necesidad_que_reaparece_vuelve_a_estar_vigente`) que
comprueba el ciclo completo —aparece, se cierra, vuelve— y afirma que el ciclo la sigue contando como
«igual», que es lo que hace que el `upsert` no pueda encargarse de reabrirla.

---

## 4. El filtro de CPC se guardaba pero no se aplicaba

### El síntoma, tal y como lo describió quien lo usa

> «Los términos se guardan, pero el filtro no cambia lo que veo en la tabla.»

### La causa

`estado` es el borrador y `aplicados` es lo único que consulta la API. La lista de CPC **es** el
filtro, no un catálogo donde marcar y pulsar «Aplicar», y `cargarCpc()` la aplicaba al abrir el panel
—pero `agregarCpc`, `agregarVariasCpc`, `quitarCpc` y `limpiarCpc` la dejaban **solo en el
borrador**—. El chip aparecía en pantalla, la tabla seguía igual, y el registro de la API lo confirma:
después de `POST /v1/cpc/lote` no hubo **ni una** búsqueda más.

Los propios avisos lo confesaban: «Pulsa «Aplicar» para buscarlo».

### Lo que se hizo

`aplicarClavesCpc()` copia la lista a `aplicados` y vuelve a la página uno, y las cuatro mutaciones la
llaman. **Las palabras clave no se tocan**: ahí el borrador sí es lo correcto, porque marcar una
palabra no es una intención completa.

### La trampa del modo «Todas», medida

Con la lista real de 31 términos:

| Consulta | Filas |
|---|---|
| Ínfimas, sin CPC | 3.729 |
| Ínfimas + CPC, modo «cualquiera» | **294** |
| Ínfimas + CPC, modo «todas» | **0** |

El modo «todas» exige que el CPC de una misma necesidad contenga **todos** los términos, y estas son
clasificaciones alternativas: ninguna coincide con otra. El gestor avisa de esto **antes** de pulsar,
sin bloquear el botón —quien tenga un solo término quiere ese modo—.

### Herramienta que queda

`backend/scripts/verificar_cpc_lista.py` imprime el total con y sin filtro y cuánto aporta **cada
término**. De los 31 de la lista real, **nueve no encuentran nada** (`atl`, `btl`, `cinemometro`,
`concierto`, `festival`, `foto radar`, `historia`, `pauta`, `trasito`): no es un fallo del filtro sino
de la lista, porque `atl` y `btl` son términos de publicidad que no existen en la nomenclatura del
CPC. Eso hay que decidirlo con el cliente, no arreglarlo en el código.

---

## 5. El panel se actualiza solo cuando la ingesta termina

### El hueco

Hasta esta fase, lo único que refrescaba la tabla era **tocar un filtro**: el canal de eventos en vivo
solo transporta presencia, y no había ningún temporizador de datos. La ingesta podía cerrar dos ciclos
—con las contrataciones guardadas y su CPC leído— y la pantalla seguía enseñando lo de antes hasta que
alguien recargaba la página a mano.

Había, además, una mitad que se escapaba incluso con caché bien invalidada: **el CPC se escribe
*después* de que cada fuente haya invalidado lo suyo**, así que las páginas cacheadas seguían saliendo
sin columna CPC hasta caducar por tiempo. El síntoma es el peor de todos: la necesidad está, su
clasificación no, y parece que la ficha no se leyó.

### Lo que se hizo

**En el worker:** `_leer_fichas` sube la generación cuando ha escrito ítems (y solo entonces: marcar
una ficha como «leída y sin detalle» no cambia nada de lo que se puede buscar, y subirla invalidaría
todo el caché para no enseñar nada distinto).

**En el API:** `GET /v1/ingestas/version` devuelve un solo número —la generación— leyendo **una clave
del caché**, sin tocar la base de datos. Va declarado **antes** de `/{codigo}` a propósito: FastAPI
resuelve las rutas en orden de declaración, y con la línea más abajo `version` entraría por `/{codigo}`
y la respuesta sería un 404 diciendo que la fuente «VERSION» no está registrada. Admite un memo de dos
segundos para que mil paneles preguntando a la vez no sean mil lecturas.

**En el panel:** cada minuto —y al volver a una pestaña que estaba de fondo— se pregunta por esa
versión. Si cambió, se recarga la tabla con los filtros **aplicados**, así que lo que alguien esté
escribiendo en el borrador no se pierde y la página en la que está no se mueve.

### Las dos decisiones que importan

1. **Se pregunta por la versión, no por los datos.** Recargar la tabla cada minuto sería lo fácil y lo
   caro: con cientos de paneles, multiplicar por sesenta las consultas que ya cuestan 120 ms cada una.
   Preguntar por un contador del caché cuesta una lectura y no toca la base.
2. **La vuelta corta sigue sin invalidar la caché**, y eso no cambia. Subir la generación cada 150 s
   dejaría inservible todo lo cacheado a esa cadencia —el catálogo de desplegables recorre el
   histórico entero—, que es justo el motivo por el que la vigilancia existe aparte. La consecuencia
   hay que decirla en voz alta: lo que entra por la vuelta corta aparece en pantalla con el ciclo
   completo, no a los dos minutos y medio.

### Verificación

El contador se lee y se mueve: `scripts/estado_version.py` imprimió `21` en los tres contadores y,
observando 90 s con un ciclo en marcha, pasó a `23`. La ruta está registrada como propia
(`/v1/ingestas/version` aparece en el esquema **antes** de `/v1/ingestas/{codigo}`) y sin sesión
responde 401, no 404. Tres pruebas de unidad nuevas fijan que escribir CPC sube la generación y que no
la suben ni una ficha sin ítems ni una tanda que falla.

**Lo que no se ha podido verificar:** el refresco visto desde un navegador. Hace falta una sesión
abierta en el panel para observar que la tabla se recarga sola, y en esta sesión no se compartió
ninguna pestaña. La mitad del servidor está verificada de punta a punta; la del cliente, compilada y
diseñada, pero no observada.

## 6. Arreglo del mensaje de error del cliente

`interpretarError` miraba `detail` como texto antes de comprobar si era una lista. Como un arreglo
siempre es «verdadero», un 422 de FastAPI se colaba por ahí y `new Error([{...}])` acababa pintando
**«[object Object]»** en pantalla, escondiendo el dato que hacía falta para corregir la petición.
Ahora la lista se comprueba primero y se unen sus `msg`.

---

## 7. Revisores: dos agentes nuevos

Se añaden dos agentes al proyecto, con la misma forma que los que ya había (`.github/agents/`):

- **Revisor de Ingesta** — su tarea es responder, con evidencia, si los workers trabajan **y si están
  insertando datos**. Existe porque el fallo más caro del proyecto no se parecía a una caída: proceso
  vivo, ciclos registrados y cero filas. Codifica las comprobaciones mínimas (que el número de filas
  crezca, que las dos cadencias corran, que `0 iguales` con listado sea imposible), las trampas
  (contar filas sin filtrar por `fuente_id`, confundir «0 ítems» con «ficha no leída»), y el aviso de
  que las pruebas de integración **se omiten en silencio** sin `PRUEBAS_INTEGRACION=1`.
- **Revisor de Despliegue** — audita el despliegue y la capacidad: coteja `deploy/docker-compose.yml`,
  el `Caddyfile`, los `Dockerfile`, `.env.example` y las copias contra
  `docs/07-capacidad-y-concurrencia.md`, rehace la aritmética de conexiones y descriptores con los
  valores reales, y separa lo medido de lo estimado. Su obligación principal es decir en voz alta que
  **la prueba de carga sigue pendiente**.

---

## 8. Despliegue y capacidad: qué se verificó

Cotejo del despliegue contra el documento de capacidad, sin cambios de configuración necesarios:

| Comprobación | Resultado |
|---|---|
| `ulimits: nofile` en `api` y `proxy` | Puesto (65.536), con el porqué escrito al lado |
| Conexiones por proceso | `bd_pool_size` 10 + `bd_max_overflow` 10 = **20** |
| Procesos contra `max_connections=200` | `--workers 4` + worker = 5 procesos = **100** conexiones. El techo son 10 procesos |
| Migraciones | Servicio de una sola ejecución del que dependen `api` y `worker` con `service_completed_successfully` |
| Volúmenes | Base, AOF de Redis (las sesiones viven ahí), plantillas y datos de Caddy |
| `/salud` y `/listo` | 200; `/listo` con `postgres: ok` y `cache: ok` |

**Lo que sigue pendiente y es lo que convierte la estimación en un hecho:** la prueba de carga con k6
y 900 paneles, con el flujo de eventos abierto. Hasta que se haga, las cifras de
`docs/07-capacidad-y-concurrencia.md` son un cálculo razonado.

---

## 9. Pruebas y evidencias

```
ruff check .............. All checks passed
ruff format ............. 211 archivos sin cambios
mypy .................... no issues found in 194 source files
pytest pruebas/unidad ... 669 passed
```

Antes de esta fase: 662 pruebas pasaban y **7 fallaban** (las de la vigilancia); `mypy` daba 5 errores
por las funciones que no existían.

Evidencia en ejecución:

- Ciclo NCO real: `ok · 143 nuevos, 1562 iguales`, 1.705 filas en 6 s.
- Ciclo completo del worker: `Ítems CPC: 32 fichas leídas (32 con ítems, 0 sin detalle), 0 fallidas,
  32 peticiones, **0 pendientes**` — la cola de fichas de CPC quedó vacía.
- Suite de ingesta contra la base real: **10 de 10 en 133 s**, con la prueba nueva de reapertura de
  vigencia incluida.
- **Vuelta corta aislada**, contra la fuente real y cronometrada
  (`python -m contratacion.tareas.worker --vigilancia`):

  ```
  Vigilancia NCO: ok · 12 nuevos, 0 actualizados, 1682 iguales, 204 cerrados
  duración: 17,6 s   (una sola petición al listado)
  ```

  Los **204 cerrados** son la señal de vigencia grabándose por primera vez en el histórico; los 12
  nuevos, necesidades publicadas en los minutos anteriores. Es la comprobación de que la vuelta
  corta hace su trabajo y de que no arrastra nada más: no consultó la cola de términos, no leyó
  fichas y no invalidó la caché.
- El worker arranca con las dos cadencias: `Worker iniciado. Ciclo completo: 15 min. Vigilancia del
  listado: 150 s.` — el mensaje que el lanzador imprimía desde antes, y que hasta esta fase no era
  cierto.
- Diagnóstico del filtro de CPC con la lista real del cliente (tabla de la sección 4).

El coste de la vigilancia, para poder decidir si se baja más: **17,6 s cada 150 s** de reloj, con
una petición de ~1,9 MB por vuelta. Es alrededor del 12 % del tiempo del worker, y el resto lo
ocupa el ciclo completo.

---

## 10. Deuda y decisiones pendientes

**De negocio (necesitan respuesta antes de cerrar la fase):**

1. **Nueve de los 31 términos de CPC no encuentran nada.** Hay que decidir si se quitan de la lista o
   se dejan: son términos que no existen en la nomenclatura oficial.
2. **Encender el cierre de vigencia en producción tiene efecto visible.** Desde ahora, una necesidad
   que desaparece del listado se marca `es_vigente = false`, y esa columna sale en el Excel («Vigente»)
   y en `cerrados`. Es la intención del diseño, pero conviene que el cliente sepa que empezará a ver
   cierres donde antes veía todo abierto.

**Técnica:**

- La **cola de términos avanza a veinte palabras por ciclo** (`limite_terminos_por_ciclo`), limitada
  por el presupuesto de peticiones y, en último término, por la fuente. Con muchos términos activos,
  una palabra clave nueva puede tardar más de media hora en tener datos. No se sube a ciegas: el
  techo lo pone SERCOP, y subirlo sin medir se paga en 429.
- **La prueba de carga sigue pendiente** (ver la sección 8). Es la única forma de prometer una cifra
  de usuarios concurrentes.
- `guardar_registro` y `agregar_historial` (una fila) siguen existiendo y ya solo los usa una prueba
  de integración. Conviene decidir si se retiran o se quedan como camino de rescate.
