# Fase 4c — Búsqueda por CPC

## 1. Objetivo

Que el filtro de palabras clave pueda buscar en la **clasificación normalizada** de lo que se compra
—el CPC— en lugar de solo en el texto libre de la convocatoria.

El problema que resuelve, con el caso que lo motivó: el objeto de compra de una necesidad lo escribe
la entidad con sus palabras, así que vigilar «lavado» devolvía desde un servicio de lavado de
vehículos hasta una capacitación sobre **prevención de lavado de activos**. El CPC es un vocabulario
cerrado del Estado (`871410032 LAVADO Y ENGRASADO DE AUTOMOTORES`) y filtrar por él deja fuera lo que
solo lo menciona de pasada.

## 2. Alcance (incluido / excluido)

**Incluido**

- Lectura de la ficha de cada necesidad para obtener sus ítems con CPC, código, descripción,
  unidad y cantidad.
- Almacenamiento de esos ítems y de dos formas derivadas: el texto de búsqueda del CPC y la lista
  de códigos.
- Criterio de búsqueda `cpc`, repetible, combinable con el de palabras clave.
- Relleno por tandas, reanudable y con cuota propia, dentro del ciclo de ingesta.
- Columna **CPC** en la exportación a Excel (y elegible en la pantalla de columnas).
- Bloque «Buscar por CPC» en el panel, columna CPC en la tabla y desglose de ítems en el detalle.
- Apartado 8 de `scripts/verificar_filtros.py`.

**Excluido**

- **Buscar por la descripción libre del producto** (`descripcion`). Es deliberado: esa es la parte
  que trae el ruido que el CPC viene a eliminar. Si se metiera en el texto de búsqueda, el filtro
  volvería a comportarse como el de palabras clave.
- **CPC en las ofertas (OCDS)**: esa fuente no publica detalle de ítems. El criterio no tiene datos
  ahí, y no se inventa ninguno.
- **Filtrar por ítem** (una fila por línea del detalle). La unidad de la tabla sigue siendo la
  necesidad: si una necesidad coincide por CPC, aparece entera.
- **Precio unitario o importe**: la ficha no los publica. La `Cantidad` del ítem sí es real.

## 3. Implementaciones realizadas

| Qué | Dónde |
|---|---|
| Ítem y sus formas derivadas (texto de búsqueda, códigos, resumen) | `dominio/cpc.py` |
| Analizador de la tabla de la ficha (`html.parser`, sin dependencias) y extracción del token del enlace | `salida/fuentes/nco_detalle.py` |
| Petición de la ficha y lectura del presupuesto | `salida/fuentes/nco.py::FuenteNco.items` |
| Obtención de texto con el mismo control de tasa (semáforo, intervalo, enfriamiento) | `salida/fuentes/limitador.py::solicitar_texto` |
| Puerto del detalle, opcional por fuente | `aplicacion/puertos/fuente.py::FuenteConDetalle` |
| Puerto de pendientes y escritura de ítems | `aplicacion/puertos/items.py`, `salida/bd/ingesta.py` |
| Relleno reanudable por tandas | `aplicacion/casos_uso/recoger_items.py` |
| Enganche al ciclo, bajo bloqueo propio y sin poder tumbarlo | `tareas/planificador.py::_leer_fichas` |
| Cuota por ciclo | `ajustes.fichas_items_por_ciclo` (300; 0 desactiva) |
| Columnas, índices y comentarios | `alembic/versions/0012_items_cpc.py` |
| Criterio `cpc` en los filtros y en la huella de caché | `dominio/busqueda.py` |
| Condición SQL e índice de CPC; ítems en la respuesta | `salida/bd/consultas.py` |
| Parámetro `cpc` en los tres endpoints de datos | `entrada/http/routers/busqueda.py` |
| Columna CPC del Excel y claves internas que no se vuelcan | `casos_uso/exportar_registros.py` |
| Estado, parámetros y métodos del filtro | `frontend/src/stores/filtros.js` |
| Gestor de términos de CPC: alta individual, lista pegada, fichas quitables y copia de las palabras clave | `frontend/src/components/GestorPalabrasCpc.vue` |
| Columna CPC y desglose de ítems en el detalle | `frontend/src/components/TablaRegistros.vue` |
| Reparto de listas pegadas y resumen del CPC | `frontend/src/utils/cpc.js` |
| **Lista de términos guardada por empresa**: tabla, puerto, caso de uso, adaptador y rutas | `alembic/versions/0013_cpc_claves.py`, `aplicacion/puertos/cpc.py`, `aplicacion/casos_uso/gestionar_cpc.py`, `salida/bd/cpc.py`, `routers/cpc.py` |
| El detalle se lee una vez: no se invalida al cambiar un registro | `salida/bd/ingesta.py::guardar_registro` |

## 4. Decisiones tomadas y justificación

1. **Los ítems van en columnas propias de `registro`, no dentro de `datos`.** Meterlos en `datos`
   cambiaría `hash_contenido`; el ciclo siguiente vería el registro como «actualizado», reescribiría
   `datos` con lo que trae el listado —sin ítems— y el trabajo de cada ficha se perdería en cada
   vuelta. En columnas aparte el `upsert` de la ingesta no las toca.

2. **`cpc_busqueda` es una columna distinta de `texto_busqueda`.** Compartirla habría hecho que el
   filtro de palabras clave encontrara el CPC y el de CPC encontrara el objeto: los dos filtros
   volverían a ser el mismo y el problema seguiría sin resolver.

3. **`items_recogidos_en` nulo es «pendiente», y no `items = '[]'`.** Hay necesidades publicadas sin
   tabla de detalle. Sin la marca explícita, esas se reintentarían en cada tanda para siempre: una
   petición perdida por ciclo y por necesidad contra una fuente que responde 429 con facilidad.
   Por el mismo motivo, un fallo de red **no** marca nada: el registro se reintenta y conserva los
   ítems que ya tuviera.

4. **El relleno va después de las fuentes y con el mismo adaptador.** El listado es el dato y la
   ficha es el enriquecimiento; si algo queda a medias, que sea lo segundo. Reutilizar el adaptador
   evita un segundo cliente HTTP contra el mismo origen, que duplicaría la tasa real de peticiones.

5. **El criterio `cpc` se suma al de palabras clave, no lo sustituye.** Quien envía los dos pide la
   intersección, que es lo que espera. Así el panel puede ofrecer las dos búsquedas y el cliente
   decidir cuál usa, sin que nadie pierda lo que ya tenía.

6. **Comparte el `modo` (`todas` / `cualquiera`).** La pregunta es la misma —cómo se combinan entre
   sí varias palabras de una lista— y una segunda semántica sería una segunda forma de equivocarse.

7. **Los términos de CPC sí se cachean.** Llegan normalizados (minúsculas, sin acentos, sin repetir
   y ordenados) y son un criterio pensado para repetirse, como el catálogo de palabras clave. Si
   algún día se usaran como caja de búsqueda «mientras se escribe», habría que revisar la decisión.

8. **Botón «Copiar las N palabras clave».** El caso de uso real es el mismo término en las dos
   listas. Se copian a la lista guardada —no a un borrador de la pantalla—, así que valen también
   para el compañero, y la lista de CPC se puede seguir afinando por separado quitando lo que trae
   ruido.

9. **La ficha se lee una vez, cuando el registro entra.** Ni se invalida ni se vuelve a pedir al
   cambiar el contenido: el `upsert` de la ingesta ya no toca `items_recogidos_en`, así que lo que
   se completa es el histórico, no se repasa. Lo pide la cuota —cada ficha es una petición a un
   origen que limita la tasa— y lo que se paga a cambio es que el CPC de una necesidad que cambió de
   estado se queda como estaba; para forzarlo hay `scripts/rellenar_items_cpc.py`.

10. **El gestor de CPC se maneja igual que el de palabras clave, con una diferencia deliberada:**
    no dispara ingesta. Una palabra clave **es una suscripción** —se guarda en el catálogo global y
    el `worker` la va a buscar al SERCOP—, mientras que un término de CPC solo acota lo que ya está
    ingestado. Por eso no hay cola ni espera, y el reparto de una lista pegada ocurre igual en la
    pantalla que en el caso de uso, para que el contador que se ve antes de pulsar coincida con lo
    que se guarda.

    **La lista se guarda en el servidor** (tabla `cpc_clave`, migración `0013`), y eso es lo que la
    hace útil para trabajar: la ve todo el equipo y sigue ahí al recargar, en lugar de vivir en el
    navegador de quien la escribió. Al abrir el panel se carga **y se aplica**: no es un catálogo
    donde elegir, como las palabras clave, sino la vigilancia que el equipo decidió, y quien abre el
    panel espera verla funcionando. La ✕ de cada ficha la borra de la lista guardada.

11. **El modo («todas» / «cualquiera») no se duplica en este bloque.** Es el mismo interruptor que
    el de las palabras clave y el servidor lo aplica a las dos listas; un segundo control para el
    mismo valor es la forma más fácil de que la pantalla diga una cosa mientras la consulta hace
    otra. El bloque explica cuál está activo en lugar de ofrecer otro botón.

12. **Un solo reparto de listas.** El contador que ve la persona antes de pulsar y el alta usan la
    misma función (`terminosDeLista` en el navegador, la misma regla en el caso de uso): cuando cada
    una cuenta a su manera, el botón dice «añadir 7» y añade 5. La comparación para no repetir
    ignora mayúsculas y acentos en las **dos** puertas de entrada —el alta individual aceptaba
    «LAVADO» teniendo «lavado», que es el mismo filtro—.


## 5. Casos de uso cubiertos (CU-xx) y requisitos (RF-xx / RNF-xx)

- **CU-03 (buscar en el histórico)**: nuevo criterio de búsqueda.
- **CU-05 / CU-06 (exportar / tabla)**: la columna CPC sale en el archivo y en la pantalla, con los
  mismos criterios que la tabla.
- **R-01 (ninguna petición de usuario toca la fuente oficial)**: el CPC se obtiene **solo** en el
  worker, con su propia cuota; ninguna ruta del API la consulta.
- **RNF-01 (rendimiento)**: la búsqueda por CPC usa índice GIN de texto completo y el relleno está
  acotado por ciclo.

## 6. Pruebas ejecutadas y resultado real

| Nivel | Qué cubre | Resultado |
|---|---|---|
| Unidad | Analizador de la ficha (tablas anidadas, entidades HTML, filas incompletas, códigos de 9 y 10 dígitos, fichas sin detalle), token del enlace, texto de búsqueda, códigos, resumen | `test_cpc.py` — 17 pasan |
| Unidad | Relleno: guarda el texto y los códigos, usa el enlace guardado, un fallo no marca la ficha, una necesidad sin detalle sí se marca, el presupuesto corta la tanda, no pide fichas de fuentes sin detalle | `test_recoger_items.py` — 8 pasan |
| Unidad | Criterio en la huella de caché, normalización de los operadores, suma con los términos | `test_busqueda.py` |
| Unidad | Condición SQL: columna propia, no la del texto libre; modo; ausencia; parámetro reconocido por SQLAlchemy | `test_consultas_bd.py` |
| Unidad | Costura petición → criterios | `test_criterios_cpc.py` — 7 pasan |
| Unidad | Columna del Excel, ítems que no se vuelcan, celda vacía sin ficha leída | `test_exportacion_cpc.py` — 7 pasan |
| Unidad | Lista guardada: separadores, repetidos, cortos, quitar y vaciar, aislamiento por actor | `test_gestionar_cpc.py` — 12 pasan |
| Integración | La lista en la base real: alta, clave única, quitar, vaciar y **dos negocios sin verse entre ellos** | `test_cpc_claves.py` — 6 pasan |
| Integración | El detalle no se invalida al actualizar un registro (la regla de cuota) | `test_items_no_se_releen.py` — 2 pasan |
| Manual contra el portal y la base reales | La necesidad del cliente `NIC-0860001560001-2026-00083`: 17 ítems, CPC `871410032 LAVADO Y ENGRASADO DE AUTOMOTORES`; `cpc=lavado` la encuentra; el mismo término por texto libre sigue devolviendo lo que solo lo menciona | Correcto |
| Manual en el navegador | «Gestión» guardado en la lista, **sigue ahí tras recargar** y el panel se abre filtrado: 11 contrataciones | Correcto |

Totales del backend tras el cambio: **649 pruebas de unidad**, `ruff` limpio, `mypy` limpio
(189 archivos).

## 7. Evidencia de aceptación (comandos y salidas)

```
ruff check .                → All checks passed
ruff format --check .       → 206 files already formatted
mypy src pruebas scripts    → Success: no issues found in 189 source files
pytest pruebas/unidad       → 649 passed
alembic upgrade head        → Running upgrade 0011 -> 0012 · 0012 -> 0013
```

Consulta real de la ficha y del filtro (una sola petición al portal, dentro de un presupuesto de 5):

```
items leidos de la ficha del ejemplo: 17
   resumen: 871410032 LAVADO Y ENGRASADO DE AUTOMOTORES
filas con texto de CPC guardado: 1
cpc=('lavado',)               -> 1 filas; ejemplos: ['NIC-0860001560001-2026-00083']
cpc=('871410032',)            -> 1 filas; ejemplos: ['NIC-0860001560001-2026-00083']
cpc=('lavado', 'engrasado')   -> 1 filas; ejemplos: ['NIC-0860001560001-2026-00083']
```

## 8. Deuda técnica y pendientes

- **Relleno inicial: hecho.** `scripts/rellenar_items_cpc.py` leyó las 2.209 fichas pendientes en
  30 min 28 s (23 tandas, **0 fallos**): 2.206 con ítems, 3 necesidades sin detalle, 0 pendientes.
  El histórico quedó con **11.734 ítems** y **2.307 códigos de CPC distintos** en 2.210 registros.
- **El CPC solo existe en las ínfimas (NCO).** OCDS no publica detalle de ítems, y sus 53 registros
  nunca entran en el relleno (se pide solo a las fuentes que publican ficha).
- **La ficha se lee una vez.** Si la entidad cambia solo el detalle —o cambia el objeto de compra
  de una necesidad ya leída—, el CPC guardado se queda como estaba hasta que alguien ejecute
  `scripts/rellenar_items_cpc.py`. Es el precio de no gastar la cuota releyendo fichas conocidas.
- **`scripts/verificar_exportacion.py`** sigue comprobando el número de columnas con un umbral
  (`> 10`): la columna nueva no lo rompe, pero conviene revisarlo cuando se toque la exportación.
- **La lista de CPC no dispara ingesta**, a diferencia de las palabras clave: si alguien espera que
  añadir un término traiga datos nuevos, no los traerá. Lo que trae lo trae el ciclo de siempre, y
  el término solo acota lo que ya está descargado. Está explicado en la pantalla y en la ruta.

## 9. Riesgos abiertos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| El relleno de fichas compite por la cuota con la ingesta | Cuota propia y bloqueo propio; el relleno va después y no puede tumbar el ciclo |
| Un cambio de formato en la ficha deja de dar ítems | El analizador devuelve vacío en lugar de fallar, y eso **marca** la ficha como leída: hay que vigilar que `sin_items` no suba de golpe (se registra en cada tanda) |
| La columna `items` engorda la respuesta de la tabla | Medido: ~5 ítems de media por necesidad y 25 filas por página. Si algún día molesta, se puede servir solo en el detalle |
| Un `429` sostenido durante el relleno | El enfriamiento es global al proceso y el presupuesto por ciclo acota lo que se pide |

## 10. Aprobación (QA + Revisor)

Pendiente de la revisión de código y de la comprobación visual en el navegador con una empresa
temporal.
