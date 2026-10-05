# Fase 4.7 — Panel de la plataforma: el trabajo de la ingesta y el botón de ejecutar

> Documento de fase según la plantilla de `documentacion.md` § 9.2.

## 1. Objetivo

Que el dueño de la plataforma pueda **ver lo que han trabajado los workers y pedirles un ciclo sin
esperar al turno**. Hasta aquí la ingesta era una caja negra desde el panel: existía `GET /v1/ingestas`
con el último ciclo de cada fuente, pero no se podía ver la serie —si el worker lleva dos horas
callado o si lleva cinco ciclos fallando— ni se podía forzar una vuelta.

Y, en el mismo encargo, arreglar las **gráficas del panel**, que mentían: provincias con cero
contrataciones que aparecían con decenas al filtrarlas, y el resto de provincias cayéndose a cero al
aplicar el filtro.

## 2. Alcance

**Incluido**

- Serie de sincronizaciones por fuente en la API, leída de `sincronizacion` (no se instrumenta nada
  nuevo: es la tabla que los ciclos ya escriben para poder auditarse).
- Petición de un ciclo completo desde el panel, por el único canal que los dos procesos comparten
  (la caché), y consumo de esa petición por el worker.
- Tarjeta «Trabajo de la ingesta» en la pantalla de plataforma: gráfica de barras por ciclo, estado y
  cifras del último ciclo de cada fuente y botón **Ejecutar ahora**.
- Arreglo del agregado por provincia (el recorte a doce filas y el filtro aplicado al reparto) y del
  agrupado por grafía.
- Arreglo de la gráfica que **nacía en blanco** cuando su pestaña estaba oculta al montarse.
- Cada gráfica del Resumen dice **qué familia** está enseñando, y el Resumen deja **elegir qué
gráficas se ven** (con la preferencia recordada en el navegador).

**Excluido (deliberadamente)**

- Que el API ingeste: ninguna petición de usuario puede originar tráfico hacia el SERCOP (R-01, CU-07).
  El botón deja una petición; el ciclo lo ejecuta el worker.
- Un botón para detener un ciclo en marcha: un ciclo a medias deja filas a medio escribir y el diseño
  del bloqueo no contempla interrumpirlo.
- Elegir la fuente del ciclo pedido: los ciclos son completos (las dos fuentes) porque así es como está
  construido el planificador.

## 3. Implementaciones realizadas

| Pieza | Archivo / símbolo | Qué hace |
|---|---|---|
| Puerto | `aplicacion/puertos/consultas.py` → `historial_sincronizaciones` | La serie de ciclos, no solo el último. Por fuente, porque las dos tienen cadencias distintas. |
| Adaptador | `salida/bd/consultas.py` → `historial_sincronizaciones` | `JOIN LATERAL` con tope **por fuente**: con un `LIMIT` global, la fuente que más escribe se quedaría con toda la ventana. |
| Caso de uso | `aplicacion/casos_uso/operar_ingesta.py` | `solicitar_ciclo`, `solicitud_pendiente`, `consumir_solicitud`, `tablero_ingesta`. La comprobación de rol vive aquí, no en el enrutador. |
| API | `routers/plataforma.py` → `GET /v1/plataforma/ingesta/historial`, `POST /v1/plataforma/ingesta/solicitud` | Declarados **antes** de las rutas con `{negocio_id}` por la norma de la casa (FastAPI resuelve en orden de declaración). |
| Worker | `tareas/worker.py` → `_solicitud_de_ciclo`, rama de «ciclo pedido» en `bucle()` | Consume la petición y adelanta el ciclo; el sueño se trocea en tramos de `PASO_COMPROBACION_SEG` (5 s) para notarla. |
| Panel | `components/TrabajoWorkers.vue` | La tarjeta: gráfica, lista por fuente, botón, y refresco propio (5 s con petición pendiente, 20 s sin ella). |
| Panel | `components/VistaPanel.vue` | Selector de gráficas del Resumen con la preferencia recordada; estilos de barra de selección unificados (`.selector`). |
| Panel | `utils/familias.js` | **Un solo sitio** para el nombre de las familias: lo usan el selector del mapa, el titular de la tabla y la pista de cada gráfica. |
| Panel | `components/{GraficaProvincias,GraficaSerie,GraficaFuentes}.vue` | Cada gráfica dice **qué familia** está mostrando, y la serie deja de decir «doce meses» cuando enseña veinticuatro. |
| Panel | `api/endpoints.js`, `utils/formato.js` | `trabajoDeIngesta`, `pedirCiclo`, `horaCorta`. |
| Gráficas | `infraestructura/.../bd/consultas.py` → `LIMITE_PROVINCIAS` 12 → 60, `donde_sin_provincia` | El reparto llega entero y **sin** el filtro de provincia, para que elegir una no ponga las demás a cero. |
| Gráficas | `composables/useGrafica.js` → `vigilarVisibilidad` | Redibuja la gráfica que nació con su sección oculta (ver § 4). |
| Medida | `scripts/verificar_plataforma.py` § 10 | Comprueba la costura entera: historial, rol, petición y que el worker la recoja. |
| Medida | `scripts/verificar_graficas.py` | Contraste de las gráficas contra la tabla con datos reales. |

## 4. Decisiones tomadas y justificación

**La petición viaja por la caché, no por una tabla.** Una petición es «una vez» y caduca; guardarla en
la base obligaría a decidir qué es una fila vieja, quién la limpia y qué significa que quede una
petición de hace tres días. En la caché eso es un `TTL` de 900 s y un borrado al recogerla. Además el
worker ya mira la caché cada 5 s, así que el canal no añade infraestructura.

**La petición se borra al recogerla.** Si nadie la borrara, el worker la ejecutaría en **cada** vuelta
—un ciclo cada cinco segundos—, que es exactamente lo que la fuente castiga con 429.

**Sin caché configurada se rechaza la petición con un motivo.** Aceptarla y perderla dejaría un botón
que dice «hecho» mientras no pasa nada: la peor forma de fallar. `EstadoInvalido` con el porqué.

**El rol se comprueba en el caso de uso.** «Solo el dueño del sistema ordena la ingesta» es una regla
de negocio: tiene que negarse igual desde la API, desde el worker o desde una tarea programada.

**El sueño del worker se trocea en vez de dormir hasta la hora.** Es lo que hace el botón utilizable:
el retardo de un ciclo pedido es como mucho el tramo (5 s) en vez de hasta quince minutos. El tramo es
una lectura de caché de una clave.

**Un ciclo pedido a mano es un ciclo.** Se da por servida la hora del ciclo completo y se reprograma la
vigilancia, igual que en la vuelta programada: así no viene seguido de otro ciclo inmediato ni de una
vuelta corta que ya no tendría nada que leer.

**El reparto por provincia se calcula sin el filtro de provincia.** Es lo que permite ver el mapa
completo y **a la vez** resaltar la seleccionada. Se normaliza la clave (sin tildes, en mayúsculas)
porque agrupar por el texto crudo partía `SANTO DOMINGO DE LOS TSÁCHILAS` en dos provincias y una de
ellas caía fuera del tope.

**La gráfica se redibuja cuando su lienzo entra en pantalla, y solo si nunca tuvo tamaño.** Las
pestañas del panel conviven en el documento con `v-show`, así que una gráfica puede montarse en
`display: none`. Chart.js **no se entera** de que el contenedor aparece: su observador vigila el
lienzo, y el lienzo mide 300×150 antes y después de mostrarse. Medido: cero píxeles pintados hasta que
algo la refrescaba (un filtro, el tema, una recarga), y por eso parecía aleatorio. La condición
`!grafica.width || !grafica.height` distingue «nací escondida» de un cambio de visibilidad normal, que
no debe rehacer la gráfica (perdería la animación y el estado del cursor).

**Cada gráfica dice qué familia muestra.** La familia la fija la pestaña desde la que se llega, así que
desde la gráfica no se puede adivinar: sin decirlo, la misma gráfica podría estar contando ínfimas o
procesos con oferta y parecería lo mismo. El nombre sale de `utils/familias.js`, **un solo sitio**,
porque aparece en tres (selector del mapa, titular de la tabla y pista de cada gráfica) y con copias
bastaba reescribir una para que la pantalla dijera dos cosas distintas de lo mismo.

**El Resumen deja elegir qué gráficas se ven.** No todas sirven siempre: con el filtro de CPC puesto,
«Origen de los datos» dice «todas de NCO» y no informa de nada; quien mira el mapa todo el día no
necesita la serie mensual. La elección se guarda en el navegador —como la del panel de filtros— porque
es una preferencia de quien mira y no una configuración de la empresa. **Quitar la última se impide**:
una pantalla vacía no explica cómo volver y el botón que la arregla estaría donde ya no se mira. Se
ocultan con `v-show` y no con `v-if` para no destruir la gráfica (y porque el envoltorio ya sabe
redibujar la que nació sin tamaño).

## 5. Casos de uso y requisitos

- **CU-07 / R-01** — ninguna petición de usuario origina tráfico hacia la fuente: el botón escribe una
  petición y el worker ejecuta. Verificado: el endpoint responde **201** sin tocar el SERCOP.
- **RF-13** (estado de la ingesta) — pasa de «último ciclo» a «serie de ciclos».
- Administración de plataforma: los dos endpoints exigen el rol `super_admin`, negado en el caso de uso.

## 6. Pruebas ejecutadas y resultado real

| Qué | Comando | Resultado |
|---|---|---|
| Unidad (nuevas: `test_operar_ingesta.py`, más dos del bucle) | `pytest pruebas/unidad` | **721 passed** (antes 710) |
| Lint y tipos | `ruff check .` · `mypy` | `All checks passed!` · `no issues found in 207 source files` |
| Plataforma, extremo a extremo | `python scripts/verificar_plataforma.py` | **Todas las comprobaciones pasaron** |
| Gráficas contra la tabla | `python scripts/verificar_graficas.py` | **Todas las comprobaciones pasaron** |

Lo que enseñó la verificación de la plataforma (§ 10), con la API y el worker levantados:

```
OK  GET /v1/plataforma/ingesta/historial -> 200
OK  fuentes informadas: ['NCO', 'OCDS']
OK  cada ciclo trae al menos cuándo arrancó, cómo acabó y cuánto escribió
ciclos por fuente: {'NCO': 24, 'OCDS': 24}
cadencia de comprobación: 5.0 s
OK  un admin de empresa -> 403 | sin_permiso
OK  un admin de empresa no puede pedir un ciclo -> 403
OK  POST /v1/plataforma/ingesta/solicitud -> 201
el worker la recogió en 3.2 s
OK  ciclos arrancados después de la petición: ['2026-10-01T18:59:05.742534+00:00']
```

Y en el registro del worker, la costura entre los dos procesos:

```
2026-10-01 13:55:21,865 INFO contratacion.worker Ciclo completo pedido desde el panel por 2a175c8a-…; se adelanta.
2026-10-01 13:55:23,774 INFO contratacion.tareas.planificador OCDS: sin términos por rescatar; se lee el rabo del listado general
```

En el navegador, con la sesión del superadministrador:

- La tarjeta pinta la gráfica (65.588 píxeles no blancos del lienzo) y **también** las del Resumen
  (81.499 y 48.908), que antes solo aparecían si algo las refrescaba.
- «Ejecutar ahora» → aviso «Ciclo pedido a las 14:05…», botón bloqueado mientras hay petición, y la
  petición desaparece cuando el worker la toma.
- El ciclo aparece en la lista como **en marcha** y después **terminado · 14 nuevos**: la gráfica y la
  lista cuentan lo que pasó de verdad.
- El panel se puso al día solo al terminar el ciclo: contador de Ínfimas **335 → 345** y «Datos de la
  generación 63».
- El selector de gráficas: quitar «Publicaciones por mes» oculta su tarjeta y guarda
  `panel:graficas = ["provincias","fuentes"]`; **quitar la última se impide** (el botón se bloquea y
  avisa con un `title`); y al recargar la página la elección vuelve. Al volver a mostrarlas, las dos
  ocultas **pintan** (83.767 y 49.239 píxeles) aunque se montaron escondidas: es el arreglo de
  `useGrafica` en un caso nuevo.

## 7. Defectos encontrados y corregidos durante la fase

1. **La lista de avisos se pintaba como `[]`.** Los avisos llegan como lista (`jsonb`) y **una lista
   vacía es verdadera** en JavaScript, así que un `v-if="avisos"` a secas pintaba un renglón con `[]`
   en todos los ciclos que no avisaron de nada, que son casi todos. Se mira la longitud.
2. **El `IntersectionObserver` tumbaba el panel entero.** La primera versión del arreglo se ataba al
   lienzo en `onMounted`, y una tarjeta con el lienzo detrás de un `v-if` monta **sin** canvas:
   `observe(null)` lanzaba `parameter 1 is not of type 'Element'` y la excepción se llevaba por delante
   el resto del montaje —el panel quedaba pintado, sin datos y sin una sola petición en la red—. Se
   vio en el navegador, no en las pruebas. Ahora la vigilancia se ata al lienzo que se acaba de
   dibujar, y el vigilante de datos se dispara en `flush: 'post'` para que el canvas ya exista.
3. **La comprobación del ciclo nuevo miraba demasiado pronto.** El worker consume la petición y
   **después** abre la fila de la sincronización: preguntar en el mismo suspiro encontraba cero ciclos
   con el ciclo arrancando. El guion espera ahora hasta 20 s, y hasta 120 s a que la petición sea
   recogida —un worker dentro de un ciclo no la mira, y un ciclo tarda minutos: medido, una petición
   hecha con el worker ocupado seguía en cola a los 30 s—.

## 8. Deuda técnica y pendientes

- **Gráficas nuevas**: hoy se puede elegir **cuáles** de las tres se ven, pero no hay más gráficas que
elegir. Añadir otras (por entidad, por tipo de procedimiento, por estado o por rango de monto) exige
un agregado nuevo en el servidor por cada una: es trabajo y hay que decidir cuáles se piden.
- El botón no distingue «hay un ciclo en marcha» de «hay uno en cola», que se ve en la lista por
fuente (`en marcha`) pero no en el botón, que solo dice «Ciclo en cola».
- No hay tope de peticiones por persona: cualquiera con el rol puede pedir ciclos. Con un solo
  superadministrador no es un problema hoy; con varios, conviene un freno (una petición cada X
  minutos).
- La gráfica mezcla en la misma escala los ciclos del worker (decenas de filas) y las cargas masivas
  del año (miles, que también anotan su sincronización). Es honesto —son sincronizaciones de verdad—
  pero las barras pequeñas se ven como una raya. Se irá solo cuando esas cargas salgan de la ventana
  de 24 ciclos.

## 9. Riesgos abiertos

- **La petición caduca a los 900 s.** Si el worker está caído, la petición muere sola y el panel deja
  de decir «en cola»: es lo que se quiere (no disparar un ciclo a traición horas después), pero
  significa que quien pidió un ciclo con el worker caído no recibe ningún aviso de que se perdió.
- **Con dos réplicas del worker**, las dos pueden leer la petición antes de que ninguna la borre. No se
  paga nada: la segunda encontraría el bloqueo de la fuente tomado y no escribiría nada.
- El refresco de la tarjeta es a 20 s sin petición pendiente: no es un canal en vivo. El canal de
  presencia existe y podría usarse para esto, pero hoy no transporta eventos de ingesta.

## 10. Aprobación

- **QA**: pendiente de firma. La evidencia de § 6 está reproducida en esta máquina.
- **Revisor de código**: pendiente.
