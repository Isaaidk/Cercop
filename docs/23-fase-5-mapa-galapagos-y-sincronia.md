# Fase 5 — El mapa: Galápagos donde toca y las cifras que cambian con la familia

| Campo | Valor |
|---|---|
| Estado | Cerrada |
| Fecha | 2026-10-06 |
| Depende de | F4 (pestañas por familia, mapa con selector) |
| Petición de origen | «el mapa no se actualiza sincrónicamente con el número de ofertas e ínfimas» · «que Galápagos salga más cerca de Ecuador» |

## 1. Objetivo

Que el mapa sirva para lo que se puso ahí —decidir **dónde** se está comprando— y no solo para
parecer un mapa. Dos cosas tienen que ser ciertas a la vez:

1. Que las cifras que pinta **dependan de la familia** que se esté mirando (ínfimas, ofertas o las
   dos), porque el selector de familia está justo encima y un selector que no cambia nada es peor
   que no tenerlo.
2. Que **Galápagos se reconozca**: que se vea la isla, que se entienda que está fuera del encuadre y
   que no se lleve por delante la escala del continente.

## 2. Alcance

**Incluido:** el reconocimiento de Galápagos en el archivo del mapa, la colocación de su recuadro a
partir de la geometría, la comprobación de que el reparto por provincia cambia con la familia, y el
texto de ayuda del mapa, que describía un gesto que ya no existe.

**Excluido:** cambiar la forma de pintar el mapa (sigue siendo un `svg` con dos grupos y sin
biblioteca de cartografía) y el mapa de calor por comuna o cantón.

## 3. Implementaciones realizadas

| Archivo / símbolo | Qué se hizo |
|---|---|
| `frontend/src/utils/mapa.js` · `ISLAS`, `proyectar` | La isla se reconoce comparando el nombre **normalizado**: el GeoJSON la llama `Galápagos` y el código comparaba contra `Galapagos` a secas |
| `frontend/src/utils/mapa.js` · `recuadroDeLasIslas` | El recuadro de puntos deja de estar en una posición escrita a mano: se calcula a partir del encuadre del continente y de la latitud real de los archivos |
| `frontend/src/components/VistaPanel.vue` | La ayuda del mapa decía «haz doble clic en varias para compararlas»; ese gesto se retiró hace tiempo y la ayuda hablaba de él |
| `backend/scripts/verificar_graficas.py` § 7 | Apartado nuevo: el reparto de ínfimas, el de ofertas y el de las dos, con la comprobación de que suman y de que no comparten ni una cifra |

### 3.1 El defecto, que no era el que parecía

El síntoma decía «el mapa no se actualiza». La medida dijo otra cosa: **el mapa estaba roto entero y
no se veía a simple vista**.

`ISLAS` valía `'Galapagos'` y el GeoJSON llama a la provincia `Galápagos`, con tilde. La comparación
—`nombre === ISLAS`— fallaba en silencio, así que la isla entraba en el encuadre **del continente**
con sus noventa y dos grados de longitud. Consecuencias, medidas en el navegador antes de tocar nada:

| Qué se medía | Antes | Después |
|---|---|---|
| Continente (píxeles del `viewBox`) | x 399 → 608, y 129 → 359 | x 102 → 518, y 12 → 468 |
| Tamaño del continente | 209 × 229 px | 416 × 456 px |
| Galápagos dibujada | x 12 → 110, y 121 → 231 | x 12 → 88, y 63 → 147 |
| Recuadro de puntos | x 8 → 116, **y 398 → 472** | x 6 → 94, y 57 → 153 |

Se lee mejor de lo que parece: el país entero cabía en una franja de doscientos píxeles a la derecha
—la escala la marcaba la isla, que está a mil kilómetros— y el recuadro de puntos, colocado en un
sitio fijo, quedaba **vacío** en la esquina opuesta a la isla que debía contener. Quien mirara el
mapa veía un Ecuador pequeño, una mancha sin etiqueta a la izquierda y un rectángulo punteado sin
nada dentro. «No se actualiza» era la lectura razonable de todo eso.

### 3.2 Dónde va el recuadro, y por qué no se escribe a mano

Se calcula con dos datos que salen de la propia geometría:

- **La altura**, con la latitud del centro de la isla medida en la proyección del continente: se
  pregunta en qué píxel cae el paralelo de Galápagos y el recuadro se centra ahí. La isla está a la
  altura del norte de Manabí, así que el recuadro queda **frente a la costa** que le corresponde —
  que es lo que pedía el «más cerca de Ecuador»— en lugar de en una punta.
- **El ancho**, con el hueco que deja el continente a su izquierda. Ecuador es más alto que ancho, así
  que el encuadre deja una banda de océano libre; el recuadro se recorta a lo que quepa para que
  nunca se monte encima del país. Escribirlo a mano garantizaba que un día el mapa cambiara de
  tamaño y el recuadro acabara sobre la costa, con las islas pareciendo continentales.

Se conserva la convención de los mapas oficiales del Ecuador: el continente ocupa el marco y la isla
va aparte, con línea de puntos, para que se entienda que ese trozo no está a escala ni en su sitio.

## 4. Decisiones tomadas y justificación

- **Comparar por nombre normalizado, no por igualdad de textos.** La regla ya existía en el panel
  (`utils/provincias`) por el mismo motivo: la cartografía escribe `Manabí` y la fuente publica
  `MANABI`. Aquí el fallo fue no usarla en esta pieza. Se importa `normalizarNombre` en lugar de
  escribir una segunda normalización.
- **Calcular el recuadro, no escribirlo.** Ver § 3.2: una posición fija es una promesa de que el
  encuadre no cambiará nunca.
- **No añadir una biblioteca de mapas.** Sigue bastando con pintar veinticuatro polígonos y saber cuál
  se pulsa; una biblioteca añadiría cientos de kilobytes y una hoja de estilos que reescribir.
- **Dejar el reparto por provincia como está** (sin el filtro de provincia puesto). Es lo que hace que
  el mapa sirva para *navegar*: elegir una provincia no puede poner las demás a cero.

## 5. Casos de uso y requisitos

| CU / RF | Cómo queda |
|---|---|
| CU-03 consultar con filtros | El mapa es uno de los tres sitios donde se elige provincia; sus cifras y las de la tabla salen de la misma consulta |
| RF-12 filtro por provincia (varias) | El clic del mapa y las casillas del panel lateral escriben la misma lista |
| OE-8 visibilidad operativa | El mapa deja de mentir sobre el volumen de cada provincia |

## 6. Pruebas ejecutadas y resultado real

- `python scripts/verificar_graficas.py` → **Todas las comprobaciones pasaron**, con el apartado 7
  nuevo: el reparto de cada familia suma el total de su tabla (6.892 / 104.316 / 111.208) y las dos
  familias suman la vista de ambas.
- Medido en el navegador, con una empresa temporal y el panel servido en `5174`, pulsando el selector
  de familia del mapa y leyendo la etiqueta accesible de cada provincia:

  | Familia | Pichincha | Galápagos |
  |---|---|---|
  | Ínfimas cuantías | 1.592 | 112 |
  | Ofertas | 28.219 | 303 |
  | Ambas | 29.811 | 415 |

  Las tres cifras coinciden con las del repositorio medidas en el servidor, y las peticiones que salen
  (`/v1/estadisticas` y `/v1/registros`) llevan `categoria` cuando toca y lo omiten en «ambas».
- Geometría del mapa medida sobre el `svg` renderizado, antes y después (§ 3.1).

## 7. Evidencia de aceptación

```
categoria=None      tabla= 111208 reparto=25 filas suma= 111208 {'pichincha': 29813, 'galapagos': 415}
categoria=infimas   tabla=   6892 reparto=24 filas suma=   6892 {'pichincha': 1594, 'galapagos': 112}
categoria=ofertas   tabla= 104316 reparto=24 filas suma= 104316 {'pichincha': 28219, 'galapagos': 303}

continente: minX 102.3  maxX 517.7  minY 12.0  maxY 468.0
islas:      x 12.3 → 87.7   y 63.0 → 147.0
recuadro:   x 6  ancho 88  y 57  alto 96      (la isla está dentro)
provincias: 24
```

## 8. Deuda técnica y pendientes

- El `viewBox` del mapa está fijo en `620 × 520`. El recuadro se calcula, pero el **hueco** del que
  depende sale de ese encuadre: si algún día cambia, hay que volver a medirlo (y la comprobación del
  § 6 es la que lo dice).
- `utils/mapa.js` **no tiene pruebas automáticas**: el panel no tiene ejecutor de pruebas y sólo se
  comprueba midiendo el `svg` renderizado. Es la deuda más incómoda de esta fase, porque es la pieza
  que se rompió en silencio.
- El sombreado sigue siendo lineal y lo advierte la leyenda; una escala por cuantiles se vería mejor
  y sería menos honesta.

## 9. Riesgos abiertos y mitigaciones

| Riesgo | Estado |
|---|---|
| Otro nombre con grafía distinta a la del panel | Mitigado: la comparación pasa por `normalizarNombre`, la misma que usa el resto del panel |
| El mapa se ve distinto en móvil | El `svg` escala con la ventana y el recuadro viaja con él; no se ha medido en móvil |
| Confundir el recuadro con una isla en su sitio | El recuadro va con línea de puntos y etiqueta, que es la convención y lo que ya hacía |

## 10. Aprobación

Pendiente de revisión visual del cliente: el aspecto del mapa es lo único que no se puede comprobar
desde aquí —la pestaña del navegador desde la que se verificó no repinta— y se aprobó midiendo el
`svg`, no mirándolo.
