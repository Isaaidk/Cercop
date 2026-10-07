# Ventana de descarga: los últimos tres meses

> Pedido el 2026-10-06: «agrega una restricción para que no se puedan hacer excels o descargar
> excels de las ofertas e ínfimas que pasen más de 3 meses, para alivianar la carga».

## 1. Objetivo

Que la descarga a Excel —la operación más cara del sistema y la única que no se puede paginar— no
lea el histórico entero. Cubre como mucho los **últimos tres meses** de fecha de publicación, tanto
para ínfimas como para ofertas y para la descarga de las dos familias.

## 2. Alcance

**Incluido**

- La regla, en el dominio (`dominio/exportacion.py`), aplicada en el caso de uso antes de consultar.
- El rechazo con el motivo y con la fecha desde la que sí se puede.
- El panel: cuando la descarga se sale de la ventana, el botón **pone el periodo y descarga** en un
  solo gesto, y una pista explica por qué.

**Excluido**

- **La consulta en pantalla no cambia.** La tabla, las gráficas y el mapa siguen llegando a todo el
  histórico: están paginados y su coste por página no depende del rango.
- **No hay excepción por rol.** Ni el superadministrador descarga más atrás: la ventana protege al
  servidor, no a los datos.
- **No se recorta nada.** Ver § 4.1.

## 3. Implementaciones realizadas

| Componente | Archivo / símbolo | Qué hace |
|---|---|---|
| Aritmética de meses | `dominio/plazos.py` · `sumar_meses` | Meses de calendario con ajuste de día, positivos y negativos. Estaba en `acceso.py` como privada y ahora la comparten los plazos de las vistas y la ventana. |
| La regla | `dominio/exportacion.py` · `MESES_EXPORTABLES`, `inicio_exportable`, `revisar_ventana` | Calcula el límite en la zona del negocio y rechaza lo que se salga. |
| Caso de uso | `exportar_registros.py` · `exportar` | Comprueba la ventana **antes** de tocar la base. |
| Enrutador | `routers/busqueda.py` | Documenta el límite en la descripción del endpoint. |
| Panel | `utils/exportacion.js`, `TablaRegistros.vue` | Espejo de la regla y botón «Descargar los últimos 3 meses». |
| Verificación | `scripts/verificar_exportacion.py` (§ 7b) | Comprueba las tres fronteras contra la API en marcha. |

## 4. Decisiones tomadas y justificación

### 4.1 Rechazar, no recortar

Recortar en silencio rompería la propiedad que sostiene toda la exportación: **el archivo y la tabla
no pueden discrepar**. Si el archivo trajera menos filas de las que se ven —sin decirlo—, quien lo
recibe no tendría forma de saber que le falta la mitad. Así que la petición se rechaza con el motivo
y con la fecha exacta desde la que sí se puede, y el panel ofrece hacerlo en un clic.

### 4.2 Tres meses, en meses de calendario y en la zona del negocio

Ni 90 días ni UTC:
- **Meses de calendario**, porque «tres meses» es lo que se dice y lo que se espera; 90 días
  dejaría fuera o dentro un día distinto según el mes. Con el ajuste de día al último del mes: tres
  meses atrás desde el 31 de mayo no es un 31 de febrero, es el 28 (o el 29 en bisiesto).
- **En la zona del negocio**, porque el panel filtra por días naturales de Ecuador: un límite
  calculado en UTC dejaría fuera el primer día de la ventana a quien pidiera la descarga de noche.

### 4.3 Sin fecha inicial también se rechaza

Sin `desde`, la consulta abarcaría el histórico entero: es exactamente el caso que la ventana viene
a evitar. El rechazo dice qué fecha hay que poner, y el panel la pone él mismo si se lo piden.

### 4.4 Se comprueba antes de consultar

No es un detalle de estilo: si la consulta cara se lanzara primero, la ventana no ahorraría lo que
viene a ahorrar. Hay una prueba que lo fija con un repositorio que no debe ser llamado.

### 4.5 La copia del panel es un espejo, no la barrera

`utils/exportacion.js` replica la misma cuenta para no ofrecer un botón condenado a un rechazo, pero
**quien manda es el servidor**. Si las dos cuentas se separaran, el panel ofrecería un botón que
falla; se comprobó que hoy coinciden al día: el panel calcula `2026-07-06` y el servidor responde
`2026-07-06`.

### 4.6 El botón pone el periodo y descarga

Es la excepción deliberada a «la descarga lleva exactamente los filtros de la pantalla»: cuando el
rango se sale de la ventana, el botón **fija** el periodo descargable (del límite a hoy) y descarga.
Fija los dos extremos y no solo `desde` porque un `hasta` anterior al nuevo `desde` haría que la
petición se rechazara por dos fechas que se contradicen. Después de aplicar, la tabla muestra el
mismo periodo que el archivo: la descarga sigue siendo fiel a la vista.

### 4.7 La verificación manual también se quedó vieja, y eso se vio al ejecutarla

`scripts/verificar_exportacion.py` exportaba **sin fecha** en tres de sus apartados, así que después
del cambio daba por rotas cosas que estaban bien. Se corrigió —los tres apartados piden el periodo
con `inicio_exportable()`, la misma función que usa el servidor— y se añadió el apartado **7b** con
las tres fronteras. Es la segunda vez en el proyecto que un guion de verificación se queda atrás en
silencio: la lección es ejecutarlos **al cerrar cualquier cambio de contrato observable**.

## 5. Casos de uso y requisitos cubiertos

| ID | Descripción | Estado |
|---|---|---|
| F4.1 | La descarga respeta los filtros de la pantalla | **Se mantiene**: el archivo sigue coincidiendo con la tabla |
| — | La descarga no lee el histórico entero | Cubierto |
| RNF (carga) | Alivianar la base en la operación más cara | Cubierto por diseño |

## 6. Pruebas ejecutadas y resultado real

| Prueba | Comando | Resultado |
|---|---|---|
| Unidad | `pytest pruebas\unidad` | **851 passed** (16 nuevas de la ventana) |
| Estilo y tipos | `ruff check src pruebas scripts` · `ruff format --check` · `mypy` | Limpio (225 y 223 archivos) |
| Compilación | `npx vite build --outDir $env:TEMP\...` | 97 módulos, correcto |
| De punta a punta | `python scripts\verificar_exportacion.py` | **Todas las comprobaciones pasaron** (salida 0) |

## 7. Evidencia de aceptación

```
$ .\.venv\Scripts\python.exe scripts\verificar_exportacion.py
==================================================================
7b. La descarga se limita a los últimos meses
==================================================================
  OK  sin fecha inicial -> 422
  OK  el mensaje dice desde cuándo se puede: 2026-07-06
  OK  con 2026-07-05 -> 422
  OK  con 2026-07-06 -> 200

Todas las comprobaciones pasaron.
```

Y el resto del guion sigue en verde: el archivo y la tabla cuadran (54 de 54), la hoja de criterios,
el semáforo de plazos, la familia sola, el archivo vacío, el lector que no exporta y la descarga sin
sesión.

En el navegador, la cuenta del panel da el mismo día que la del servidor:

```
hoy: 2026-10-06 · límite: 2026-07-06 · legible: «6 de julio de 2026»
en ventana en el límite: true · un día antes: false · sin fecha: false
```

## 8. Deuda técnica y pendientes

- **El mensaje del rechazo no está en el panel hasta que falla.** La pista explica el límite, pero si
  alguien llama a la API directamente verá el texto del servidor, que está bien escrito y es
  accionable. No hay nada que arreglar, y se deja anotado.
- **El tope de filas de la exportación** (`export_async_umbral_filas`) sigue siendo el otro límite:
  con tres meses de datos y muchos términos a la vez, se puede llegar a él. Los dos mensajes son
  distintos y dicen qué hacer, así que se distinguen bien.
- **No hay prueba automática de que el panel y el servidor coincidan en la fecha.** Se comprobó a
  mano (arriba). Un día que alguno de los dos cambie la cuenta, el síntoma sería un botón que falla;
  la prueba de integración del servidor sí lo cubre por su lado.

## 9. Riesgos abiertos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Un usuario necesita el histórico completo | La consulta en pantalla llega a todo y la exportación se acota por palabras clave, CPC o provincia dentro de la ventana |
| El recorte se cuela por descuido en el futuro | Hay pruebas que fijan el rechazo, no el recorte |
| Un guion de verificación se queda viejo otra vez | Se ejecutó y se corrigió en este cambio; el apartado 7b lo vigila |

## 10. Aprobación

| Rol | Nombre | Fecha | Veredicto |
|---|---|---|---|
| Ingeniero QA | — | 2026-10-06 | 851 de unidad y las tres fronteras comprobadas contra la API real |
| Revisor de Código | — | 2026-10-06 | El rechazo va antes de consultar; la copia del panel, documentada como espejo |
