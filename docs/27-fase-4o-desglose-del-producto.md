# Fase 4o — El desglose del producto, la barra de filtros y el detalle de una oferta

> Cierre de la tanda pedida el 2026-10-06: «agrega un botón para pegar una lista en la descripción
> del producto, ajusta la barra lateral que se ve un poco faltante de espacio, y en el recuadro de
> detalle de una oferta pon un poco más de información del producto».

## 1. Objetivo

Tres cosas con la misma raíz: **entender qué se está comprando**.

1. **Pegar una lista** de descripciones, como ya se hacía con las palabras clave y el CPC.
2. **La barra lateral**, que se veía apretada y con una barra horizontal que cortaba el texto.
3. **El detalle de una oferta**, que decía muy poco del producto. Lo que faltaba no era pintar más
   campos: era que **el desglose del producto se estaba tirando** al importar.

## 2. Alcance (incluido / excluido)

**Incluido**

- Alta en bloque de descripciones (`≡ Pegar una lista`), con contador y resumen de lo que entró.
- Un solo mínimo de término en el panel: estaba declarado **cuatro veces**.
- Arreglo del desbordamiento horizontal de la columna de filtros y más sitio para el texto.
- **Los ítems del producto de una oferta**, leídos del fichero mensual del portal, guardados con la
  misma forma que los de las ínfimas, y con ellos el texto y los códigos del CPC.
- Un bloque **«El producto»** en el cajón de detalle, más el identificador de la fuente y el
  seguimiento del dato.

**Excluido**

- Meter los ítems de OCDS en el buscador por CPC de las ínfimas **no** era el objetivo, pero ocurre:
  ver § 4.4. Es un efecto real y medido, y se documenta en lugar de esconderse.
- Años anteriores: los ficheros del portal son anuales y solo se importa el año en curso.

## 3. Implementaciones realizadas

| Componente | Archivo / símbolo | Qué hace |
|---|---|---|
| Traducción del ítem | `ocds_masiva.py` · `traducir_item`, `items_del_proceso` | Convierte `tender.items` (o los de la adjudicación) a la forma de `ItemCpc`. |
| Clave interna | `_items` en la fila plana | Viaja al margen de los campos canónicos: el mapeo la ignora por la convención del guion bajo. |
| Caso de uso de ingesta | `ejecutar_ingesta.py` · `_items`, `_mapear_todo` | Lleva el desglose hasta la escritura. |
| Escritura por lotes | `ingesta.py` · `guardar_registros` | Escribe `items`, `cpc_busqueda`, `cpc_codigos` e `items_recogidos_en` en la misma sentencia, **con guarda**: una lista vacía no borra lo que había. |
| Reglas de términos | `utils/terminos.js` | Único sitio del mínimo, del troceo de una lista pegada y de la clave de comparación. |
| Descripción al por mayor | `stores/filtros.js` · `agregarVariasDescripcion` | Añade la lista al borrador y devuelve añadidas, repetidas y cortas. |
| Barra de filtros | `VistaPanel.vue`, `GestorPalabrasCpc.vue`, `GestorDescripcionProducto.vue` | Columna de 340 px, relleno menor, `overflow-x: hidden` y botones que envuelven. |
| Detalle | `CajonDetalleOferta.vue` | Bloque «El producto», identificador en la fuente, fuente y bloque «El dato». |

## 4. Decisiones tomadas y justificación

### 4.1 El desglose del producto estaba en la fuente y se tiraba

Medido antes de tocar nada, contra la base y contra los ficheros:

- En la base: **0 de 104.322** ofertas tenían ítems. Las 5.487 ínfimas con desglose venían de leer
  la ficha una a una.
- En el fichero de septiembre: **105 de 400** publicaciones traen `tender.items`, con
  `classification.id` (el CPC), `description` (lo que escribió la entidad), `unit.name` y `quantity`.
- Contado en local, sin tocar la base: de los **103.906** procedimientos del año, **96.777** traen
  desglose; en total **391.864 ítems**, 4 por proceso.

La decisión era cara (tocar la escritura por lotes y reimportar el año) o dejar la pregunta abierta
para siempre. Se hizo, y el resultado medido **coincide exactamente** con la previsión local:
96.777 ofertas con desglose.

### 4.2 El desglose no entra en la huella, así que la reimportación es la que lo rellena

`hash_contenido` mira `datos`, y los ítems no son un campo canónico. Consecuencia que se pasa por
alto con facilidad: **una fila ya importada sin ítems se ve «igual» que una con ellos**. Si el ciclo
se saltara las filas iguales, reimportar el año no escribiría ni un ítem. Por eso hay una excepción
explícita —una fila igual **con** ítems se reescribe— y no cuenta como actualización ni deja
historial: el contenido de `datos` no ha cambiado.

### 4.3 La guarda de la lista vacía

La misma fila la escriben tres caminos: la importación mensual (trae el desglose), el listado
paginado y la vigilancia del listado (no lo traen). Sin la guarda, el primero que pasara después
dejaría el detalle en blanco **sin ningún error**. Está cubierta por una prueba de integración que
escribe con ítems, vuelve a escribir sin ellos y comprueba que siguen ahí.

### 4.4 Efecto secundario, medido: el buscador por CPC ahora encuentra ofertas

No era el objetivo, pero es coherente con que el detalle enseñe el CPC de una oferta: si la ficha
dice `832110112`, el buscador tiene que encontrarla. Antes el CPC solo existía en las ínfimas.

> 96.777 de las 104.693 ofertas (92 %) tienen ya clasificación. Con «Cualquiera» los términos de
> CPC encuentran mucho más que antes; con «Todas» sigue siendo una intersección, y en las ofertas
> los ítems de un mismo proceso comparten clasificación, así que el modo «Todas» funciona mejor de
> lo que funcionaba en las ínfimas.

### 4.5 Pegar una lista: el mismo gesto en los tres campos, con una diferencia

Palabras clave, CPC y descripción abren el mismo par de botones. La diferencia está en dónde vive la
lista: el CPC es del servidor (cada alta viaja a la API) y la descripción es del borrador (local).
Por eso el campo de la descripción **se queda abierto** después de añadir —lo normal es escribir dos
o tres seguidos— y el del CPC se cierra, porque cerrar confirma que se guardó.

### 4.6 La barra lateral: `overflow-y` arrastra el otro eje

El síntoma era «le falta espacio» y una barra horizontal que cortaba el texto. La causa no era el
ancho: con `overflow-y: auto`, CSS convierte `overflow-x` en `auto` por su cuenta, y **cualquier**
contenido más ancho sacaba la barra. Lo que la sacaba eran los dos botones del CPC, que no cabían en
252 px de contenido. Se arregla en los tres sitios: los botones envuelven (`flex-wrap` y
`min-width: max-content`), la columna pasa a 340 px y su relleno a `--e-4` (el texto dispone de
308 px), y `overflow-x: hidden` lo deja cerrado para el próximo control ancho.

### 4.7 El mínimo de un término estaba en cuatro sitios

`LONGITUD_MINIMA = 3` estaba en `OfertasTab.vue`, `stores/filtros.js`, `utils/cpc.js` y como
`LONGITUD_MINIMA_TERMINO` en `utils/terminos.js`. Ahora hay una sola declaración, junto con
`terminosDeLista`, que antes vivía en el módulo del CPC aunque lo usaran los tres campos.

## 5. Casos de uso y requisitos cubiertos

| ID | Descripción | Estado |
|---|---|---|
| F4.2 / F4.12 | Buscar por CPC y por descripción del producto | Se suman las **ofertas** al CPC |
| — | Pegar una lista de descripciones | Cubierto |
| — | Ver qué se compra en el detalle de una oferta | Cubierto |

## 6. Pruebas ejecutadas y resultado real

| Prueba | Comando | Resultado |
|---|---|---|
| Estilo y tipos | `ruff check src pruebas scripts` · `ruff format --check` · `mypy` | Limpio (225 y 223 archivos) |
| Unidad | `pytest pruebas\unidad` | **851 passed** |
| Integración del desglose | `PRUEBAS_INTEGRACION=1 pytest pruebas\integracion\test_ingesta_items.py` | **4 passed** en 54 s (contra Postgres real) |
| Compilación del panel | `npx vite build --outDir $env:TEMP\...` | 97 módulos, correcto |
| Adaptador | `pytest pruebas\unidad\test_ocds_masiva.py` | 38 passed (7 nuevas) |

## 7. Evidencia de aceptación

```
$ .\.venv\Scripts\python.exe scripts\importar_ocds_masivo.py --conservar
 10 · octubre    0.2 MB en 1 s
 11 · noviembre  no disponible (500): se omite
 12 · diciembre  no disponible (500): se omite
Lectura y combinación
  103906 publicaciones → 103906 procedimientos en 19 s
[ 11] 103906/103906 filas · nuevas   371 · actualizadas   461 · iguales  3074 · sin mapear   0
Procedimientos escritos: 103906 de 103906 en 23 min 58 s
  peticiones al portal: 10 (una por mes)

$ sonda de comprobación, después
Desglose por fuente:
  OCDS           96777 con ítems ·   96777 con CPC · de 104693
  NCO             5533 con ítems ·    5533 con CPC · de 5537
Ofertas (OCDS) por año:  2026 → 104693
```

Los 96.777 coinciden **exactamente** con lo previsto en local antes de escribir nada (96.777), que es
la comprobación de que el desglose que se guarda es el que la fuente publica.

## 8. Deuda técnica y pendientes

- **El peso de las columnas nuevas no se ha medido** con `scripts/peso_de_datos.py` después de la
  importación. Está pedido: son 391.864 ítems y un `cpc_busqueda` por fila, y conviene saber cuánto
  suman antes de decidir si la retención debe mirarlos también.
- **Los ítems de las ofertas no entran en el desglose de las ínfimas ni al revés**: son la misma
  forma, pero la columna de exportación «CPC» ya los pinta igual. No hay nada que hacer, y se deja
  escrito para que nadie lo «arregle».
- **El cajón de detalle solo existe en la pestaña de ofertas.** Las ínfimas tienen su detalle en
  línea dentro de la tabla, con los ítems incluidos. Unificarlo sería una fase propia.

## 9. Riesgos abiertos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Una vuelta posterior sin desglose borra el de una oferta | Guarda en la escritura por lotes + prueba de integración |
| Reimportar el año no rellena los ítems de las filas ya importadas | Excepción explícita para las filas iguales con ítems + 4 pruebas |
| El panel y el servidor deciden distinto qué cabe en una descarga | Una sola regla en cada lado, con la misma cuenta de meses y la misma zona horaria |
| El CPC de las ofertas cambia lo que devuelve un filtro ya en uso | Medido y documentado (§ 4.4): más resultados, nunca menos |

## 10. Aprobación

| Rol | Nombre | Fecha | Veredicto |
|---|---|---|---|
| Ingeniero QA | — | 2026-10-06 | 851 de unidad + 4 de integración contra Postgres real |
| Revisor de Código | — | 2026-10-06 | Guarda de la lista vacía revisada con prueba; clave interna `_items` documentada |
