# Fase 4e — Ingesta general de OCDS y relleno del año

> Estado: **en curso al escribir esto** (el relleno del año está corriendo). Lo que aparece como
> «medido» está medido; lo que aparece como pendiente, lo está, y se dice.

## 1. Objetivo

Que los filtros de ofertas tengan sobre qué buscar. Hasta aquí OCDS se ingestaba **por palabra
clave**: cada término de la cola costaba una petición por año y página, así que la tabla de procesos
publicados solo tenía lo que coincidía con las palabras clave del cliente —800 filas para un año que
tiene 103.628— y buscar cualquier otra cosa en el panel devolvía poco más que nada, porque el filtro
trabaja sobre lo ya ingestado.

El objetivo tiene dos mitades: **traer el año entero** (una vez) y **seguir al día con muy pocas
peticiones** (para siempre), sin tocar el comportamiento de los filtros del panel.

## 2. Alcance (incluido / excluido)

**Incluido**

- Adaptador del **listado general** de OCDS: `search=` vacío, ordenado por fecha, leyendo el final.
- Modo **relleno** del mismo adaptador: caminar hacia atrás desde una página dada.
- Planificador: el rabo se ingesta siempre; las palabras clave quedan como **rescate** de una vez.
- Ajustes: páginas por ciclo del rabo y presupuesto de peticiones del ciclo.
- Guion reanudable `scripts/rellenar_ofertas_ocds.py` y comprobación `scripts/verificar_relleno.py`.
- Worker: el ciclo completo cada 15 min y la vigilancia de NCO cada 150 s se mantienen como estaban.

**Excluido**

- Años anteriores a 2026 (el relleno se lanza por año, `--anio`).
- CPC en OCDS: la fuente no publica clasificación, así que el criterio solo tiene datos en las ínfimas.
- Retirar el índice `ix_registro_datos`: hay un indicio de que solo lo usa la consulta de catálogos,
  pero quitarlo sin un `EXPLAIN` medido sería adivinar.

## 3. Implementaciones realizadas

| Componente | Archivo / símbolo | Qué hace |
|---|---|---|
| Adaptador general | `salida/fuentes/ocds.py` · `FuenteOcdsGeneral` | Lee el **rabo** del listado general del año: la primera página para saber cuántas hay, y luego hacia atrás tantas como creció el listado desde la vuelta anterior |
| Filtro del rescate | `tareas/planificador.py` · `fuentes_por_defecto` | De la cola solo pasan al adaptador los términos con `ultima_ingesta_en` nulo: los que nunca se han buscado |
| Modo relleno | `FuenteOcdsGeneral(desde_pagina=…)` | Arranca en esa página y camina hacia atrás, sin sondear la primera. Es lo que permite recorrer el año en tandas |
| Tope de páginas | `FuenteOcdsGeneral._paginas_a_leer` | Estima cuántas páginas leer **por tiempo transcurrido** (1,6 páginas/hora × margen 3), con un mínimo de 2 y el tope del ciclo |
| Rescate | `FuenteOcdsGeneral.extraer` | Si la cola trae términos **nunca buscados**, los busca además del rabo, con una reserva de presupuesto (`RESERVA_PARA_RESCATE`) para que no se queden sin cuota |
| Planificador | `tareas/planificador.py` · `fuentes_por_defecto` | NCO primero y completa; OCDS siempre, con `desde=None` (la ventana la fija la marca de agua) salvo que haya términos por rescatar |
| Ajustes | `config/ajustes.py` | `paginas_generales_por_ciclo` (40) y `presupuesto_peticiones_ciclo` (90, subido desde 60 por el cambio de régimen) |
| Relleno reanudable | `scripts/rellenar_ofertas_ocds.py` | Tandas del tamaño del ciclo, bloqueo **por tanda**, pausa entre tandas, `--simular`, `--maximo`, `--desde-pagina`, y la marca de agua intacta |
| Comprobación | `scripts/verificar_relleno.py` | Contrasta con la base las dos cosas que el guion no puede saber: que la marca de agua no se movió y que las filas entraron vigentes |

## 4. Decisiones tomadas y justificación

**El listado general en lugar de la búsqueda por término.** Medido contra la fuente: veinte palabras
clave cuestan ~45-60 peticiones cada ciclo —unas 5.760 al día—, frente a **~133 al día** leyendo el
rabo del listado general. Treinta veces menos. Y las filas del listado general traen **más** campos
que las de una búsqueda: 15 con dato, incluidos `budget` y `suppliers`, contra 13.

**El rabo, y no el año entero cada vez.** La API pagina de lo más antiguo a lo más reciente, así que
lo recién publicado está siempre al final. Leer el final es leer lo que cambió.

**El tope de páginas se estima por tiempo, no por las fechas de las filas.** Muchas publican el día
sin hora (`2026-09-30T00:00:00-05:00`), así que su fecha es anterior a una ventana de media hora
aunque la fila acabe de aparecer: parar al ver una fecha fuera de la ventana cortaría antes de tiempo
y perdería publicaciones. El tiempo transcurrido se estima de sobra.

**El rabo no declara `listado_completo`, y eso es una decisión, no un olvido.** Declararlo aplicaría
la deducción de vigencia —«lo que ya no aparece se cerró»— a una fuente que se consulta **por
partes**: cerraría como cerrado casi todo lo que hay en la base. NCO sí lo declara, porque su listado
**es** la foto completa de lo vigente.

**La búsqueda por palabra clave no desaparece: pasa a rescate, y solo de lo que nunca se buscó.** El
listado general da lo que se publique de aquí en adelante, pero no lo que se publicó **antes** de que
esta fuente existiera. Eso solo le falta a una palabra clave **nueva**, así que el rescate se limita a
los términos con `ultima_ingesta_en` nulo. Volver a buscar por palabra clave algo que ya se buscó
serían ~45-60 peticiones por ciclo —unas 4.300 al día— por datos que el rabo ya trae, que es
exactamente el gasto que este cambio viene a quitar. El usuario sigue añadiendo palabras clave y
sigue filtrando por ellas: lo que cambia es que cada término cuesta **una** búsqueda en su vida, no
una por ciclo. Dos pruebas lo fijan (`test_solo_se_rescatan_los_terminos_que_nunca_se_han_buscado` y
`test_sin_terminos_nuevos_el_rabo_usa_la_marca_de_agua`): la segunda comprueba además que sin nada que
rescatar **no** se abre la ventana ancha, porque abrirla haría que el rabo leyera su tope entero —40
páginas— en cada vuelta en lugar de las dos o tres que de verdad creció el listado.

**El relleno se declara parcial.** `cerrar_sincronizacion` avanza la marca de agua cuando la vuelta
termina bien, y de ella deduce el ciclo normal cuántas páginas del rabo leer. Una tanda de relleno
lee el **principio** del año: si se declarara completa, el ciclo siguiente creería estar al día,
leería las dos páginas de siempre y lo publicado durante las horas de relleno se perdería **en
silencio**. La comprobación en la base lo confirma: la fila del relleno guarda la marca **anterior**
(16:21:09), no un «ahora».

**El relleno cede el bloqueo por tanda y hace una pausa de 90 s.** Sin la cesión, el relleno tomaría
el bloqueo en cuanto lo suelta —termina una tanda y empieza la siguiente— y el ciclo del worker no
llegaría a ver la fuente en las 34 horas que dura el relleno; con la cesión, el rabo sigue
ingestándose cada cuarto de hora mientras se rellena el pasado. Medido en la primera vuelta: el
relleno esperó 9 veces de 30 s a que el worker terminara su ciclo.

**El relleno no puede superar el presupuesto del ciclo.** Los valores de intervalo y presupuesto que
se le pasan al ciclo son los mismos que usa el worker, para no reescribir la fila de la fuente. Por
encima de ese presupuesto habría que reconfigurar la fuente, y eso no lo hace un guion de
mantenimiento.

**El mínimo de páginas del rabo se aplica dentro del `min`, no sumado.** La primera versión sumaba
`PAGINAS_MINIMAS_DEL_RABO` a la estimación, y como `ceil` de cualquier positivo ya vale uno, contaba
el mínimo dos veces y leía una página de más en cada vuelta. Lo destapó una prueba, no la revisión.

## 5. Casos de uso y requisitos cubiertos

| ID | Descripción | Estado |
|---|---|---|
| R-01 | Ninguna petición de usuario puede originar tráfico hacia el SERCOP | Se mantiene: el relleno es un guion de mantenimiento, no un endpoint; el panel solo lee de la base y de la caché |
| CU-05 | Consultar contrataciones de la fuente | Cubierto con el listado general: 103.628 filas del año, contra las 800 que había |
| CU-07 | Nunca se llama al SERCOP dentro del request | Sin cambios |
| RF-04 | Estados y sesiones con auditoría | Sin cambios |

## 6. Pruebas ejecutadas y resultado real

| Prueba | Comando | Resultado |
|---|---|---|
| Análisis y formato | `ruff check .` · `ruff format .` | `All checks passed!` · 216 archivos sin cambios |
| Tipos | `mypy` | `Success: no issues found in 199 source files` |
| Unidad | `pytest pruebas/unidad` | `678 passed` |
| Adaptador de OCDS | `pytest pruebas/unidad/test_fuente_ocds.py` | `10 passed` (6 del modo por término, 4 del general: tope por tiempo, mínimo no duplicado, sin términos, relleno) |
| Vigilancia y cadencia | `pytest pruebas/unidad/test_vigilancia_listado.py` | `12 passed` (2 nuevas) — el ciclo completo sí consulta la cola; la vuelta corta no; el rescate solo toma términos nunca buscados; sin ellos el rabo usa la marca de agua |
| Integración | `PRUEBAS_INTEGRACION=1 pytest pruebas/integracion` | `10 passed` en 133 s |
| Plan del relleno | `scripts/rellenar_ofertas_ocds.py --simular` | 10.363 páginas · 103.630 filas · 1.031 MB · 260 tandas |
| Una tanda real | `--desde-pagina 5000 --paginas 5 --maximo 5` | 45 filas nuevas, 0 errores, 1 min 1 s |
| La base después | `scripts/verificar_relleno.py` | La sincronización del relleno queda `parcial` con la marca **anterior**; las 800 filas de OCDS siguen vigentes |

## 7. Evidencia de aceptación

```
$ python scripts/rellenar_ofertas_ocds.py --simular
OCDS 2026
  el año tiene 10363 páginas · 103630 filas · 1031 MB en la base con los índices
  se camina de la página 10363 a la 2: 10362 páginas · 103620 filas · ~1031 MB
  en tandas de 40: 260 tandas · ~34 h 32 min al ritmo medido de 12 s por página —429 incluidos—

$ python scripts/rellenar_ofertas_ocds.py --desde-pagina 5000 --paginas 5 --maximo 5
La fuente respondió 429 en general · 2026 · pág. 5000; reintento en 29.0s (1/4)
[  1] páginas   5 (hasta la  4995) · nuevas   45 · actualizadas    0 · iguales    0 · sin mapear   0
Páginas leídas en esta ejecución: 5 en 1 min 1 s (1 tandas)

$ python scripts/verificar_relleno.py
Fuente OCDS
  configuración: cada 15 min · 60 peticiones por ciclo
Últimas sincronizaciones
  2026-10-01 16:27:26 · parcial  ·   5 pet. ·    45 nuevas · agua 2026-10-01 16:21:09
  2026-10-01 16:21:11 · ok       ·  38 pet. ·     2 nuevas · agua 2026-10-01 16:21:09
Registros de OCDS: total 800 · vigentes 800

$ .\levantar.ps1     # el worker, ya con la ingesta general
    2026-10-01 11:32:21 INFO  contratacion.tareas.planificador
    OCDS: 20 términos por rescatar (0 nunca buscados), desde 2026-10-01T15:21:08+00:00
```

El primer 429 de la tanda es el dato más útil de todos: **el ritmo real es de ~12 s por página**, no
los 0,6 s del intervalo mínimo, porque la fuente responde 429 en cuanto se la aprieta y cada espera
cuesta 20-30 s. De ahí que el plan diga 34 horas y no «dos horas y media».

## 8. Deuda técnica y pendientes

- **El año no está relleno todavía.** Al cerrar esta nota hay **800 filas de OCDS** en la base de las
  103.630 del año (0,8 %). El relleno va por tandas y dice por dónde seguir; se reanuda con
  `--desde-pagina <n>`.
- **La cola de términos ya solo significa el rescate.** Lo que el panel muestra como «en cola» son
  términos pendientes de **una** búsqueda, no de una vigilancia continua. Conviene revisar el texto
  de la pantalla para no prometer lo que ya no hace.
- **`ix_registro_datos` puede sobrar.** Es un GIN sobre `datos` de 16,3 MB (36 % de los índices) y el
  único sitio que lo usa es la consulta de catálogos. Retirarlo sin un `EXPLAIN` medido sería
  adivinar; queda pendiente de medir.
- **La prueba de carga sigue pendiente** (900 paneles con el flujo de eventos abierto). Es lo que
  convierte las estimaciones de `docs/07` en hechos.
- **El relleno no está automatizado.** Es un guion manual a propósito: mueve 1 GB de datos y consume
  cuota de la fuente durante más de un día.

## 9. Riesgos abiertos y mitigaciones

| Riesgo | Por qué importa | Mitigación |
|---|---|---|
| El relleno y el worker compiten por la misma fuente | Dos limitadores distintos contra un origen que ya responde 429: cada 429 cuesta 20-30 s | Bloqueo por tanda, pausa de 90 s y cesión cuando el worker está dentro. Medido: 9 esperas en la primera vuelta |
| Un relleno muy largo deja el rabo sin leer más tiempo del que cubre el tope de 40 páginas | 40 páginas ≈ 25 horas de crecimiento; un relleno que monopolizara el bloqueo más de eso perdería publicaciones | El bloqueo se cede cada tanda y la marca de agua no avanza, así que el ciclo siguiente abre la ventana que haga falta |
| El crecimiento de la base | 10,4 KB por fila con índices; el año añade ~1 GB y el historial se duplica cada ~12 días | Medido en `docs/07`; el histórico está particionado por meses, así que purgar es `DROP PARTITION` |
| El relleno se corta a medias (sesión, red, 429 sostenido) | Se perdería el trabajo hecho y se repetiría el ya hecho | Es reanudable: cada tanda se confirma entera, dice la página por la que sigue y el `upsert` por huella es idempotente |
| Leer el rabo con la ventana mal calculada | Perder contrataciones es irreversible | La ventana sale de la marca de agua (tiempo transcurrido × 1,6 páginas/hora × 3 de margen), con el tope del ciclo como única cota |

## 10. Aprobación

| Rol | Nombre | Fecha | Veredicto |
|---|---|---|---|
| Ingeniero QA | | | |
| Revisor de Código | | | |
| Revisor de Ingesta | | | |
