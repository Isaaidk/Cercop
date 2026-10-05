# Fase 4.1 — Exportación fiel, columnas elegidas y panel plegable

> Incremento sobre F4. Cierra tres encargos del cliente sobre el panel ya en uso.

## 1. Objetivo

Que el Excel lleve **lo que se está viendo** y **lo que la empresa decide**, que se pueda saber de
antemano dónde van a caer esos datos dentro de su plantilla, y que el panel deje sitio a la tabla
cuando molesta. Además, que los números de las pestañas digan lo suyo y no lo de la pestaña vecina.

## 2. Alcance

**Incluido**

- La exportación respeta los filtros de la pantalla (antes descargaba el histórico entero).
- Selección de columnas **por empresa**, guardada en el servidor y editable en la pestaña Plantilla.
- Informe de la plantilla: a qué hoja va cada familia, dónde se reconocen los títulos y qué columnas
  se van a rellenar.
- Panel de filtros plegable en escritorio, con la preferencia recordada.
- Contador propio de cada pestaña de familia, sin contaminarse al navegar.

**Excluido**

- Unificar los filtros de la pestaña «Ofertas» con los del panel (la tabla que muestra sigue teniendo
  sus propios criterios).
- Exportación asíncrona y proceso `worker`.
- El sistema legado (`/main.py` y `/Consultoria/`).

## 3. Implementaciones realizadas

| Componente | Archivo / símbolo | Qué hace |
|---|---|---|
| Descarga con filtros | `frontend/src/api/endpoints.js` (`exportarRegistros`) | Envía los criterios envueltos en `{ parametros }`, que es lo que espera `http.descargar`. |
| Columnas elegidas (API) | `aplicacion/casos_uso/exportar_registros.py` (`GRUPOS_DE_COLUMNAS`, `revisar_columnas`, `columnas_del_libro(..., elegidas=)`) | Catálogo de columnas exportables, validación de claves y filtrado del archivo. |
| Persistencia | `alembic/versions/0011_columnas_exportacion.py`, `aplicacion/puertos/exportacion.py`, `salida/bd/columnas.py` | Una fila por empresa (`ON CONFLICT`), RLS forzado, `CAST(:columnas AS text[])`. |
| Casos de uso | `aplicacion/casos_uso/gestionar_columnas.py` | Consultar (cualquier rol) y guardar (administrativo, con validación). |
| Rutas | `routers/plantilla.py` (`GET /v1/plantilla`, `PUT /v1/plantilla/columnas`, `GET /v1/plantilla/analisis`) | Catálogo y selección en la consulta; análisis a petición. |
| Exportación | `routers/busqueda.py` (`_columnas_elegidas`) | Lee la selección del negocio **sin poder fallar**: si no se puede leer, se exporta con todas. |
| Informe de la plantilla | `aplicacion/casos_uso/analizar_plantilla.py`, `frontend/src/components/AnalisisPlantilla.vue` | Reutiliza el mismo código que rellena la plantilla para decir qué haría. |
| Lectura compartida | `aplicacion/casos_uso/gestionar_plantilla.py` (`leer_contenido`) | Una sola lectura de la plantilla para la exportación y para el informe. |
| Totales por familia | `salida/bd/consultas.py` (`por_fuente_sin_familia`), `casos_uso/buscar_registros.py` (`_totales_por_categoria`) | Conteo por fuente con la familia **excluida**, traducido a `por_categoria`. |
| Panel plegable | `frontend/src/components/VistaPanel.vue`, `BarraSuperior.vue`, `composables/useEsMovil.js` | Un botón gobierna el cajón en móvil y la columna en escritorio; la preferencia se recuerda. |
| Interfaz de columnas | `frontend/src/components/ColumnasExcel.vue` | Casillas por grupo, «Marcar todas» y guardado con aviso. |

## 4. Decisiones tomadas y justificación

- **La selección vive en su propia tabla** (`exportacion_columnas`) y no en `plantilla_excel`: una
  empresa sin plantilla también quiere acortar sus columnas, y atar una cosa a la otra obligaría a
  subir un `.xlsx` para poder elegir.
- **La lista vacía significa «todas».** Es lo que permite que una columna nueva del catálogo aparezca
  sola, sin tocar la selección de nadie, y lo que hace que el estado de partida no dependa del
  catálogo del día en que se guardó.
- **Los totales por familia se calculan ignorando la familia filtrada.** Es la única forma de que el
  número de «Ínfimas cuantías» no cambie al abrir «Ofertas»: la consulta de la tabla lleva la familia
  puesta porque se está mirando una sola.
- **No se adivina por qué la plantilla no encaja: se informa.** La heurística de encabezados se deja
  como estaba —elegir la fila con más títulos reconocidos es lo que hace que una plantilla con dos
  tablas superpuestas reciba los datos bajo la tabla completa— y se añade un informe que dice, hoja
  por hoja, qué se reconoce y dónde entrarían los datos.
- **Un solo botón para los dos anchos.** En móvil abre el cajón (que no se recuerda: tapar el
  contenido es una acción del momento) y en escritorio esconde la columna (que sí se recuerda).
- **La preferencia de plegado se guarda en el navegador**, no en el servidor: es una comodidad de
  quien mira, no una decisión de la empresa.

## 5. Casos de uso y requisitos cubiertos

| ID | Descripción | Estado |
|---|---|---|
| CU-07 | Exportar a Excel | Cubierto (filtros + columnas) |
| CU-09 | Descargar con la plantilla de la empresa | Cubierto (y ahora diagnosticable) |
| RF-05 | Filtros de la tabla, gráficas y exportación | Reforzado |
| RNF-04 | El caché no rompe la consulta | Se extiende a la selección de columnas |

## 6. Pruebas ejecutadas y resultado real

| Prueba | Comando | Resultado |
|---|---|---|
| Estilo y formato | `ruff check .` · `ruff format --check .` | `All checks passed!` · `186 files already formatted` |
| Tipos | `mypy` | `Success: no issues found in 172 source files` |
| Unidad | `pytest pruebas/unidad` | **573 passed** (5 nuevas de totales por familia, 13 de columnas y análisis) |
| Integración | `$env:PRUEBAS_INTEGRACION='1'; pytest pruebas/integracion/test_columnas_exportacion.py` | **6 passed** (arreglo `text[]`, `ON CONFLICT`, aislamiento, `actualizado_en`) |
| Exportación de punta a punta | `python scripts/verificar_exportacion.py` | `Todas las comprobaciones pasaron` |
| Compilación del panel | `npm run build` | `✓ built in 16.07s` |
| Navegador | sesión temporal creada y borrada al terminar | Ver §7 |

## 7. Evidencia de aceptación

```
# Filtros en la exportación (antes: sin querystring)
GET /v1/registros/exportacion?modo=cualquiera&orden=recientes&categoria=infimas
GET /v1/registros/exportacion?modo=cualquiera&orden=recientes&provincia=PICHINCHA&categoria=infimas
  -> 519 filas, y el aviso del panel dice «Se descargaron 519 contrataciones»

# Totales por familia con los mismos filtros, sin que la pestaña los cambie
/v1/estadisticas                 -> por_categoria [infimas 2210, ofertas 53]
/v1/estadisticas?categoria=ofertas -> por_categoria [infimas 2210, ofertas 53]
  -> en el navegador: pestañas «Ínfimas cuantías 2.210» y «Ofertas 53»,
     y siguen iguales después de abrir Ofertas y volver

# Con el filtro de provincia aplicado
2.210 / 53  ->  519 / 11   (y la exportación lleva provincia=PICHINCHA)

# Panel plegable
inicial:  aria-label="Ocultar los filtros"  ·  columna visible
al pulsar: --sin-filtros  ·  display:none  ·  localStorage=0
tras recargar: sigue oculto  ·  aria-label="Mostrar los filtros"

# Columnas elegidas (empresa de prueba, plantilla sintética INFIMAS/Ofertas)
GET /v1/plantilla -> columnas_elegidas: 15 claves (sin objeto_compra)
cabecera del libro exportado: Código, Tipo de compra, Razón social, Responsable…, Provincia,
  Cantón, Estado, Fecha de publicación, Límite de proformas, Días para proforma, Fuente, …
¿aparece «Objeto de compra»? -> False
con plantilla: la fila de títulos de la empresa queda en su sitio (fila 3), los datos entran
  desde la fila 4 y «Objeto de compra» —desmarcada— se queda vacía

# Informe de la plantilla
«Los datos de ínfimas cuantías entran en la hoja INFIMAS y los de ofertas en Ofertas.»
INFIMAS · Ínfimas cuantías · títulos en la fila 3 · datos desde la 4 · Código, Tipo de compra,
  Objeto de compra, Provincia · cantón
Ofertas · Ofertas · títulos en la fila 1 · datos desde la 2 · Código, Razón social, Estado
```

## 8. Deuda técnica y pendientes

- El contador de la pestaña «Ofertas» sale de los filtros del panel, mientras que la tabla de esa
  pestaña usa sus propios criterios: los dos números pueden no coincidir. Se ve en la pantalla y
  queda como está hasta que se unifiquen los filtros de esa pestaña.
- Con una selección de columnas activa **no** se añaden los campos nuevos que la fuente publique
  (el comportamiento automático sigue vigente solo sin selección). Es deliberado —un archivo fijo es
  lo que se pidió— pero conviene revisar el catálogo cuando la fuente añada campos útiles.
- `GET /v1/plantilla/analisis` abre el libro entero; con una plantilla de varios megas tarda. Se pide
  a propósito y no al abrir la pestaña.

## 9. Riesgos abiertos y mitigaciones

- **Plantillas con dos tablas superpuestas** (es el caso de la plantilla real de «Plataforma»: una
  tabla en la fila 4 y otra en la 7): el sistema escribe bajo la que reconoce **más títulos**, que es
  la más completa. El informe lo dice con nombres y filas, así que la decisión deja de ser invisible.
- **Techo de conexiones de Redis (30)** observado otra vez durante la verificación: al acumular
  sesiones, paneles y procesos de prueba, el caché dejó de aceptar conexiones y el panel se quedó
  sin datos. Se libera reiniciando el proceso del API. Refuerza el pendiente de F4 de usar un Redis
  local en el despliegue.
- La exportación sigue siendo **síncrona** (openpyxl bloquea el bucle) y con tope de 20.000 filas.

## 10. Aprobación

| Rol | Nombre | Fecha | Veredicto |
|---|---|---|---|
| Ingeniero QA | — | — | Pendiente de firma |
| Revisor de Código | — | — | Pendiente de firma |
