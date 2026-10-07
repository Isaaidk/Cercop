# Fase 4.12 — Filtrar por la descripción del producto

> Documento de fase según la plantilla de `documentacion.md` § 9.2.

**Fecha:** 2026-10-06 · **Estado:** implementado y verificado contra la base real; la comprobación
visual en el navegador queda pendiente de una sesión con la que entrar.

## 1. Objetivo

**Que se pueda buscar por lo que se compra, y no por lo que se menciona.** El panel tenía dos formas
de escribir qué se busca —las palabras clave y el CPC— y ninguna respondía a la pregunta más directa:
«¿qué necesidades compran esto?». Las palabras clave buscan en **todo** el texto de la convocatoria
(el código, el objeto, la entidad, la provincia, el cantón y los tipos de proceso), así que quien
vigila «lavado» recibe desde un servicio de lavado de vehículos hasta una capacitación sobre
prevención de lavado de activos. El CPC acota por la clasificación normalizada del Estado, pero
depende de que la ficha publicada traiga la clasificación —y la mayoría del histórico no la tiene
todavía—.

Lo que faltaba era el criterio que el usuario escribe de forma natural: **una o varias palabras que
describen el producto**, buscadas solo en el **objeto de compra**.

## 2. Alcance

**Incluido**

- Un criterio nuevo `descripcion` en el dominio, con la misma semántica que las palabras clave
  —prefijo de palabra, modos «todas» y «cualquiera»— pero contra **un solo campo**.
- El parámetro repetible `descripcion` en los tres endpoints de datos (tabla, gráficas y
  exportación), que lo reciben por compartir `_filtros_compartidos`.
- Un índice de texto completo sobre la expresión normalizada de `objeto_compra`, creado en la
  migración `0020`.
- El campo en el panel, **debajo del CPC**, con sus fichas y su alta y baja de términos, y su parte
  en el almacén de filtros (huella del caché incluida).
- Catorce pruebas nuevas: cinco de la consulta, cuatro del valor de los filtros y cinco de la costura
  entre la URL y el dominio.

**Excluido (deliberadamente)**

- **Sacar el objeto de compra a una columna.** Es la alternativa que la fase 4.11 siguió para
  provincia y tipo de proceso, y aquí **no se puede pagar**: ver § 4.1.
- Un interruptor propio de «todas»/«cualquiera» para este campo. Comparte el de las palabras clave
  (§ 4.5).
- Buscar también en los ítems del CPC leídos de la ficha. El criterio del CPC ya cubre esa pregunta y
  sumarlos aquí mezclaría dos fuentes con coberturas muy distintas.

## 3. Implementaciones realizadas

| Qué | Dónde |
|---|---|
| El campo del criterio, su porqué y su entrada en la huella del caché | `dominio/busqueda.py` (`Filtros.descripcion`, `canonico`, `cacheable`) |
| El índice de la expresión normalizada del objeto (`ix_registro_objeto`) | `alembic/versions/0020_indice_descripcion.py` |
| La constante que la consulta usa, con el mismo texto que el índice | `salida/bd/consultas.py` (`INDICE_OBJETO`) |
| La condición, después del CPC y antes del texto libre | `salida/bd/consultas.py` (`_condiciones`) |
| El parámetro repetible en la API | `entrada/http/routers/busqueda.py` (`_filtros_compartidos`, `criterios`) |
| El estado, las altas y las bajas del borrador | `frontend/src/stores/filtros.js` |
| El campo, debajo del CPC | `frontend/src/components/GestorDescripcionProducto.vue`, colocado desde `PanelFiltros.vue` |
| Cinco pruebas: la condición, el modo, el vacío, la convivencia con «solo CPC» y la equivalencia con la migración | `pruebas/unidad/test_consultas_bd.py` |
| Cuatro pruebas: huella, orden, caché y resumen | `pruebas/unidad/test_busqueda.py` |
| Cinco pruebas de la costura: llega, sin parámetro no hay criterio, normalización con tildes, orden de palabras y que no se mezcle con las palabras clave | `pruebas/unidad/test_criterios_cpc.py` |
| La comprobación contra la base real, con su apartado 10 | `scripts/verificar_filtros.py` |
| La comprobación de que el criterio llega al Excel, con su apartado 3b | `scripts/verificar_exportacion.py` |
| El caso de medida con su plan | `scripts/medir_consultas.py` |

## 4. Decisiones tomadas y justificación

### 4.1 Un índice de expresión, y no una columna

La fase 4.11 sacó `provincia` y `tipo_proceso` a columnas y fue la decisión correcta: agrupar por una
expresión del `jsonb` obliga a descomprimir dos kilobytes por fila. Aquí se planteó lo mismo y se
descartó, con el motivo medido:

- Un `ADD COLUMN` con relleno **reescribe las 111.000 filas** y deja una versión muerta de cada una
  mientras tanto: es exactamente lo que dejó la tabla en 415 MB y llevó el disco al límite, hasta el
  punto de que `VACUUM FULL` falló con «No space left on device» (docs/18 § 8.1). No hay sitio para
  repetirlo.
- Y **no hace falta**. La lentitud de los repartos venía de leer `datos` para **contar**; aquí lo que
  se hace es **buscar**, y para buscar hay índice de texto completo. La expresión se indexa una vez
  —la migración tardó 44 s, `ANALYZE` incluido— y desde entonces la consulta no lee el `jsonb`: lo
  confirma el plan, `Bitmap Index Scan on ix_registro_objeto`.

El precio que sí se paga: el índice guarda una copia del texto del objeto y, cuando la ingesta
actualiza una fila, se reescribe su entrada. Es el mismo precio que ya pagaba `texto_busqueda`.

### 4.2 Solo el objeto de compra, y eso es todo el criterio

Se buscó la forma de medirlo, y las cifras lo enseñan mejor que la definición:

| Palabra | Por palabras clave (`termino`) | Por descripción (`descripcion`) |
|---|---|---|
| «descentralizado» (está en cientos de nombres de entidad) | 30.661 | **690** |
| «especialidades» | 1.506 | 285 |
| «chjimborazo» (un error de la fuente, en la provincia) | 40 | **0** |

«Chjimborazo» es el caso que mejor lo cuenta: la palabra **existe** en el texto de cuarenta
registros —la provincia viene mal escrita en el dato— y **no está en el objeto de compra de ninguno**,
y por eso la descripción devuelve cero. Ese cero es una propiedad, no un fallo: es el mismo cero que
se ve al buscar «hospital» y obtener las necesidades cuyo objeto *es* un hospital y no las que
mencionan hospital en el nombre de la entidad.

La comprobación que quedó escrita en `verificar_filtros.py` § 10 es la relación que tiene que
cumplirse siempre —**el objeto de compra forma parte del texto de búsqueda**, así que todo lo que
encuentre la descripción lo encuentran también las palabras clave— más el caso contrario: alguna de
las palabras de la entidad tiene que dar más por texto que por descripción. Si algún día el índice de
la descripción se construyera con otra columna o con otra normalización, esa prueba lo diría.

### 4.3 El índice va **sin tildes**, y por eso el término se normaliza al entrar

Esto se descubrió midiendo y merece quedar escrito, porque el síntoma es un cero silencioso.

El diccionario `simple` de PostgreSQL no quita tildes: indexa lo que le llega. Como `objeto_compra`
está en español, la expresión del índice pasa el texto por `translate(...)` para eliminar
áéíóúüñ —igual que `texto_busqueda`, que ya se normaliza en Python al escribirlo—. Del otro lado, la
consulta construye `to_tsquery('simple', 'computo:*')` con el término que le dan. Si alguien
escribiera «CÓMPUTO» y ese término llegara tal cual, el `tsquery` pediría `cómputo:*`, que **no**
existe en el índice, y la búsqueda devolvería cero filas sin ningún error. El usuario concluiría que
ese producto no está publicado.

Lo que lo evita es que el término se normalice **al entrar**: `criterios()` en el enrutador llama a
`normalizar_terminos(descripcion)`, que baja a minúsculas y quita tildes. Comprobado contra la base
real: «cómputo» → `computo` → **23** filas, y el `LIKE` equivalente sobre el objeto devuelve
exactamente 23; «ELECTROCARDIÓGRAFO» → 3 filas, las mismas que «ELECTROCARDIOGRAFO».

Ese detalle se llevó por delante la primera versión del arnés de verificación, y no por un fallo del
producto: `verificar_filtros.py` llama a la capa de consulta **sin pasar por el enrutador**, así que
mandaba el término con tilde. Ahora el arnés normaliza igual que la petición HTTP y lo dice en el
código, y hay una prueba en `test_criterios_cpc.py` que fija que la normalización **es** del
enrutador: si mañana alguien la quita de ahí, la prueba falla antes que la búsqueda.

### 4.4 La descripción sí entra en el caché

Las palabras clave libres no se guardan en el caché: quien teclea escribe cualquier cosa y el espacio
de combinaciones es ilimitado (por eso `texto` y `codigo` quedan fuera, y una búsqueda por NIC tampoco
se guarda). La descripción es otra cosa: es un conjunto pequeño de términos que una empresa vigila
siempre —los productos que le interesan— y que se repite en cada carga de la pantalla. Se guarda, y
`Filtros.cacheable` lo dice con el razonamiento al lado, igual que el CPC.

La huella incluye el campo (`canonico()` → `"dp"`), así que dos búsquedas con el mismo texto y
descripciones distintas **no** comparten entrada: sin eso, la primera que se calculara serviría la
respuesta de la otra y el panel enseñaría filas que no corresponden a los filtros de la pantalla.

### 4.5 El modo se comparte con las palabras clave

El interruptor «todas»/«cualquiera» del panel sirve a los dos criterios. Es una decisión de interfaz
con una razón de fondo: la pregunta es la misma —cómo se combinan entre sí varias palabras de la misma
lista— y un segundo control para el mismo valor es la forma más fácil de que la pantalla diga una cosa
mientras la consulta hace otra. En la API, en cambio, el modo es un parámetro compartido por todos los
criterios de texto, y eso no se cambió.

### 4.6 En el panel va debajo del CPC

Los tres campos donde se escribe qué se busca quedan juntos —palabras clave, CPC y descripción— y el
orden va de lo más ancho a lo más fino: las palabras clave miran toda la convocatoria, el CPC la
clasificación normalizada y la descripción solo el objeto de compra. Puesto arriba, el campo más
estrecho parecería el principal.

## 5. Casos de uso y requisitos cubiertos

- **«Quiero ver quién compra computadoras»**: `descripcion=computadoras` devuelve las necesidades
  cuyo objeto lo dice, sin las capacitaciones sobre computación ni las entidades cuyo nombre lo lleva.
- **«Quiero lo que sea de aseo»**: `descripcion=aseo&descripcion=limpieza&modo=cualquiera` suma las
  dos familias.
- **«Refinar lo que ya busco»**: la descripción se **suma** a los demás criterios con «y», así que se
  puede combinar con provincia, fechas, estado o plazo sin sustituir nada.
- **La exportación respeta el criterio**: el Excel lleva las mismas filas que la tabla para los mismos
  filtros (comprobado, § 6.4).

## 6. Verificación

### 6.1 Mediciones

`scripts/medir_consultas.py` con la **API y el worker parados** (la medida con el worker escribiendo no
sirve: el total se mueve y la varianza se come la diferencia):

| Caso | Mediana | Mín | Máx |
|---|---|---|---|
| Página sin filtros | 377 ms | 368 ms | 544 ms |
| Página con el orden por defecto | 375 ms | 369 ms | 409 ms |
| Provincia (el clic del mapa) | 360 ms | 355 ms | 440 ms |
| Código por fragmento (el NIC) | 353 ms | 349 ms | 357 ms |
| CPC por código | 348 ms | 341 ms | 352 ms |
| Palabra clave | 388 ms | 375 ms | 621 ms |
| **Descripción del producto** | **380 ms** | 371 ms | 395 ms |
| Rango de fechas | 335 ms | 333 ms | 337 ms |

La descripción **no añade coste a la página**: queda en el rango de los demás casos. Los ~350 ms que
comparten todos son el `count(*)` del total, que se ejecuta con el mismo `WHERE` que la página.

El plan lo confirma. El sondeo del conteo por descripción:

```
Finalize Aggregate  (cost=12912.95..12912.96 rows=1 width=8) (actual time=20.796..25.120 rows=1)
  ->  Parallel Bitmap Heap Scan on registro r
        ->  Bitmap Index Scan on ix_registro_objeto  (actual time=6.243..6.243 rows=10543)
Execution Time: 25.188 ms
```

Y el encadenado completo —tabla, gráficas y filtros— medido con la misma consulta: **~400 ms** por
pantalla, con el mismo suelo que las demás.

### 6.2 Comprobaciones automáticas

- `ruff check` → `All checks passed` · `ruff format --check` → 236 archivos
- `mypy` → `Success: no issues found in 211 source files`
- `pytest pruebas/unidad` → **766 pasan** (14 nuevas)
- `vite build` → 88 módulos, 2,6 s

Las catorce pruebas nuevas no comprueban un número, comprueban **acuerdos entre textos**: que la
constante que usa la consulta sea la misma expresión que crea la migración de la 0020 (si se separan,
el índice deja de usarse y la consulta vuelve a recorrer el histórico, sin ningún error), que la
condición no toque `texto_busqueda`, que el modo se aplique igual que en las palabras clave, que sin
descripción no se añada ninguna condición, que la descripción entre en el caché, y que el parámetro
llegue desde la URL y se normalice.

### 6.3 Verificación contra la base real

`scripts/verificar_filtros.py` § 10, con 111.117 registros:

```
palabra de muestra: «ELECTROCARDIÓGRAFO» (de un objeto de compra real)
descripcion=electrocardiografo -> 3
OK  una palabra que está en un objeto de compra encuentra algo (3)
OK  sin descripción la consulta es exactamente la misma que sin el criterio
OK  una descripción inexistente devuelve 0 (0)
«ELECTROCARDIÓGRAFO» -> 3 | «ELECTROCARDIOGRAFO» -> 3
OK  las dos formas acaban en el mismo término (electrocardiografo)
las dos -> todas=1 | cualquiera=3
OK  «todas» con dos palabras del mismo objeto encuentra al menos esa fila
«descentralizado» -> terminos=30661 | descripcion=690
«chjimborazo» -> terminos=40 | descripcion=0
OK  alguna palabra la encuentra la búsqueda por texto y la descripción no
OK  la descripción sí se guarda en el caché, al contrario que el texto libre
```

De paso, la sonda dejó un hallazgo que no es de esta fase pero conviene tener escrito: el tokenizador
de PostgreSQL **conserva el guion** en los tramos numéricos, así que `NIC-17681819000013-2026-00014`
se indexa como `nic`, `-17681819000013`, `-2026` y `-00014`. Un fragmento del código no lo encuentra
el índice de texto completo —y por eso el NIC tiene su propio filtro, que compara por `LIKE` contra
la columna del código y con índice de trigramas—.

### 6.4 La costura con el Excel

`scripts/verificar_exportacion.py` § 3b, con una empresa temporal y el término **«CÓMPUTO»**, con
tilde y en mayúsculas:

```
total con la descripción «CÓMPUTO»: 24
OK  la descripción encuentra algo (24)
OK  la tabla dice 24 y el archivo dice 24
```

Además de que el criterio llega a la exportación, esa comprobación prueba de paso la normalización
**a través de HTTP**, que es el camino que el arnés de la capa de consulta no recorre.

### 6.5 Lo que no se ha podido comprobar aquí

- **El campo en el navegador con una sesión abierta.** El panel compila y arranca, y el almacén y el
  componente están probados por sus reglas, pero ver el campo debajo del CPC, escribir una palabra y
  comprobar que las filas cambian necesita entrar con un usuario, y no hay credenciales en el
  repositorio. Queda como comprobación del usuario.

## 7. Evidencia de aceptación

- `alembic current` → `0020 (head)`; la migración tardó 44 s (índice más `ANALYZE`).
- El plan de la búsqueda por descripción es `Bitmap Index Scan on ix_registro_objeto` y el conteo
  tarda 25 ms.
- «cómputo» devuelve 23 filas, exactamente las mismas que el `LIKE` sobre el objeto: la normalización
  y el índice coinciden.
- «descentralizado» da 30.661 por texto y 690 por descripción, y «chjimborazo» 40 y 0.
- El Excel y la tabla coinciden en número de filas con el filtro puesto (24 = 24).
- 766 pruebas unitarias, `ruff` y `mypy` limpios.

## 8. Deuda técnica y pendientes

1. **El objeto de compra sigue en el `jsonb`.** Esta fase no lo movió a columna y no hace falta para
   buscar, pero cualquier operación que tenga que **leerlo de todas las filas** —por ejemplo una
   exportación con esa columna para todo el histórico— sigue pagando la descompresión. Cambiarlo
   exige el relleno que el disco no soporta hoy (docs/18 § 8.1).
2. **La tabla sigue sin compactar** y eso se nota en otros sitios: `catálogos` (los desplegables) se
   midió hoy en **14,6 s**, cuando la fase 4.11 lo dejó en 8,9 s. Es el mismo problema del espacio
   muerto —el recorrido completo lee 415 MB en lugar de 230—, no un efecto de este filtro. Sigue
   pendiente ampliar el disco y ejecutar `VACUUM FULL registro`.
3. **La comprobación visual en el navegador** (§ 6.5).
4. Las pruebas de carga con k6 siguen pendientes.

## 9. Riesgos abiertos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| La expresión del índice y la de la consulta se separan y el filtro vuelve a recorrer el histórico | Una prueba compara el texto de las dos; el plan se imprime en `medir_consultas.py`, no solo el tiempo |
| Un término con tilde entra sin normalizar y devuelve cero sin error | La normalización está en el enrutador, con prueba propia, y la verificación de la exportación la ejerce de punta a punta |
| El índice crece con cada actualización de fila | Es el mismo coste que `texto_busqueda` ya pagaba; pesa sobre el disco que está al límite |
| El usuario espera que la búsqueda traiga lo que menciona de pasada | El texto de ayuda del panel dice qué mira el campo, y el modo se explica con la lista puesta |

## 10. Aprobación

| Campo | Valor |
|---|---|
| Estado | **Completada** — 2026-10-06 |
| Migraciones | `0020 (head)` |
| Comprobaciones | ruff, ruff format, mypy, 766 pruebas unitarias, `verificar_filtros.py` § 10 y `verificar_exportacion.py` § 3b |
| Pendiente del usuario | abrir el panel y ver el campo bajo el CPC (§ 6.5); ampliar el disco para compactar (§ 8.2) |
