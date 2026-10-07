# Fase 4.15 — Los filtros de la pestaña de ofertas

> Documento de fase según la plantilla de `documentacion.md` § 9.2.

**Fecha:** 2026-10-06 · **Estado:** implementado y verificado contra la API y el panel.

## 1. Objetivo

**Que buscar ofertas se pueda acotar como se acota en ínfimas cuantías.** La petición original era
«actualizar los filtros para ofertas, que funcionen similar a los de ínfimas cuantías», y tenía dos
síntomas detrás: el panel de ofertas solo ofrecía palabras clave en texto libre, entidad, tipo,
código, fechas y fuente; el de ínfimas ofrece además **provincia**, **estado**, **CPC** y
**descripción del producto**. Quien vigilaba un producto con los mismos criterios tenía que hacerlo
dos veces, y de dos maneras.

## 2. Alcance

**Incluido**

- **Provincias** con casillas y buscador, sumables entre sí, con la misma lógica que el mapa (el
  filtro es la lista de provincias y la lista vacía no filtra).
- Las mismas casillas **en el panel lateral**, en lugar del desplegable que añadía provincias y las
  fichas que las quitaban, conservando la lógica del mapa: los dos caminos escriben la misma lista.
- **Descripción del producto** y **clasificación CPC** como listas de términos con fichas, igual que
  en el panel lateral.
- **Un solo interruptor de modo** —«todas» o «cualquiera»— que gobierna los tres campos de texto, con
  «cualquiera» por defecto, como en el de ínfimas.
- **Estado de la contratación**, desactivado y explicado cuando la fuente elegida no lo publica.
- Dos componentes reutilizables (`CampoDeTerminos`, `SelectorProvincias`) y dos reglas compartidas
  (`claveDeTermino`, `nombreParaApi`), para no tener dos versiones de lo mismo.

**Excluido (deliberadamente)**

- **«Solo con plazo abierto».** En las ínfimas filtra por la fecha límite de proformas, que la fuente
  de ofertas **no publica**: el control dejaría la lista vacía siempre. Es el mismo caso que el
  estado, pero aquí no hay forma de que sirva cambiando de fuente, así que no se pone.
- **El orden** (más recientes / más antiguos). La pestaña de ofertas no lo tenía y no se pidió; el
  listado ya viene del más reciente al más antiguo.
- **La familia** (ínfimas / ofertas / todas). En esta pestaña la familia la fija la fuente, que es
  como está pensada: es el listado de procesos publicados.

## 3. Implementaciones realizadas

| Qué | Dónde |
|---|---|
| El campo de términos reutilizable: cuadro, botón, fichas y sus avisos | `frontend/src/components/CampoDeTerminos.vue` |
| Las provincias como casillas, con buscador y fichas | `frontend/src/components/SelectorProvincias.vue` |
| La clave con la que se comparan dos términos y su longitud mínima | `frontend/src/utils/terminos.js` |
| El nombre de provincia que espera la API | `frontend/src/utils/provincias.js` (`nombreParaApi`) |
| El almacén del panel lateral, que pasa a usar las dos reglas compartidas | `frontend/src/stores/filtros.js` |
| Los criterios nuevos, el modo, el resumen de parámetros y el formulario | `frontend/src/components/OfertasTab.vue` |
| Las casillas en el panel lateral, en lugar del desplegable y las fichas | `frontend/src/components/PanelFiltros.vue` |
| La acción que fija la lista de provincias completa | `frontend/src/stores/filtros.js` (`fijarProvincias`) |

## 4. Decisiones tomadas y justificación

### 4.1 Las reglas se comparten; el estado, no

El estado de los filtros vive en sitios distintos a propósito: el del panel lateral es el **almacén
compartido** —lo leen la tabla, las gráficas y el mapa, y las palabras clave son **suscripciones** que
el worker va a buscar a la fuente— y el de la pestaña de ofertas es **local**, porque ahí se busca, no
se suscribe, y se aplica con su propio botón. Un solo almacén para las dos pantallas obligaría a que
los criterios de una viajaran en la caché de la otra.

Lo que **no** puede duplicarse es la regla, y estaba duplicada:

- Con qué se comparan dos términos para no repetir (sin mayúsculas ni tildes) y cuánto tienen que
  medir. Ahora es `utils/terminos.js`, y el almacén lateral lo importa en lugar de tener su copia.
- Cómo se convierte una provincia en el valor que espera la API. Ahora es `nombreParaApi` en
  `utils/provincias.js`.

Y la **presentación** del campo de términos —el cuadro, el botón, las fichas, los avisos de «corta» y
«repetida»— se extrajo a `CampoDeTerminos.vue`, de modo que añadirla a la pestaña de ofertas no fue
escribir otra vez esas cuatro cosas.

### 4.2 Casillas para elegir provincias

El panel lateral usaba un desplegable que añadía una provincia y fichas que la quitaban. Funciona,
pero obliga a abrirlo una vez por provincia y no deja ver la selección entera de golpe. Se sustituye
por **casillas con buscador** en las dos pantallas, con el mismo componente: «¿en qué provincias?» se
responde mirando, y con veinticuatro opciones el buscador evita recorrer la lista.

La lógica es la misma que la del mapa en los dos casos: el filtro es la **lista** de provincias, la
lista vacía no filtra, y elegir dos **suma** —no exige que estén las dos—. Se conserva así para que el
mapa y las casillas sigan escribiendo el mismo criterio, que es lo que permite tenerlos juntos
(§ 6.2).

### 4.3 El modo, un solo interruptor para tres campos

Las palabras clave, el CPC y la descripción comparten el modo porque la pregunta es la misma: cómo se
combinan entre sí varias palabras **de la misma lista**. Con «cualquiera» los resultados de cada
término se suman; con «todas» se exigen todos. Repetir el control tres veces sería la forma más fácil
de que la pantalla dijera una cosa mientras la consulta hace otra.

Medido con datos reales en la pestaña, con descripción del producto:

| Búsqueda | Filas |
|---|---|
| `medicamentos` | 195 |
| `medicamentos` + `hospital`, modo **cualquiera** | **3.293** |
| `medicamentos` + `hospital`, modo **todas** | **74** |

Los tres números dicen lo que tienen que decir: la unión es mayor que cada término por separado y la
intersección es menor. Es la comprobación que responde a la queja «al agregar distintas palabras clave
no funciona, solo deja filtrar por una sola».

### 4.4 El estado se apaga cuando la fuente no lo publica

Los procesos de datos abiertos no traen estado —**se comprobó**: de las 104.316 filas de OCDS ninguna
lo tiene y el filtro con un estado elegido devuelve **cero**—, mientras que la fuente de las ínfimas
sí lo publica. Ofrecer un control que vacía la tabla sin decir por qué se lee como que la búsqueda
está rota.

Por eso el desplegable se **desactiva** y se explica —«cambia la fuente a NCO para usarlo»— en cuanto
la fuente elegida es la de datos abiertos, y el parámetro se ignora al consultar aunque quedara
puesto. Es la misma decisión que ya estaba tomada con la columna «Estado del proceso» de la tabla: no
se enseña una columna vacía; se dice por qué no está.

### 4.6 Las casillas también en el panel lateral, sin tocar el mapa

El panel lateral tenía un desplegable que **añadía** una provincia y fichas que la quitaban. Con las
casillas, marcar y desmarcar escribe la **lista completa**, así que el almacén necesita una acción que
fije la lista (`fijarProvincias`) en lugar de alternar una sola. Se ordena ahí y no en el componente
para que el orden en que se marcaron las casillas no cree dos formas de la misma elección.

Lo que **no** cambia es el mapa: su clic sigue llamando a `alternarProvincia` —suma o quita esa
provincia—, y el componente de casillas refleja la lista en cuanto cambia, venga de donde venga. Los
dos caminos siguen escribiendo el mismo filtro, que es lo que permite tenerlos juntos.

### 4.7 Dos clics seguidos se pisaban

El componente calculaba la lista nueva a partir de su **propiedad**, que solo cambia cuando Vue vuelve
a pintarlo. Marcar Azuay y Bolívar de corrido hacía que el segundo clic leyera la lista vieja y
sobreescribiera el primero: quedaba una sola provincia marcada. Se descubrió verificándolo —dos clics
en el mismo instante, una sola marca— y se arregló con una copia local de la selección, sincronizada
con la propiedad mediante un `watch` para seguir viendo lo que escribe el mapa.

### 4.8 El borrador y lo aplicado no comparten los arreglos
Los criterios nuevos son listas, y el código copiaba el borrador con `{...criterios}`. Con arreglos,
esa copia comparte la **referencia**: añadir una ficha al borrador habría cambiado también la consulta
ya hecha, y el botón de aplicar habría dicho que no hay cambios pendientes. Ahora hay una función
`copiarCriterios` que clona las listas, y es la que se usa al aplicar y al construir el estado
inicial.

## 5. Casos de uso y requisitos cubiertos

- **Vigilar un producto y ver también los procesos publicados** con los mismos criterios: descripción
  del producto, CPC, provincia y estado, sin cambiar de pestaña ni de manera de buscar.
- **Acotar por varias provincias**: se marcan las que se quieran y se suman.
- **Elegir cómo se combinan los términos** sin adivinar qué hace el servidor.
- **Buscar por un código de CPC** pegado desde una ficha, y por el nombre estándar.

## 6. Verificación

### 6.1 Contra la API, mirando lo que se envía

Con el panel en marcha y una empresa temporal —creada y borrada para esta comprobación—, cada
búsqueda se comprobó por la petición que sale y por el total que vuelve:

| Acción | Petición | Filas |
|---|---|---|
| Sin filtros (fuente OCDS) | `?tamano=25&pagina=1&fuente=OCDS` | 104.316 |
| Marcar **Galápagos** | `…&provincia=GALAPAGOS` | **303** |
| Añadir descripción `mantenimiento` | `…&descripcion=mantenimiento&modo=cualquiera&provincia=GALAPAGOS` | **55** |
| Añadir CPC `871410032` | `…&cpc=871410032&modo=cualquiera&…` | 0 (la combinación no existe) |
| Dos descripciones, «cualquiera» | `…&descripcion=medicamentos&descripcion=hospital&modo=cualquiera` | **3.293** |
| Las mismas dos, «todas» | `…&modo=todas` | **74** |
| Limpiar filtros | `?tamano=25&pagina=1&fuente=OCDS` | 104.316 |

Los parámetros llegan **con el nombre y la forma** que espera el servidor: la provincia en mayúsculas
como la publica la fuente, los términos repetidos (`descripcion=…&descripcion=…`) y un solo `modo`.

### 6.2 El panel lateral y el mapa escriben el mismo filtro

Con la empresa temporal, en el panel de ínfimas:

| Acción | Estado de las casillas | Petición |
|---|---|---|
| Marcar **Azuay** y **Bolívar** | las dos marcadas, con sus fichas | `…&provincia=AZUAY&provincia=BOLIVAR…` |
| Pulsar **Pastaza** en el mapa | las tres marcadas | `…&provincia=AZUAY&provincia=BOLIVAR&provincia=PASTAZA…` |
| «Desmarcar» una ficha | desaparece de la lista | se vuelve a pedir sin ella |

La segunda fila es la que importa: pulsar el mapa **añadió** la provincia y las casillas lo reflejaron
sin que nadie las tocara, así que los dos caminos siguen siendo el mismo filtro. El clic del mapa
suma —antes había un gesto doble para sumar y se quitó, porque un navegador no avisa de que un clic es
el primero de un doble y el mapa se sentía lento—.

### 6.3 El estado, medido antes de decidir

Con la fuente de datos abiertos, elegir el único estado del catálogo —«En Curso»— devuelve **cero**
filas. Es lo que justifica apagarlo (§ 4.4). Comprobado también que al cambiar la fuente a NCO el
control se habilita y la nota desaparece.

### 6.4 Comprobaciones automáticas

- `ruff check` → `All checks passed` · `ruff format --check` → 236 archivos
- `mypy` → `Success: no issues found in 211 source files`
- `pytest pruebas/unidad` → **772 pasan**
- `vite build` → 95 módulos

No hay pruebas de unidad del panel —el proyecto no tiene marco para él y lo verifica con guiones y en
el navegador—, así que lo que fija este cambio son las dos reglas compartidas (que ahora tienen un
solo sitio) y la comprobación del § 6.1.

### 6.5 Lo que no se ha comprobado igual que lo haría una persona

La pestaña del navegador desde la que se verificó **no repinta**, así que la comprobación se hizo
conduciendo la aplicación y leyendo el DOM y las peticiones. Dos consecuencias:

- **No hay captura de pantalla**: el aspecto del formulario —las casillas, las fichas, el ancho en
  móvil— queda por ver a ojo del usuario.
- Pulsar un botón de envío con `elemento.click()` desde la consola **no envía el formulario** en esta
  página (ni en éste ni en el de acceso, que funciona a diario), así que se usó `form.requestSubmit()`.
  En un navegador de verdad el botón se pulsa con el ratón y no hay nada que hacer.

## 7. Evidencia de aceptación

- Los cuatro criterios nuevos viajan en la petición con su nombre correcto y el total responde a lo
  que se pidió (§ 6.1).
- «cualquiera» suma (3.293) y «todas» exige (74) sobre las mismas dos palabras (§ 4.3).
- El estado está apagado con la fuente que no lo publica, y se enciende al cambiar de fuente (§ 6.2).
- 772 pruebas unitarias, `ruff` y `mypy` limpios, y el panel compila.

## 8. Deuda técnica y pendientes

1. **El panel lateral no reutiliza `CampoDeTerminos`.** Sus tres campos (palabras clave, CPC y
   descripción) siguen con su propia copia de la interacción, atada al almacén. Unificarlos exige
   pasarles el estado por propiedades, y no se hizo para no tocar la pantalla que más se usa en la
   misma tanda.
2. **No hay «orden» en la pestaña de ofertas** (más recientes / más antiguos), y el servidor ya acepta
   ese parámetro. El listado sale del más reciente al más antiguo, que es lo que se pide siempre.
3. Las pruebas de carga con k6 siguen pendientes.

## 9. Riesgos abiertos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Las dos pantallas se separan y aceptan cosas distintas | Las reglas —longitud mínima, comparación sin tildes, nombre de provincia— viven en un solo archivo y las dos las importan |
| Un filtro nuevo se pone en una pantalla y no en la otra | Los dos formularios tienen ahora los mismos criterios salvo los que no tienen datos en la fuente de ofertas, y se dice cuáles y por qué |
| El borrador y lo aplicado comparten las listas | `copiarCriterios` las clona; es el fallo clásico de los arreglos en un estado reactivo |

## 10. Aprobación

| Campo | Valor |
|---|---|
| Estado | **Completada** — 2026-10-06 |
| Migraciones | ninguna (el servidor ya aceptaba todos los criterios) |
| Comprobaciones | ruff, ruff format, mypy, 772 pruebas unitarias, el panel con una empresa temporal y las peticiones del § 6.1 |
| Pendiente del usuario | mirar el formulario a ojo (§ 6.4) |
