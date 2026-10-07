# Fase 4f — Descarga masiva de OCDS: el año en minutos, no en días

## 1. Objetivo

Que el año entero de procesos publicados esté en la base **sin pedirlo diez mil veces**. La vía
paginada cuesta 10.363 peticiones para el año 2026 contra un origen que responde 429 cada cinco o
seis: medido, ~9 segundos por página y **~26 horas** de reloj. El portal publica los mismos
procedimientos en ficheros mensuales, así que la vía correcta es **doce peticiones**.

## 2. Alcance (incluido / excluido)

**Incluido**

- Adaptador `FuenteOcdsMasiva`: lee el ZIP del mes, traduce el OCDS estándar a la fila plana que ya
  sabe leer la tabla de mapeos, y **combina por `ocid`** los meses que se le pasen.
- Guion `scripts/importar_ocds_masivo.py`: descarga por meses, traduce, combina y escribe por tandas.
- Dos guiones de medida: `scripts/sondear_ocds_masivo.py` (qué trae el fichero) y
  `scripts/comparar_ocds_listado_masiva.py` (campo a campo, listado contra fichero).
- 32 pruebas nuevas en `pruebas/unidad/test_ocds_masiva.py`.

**Excluido, a propósito**

- **Los ítems con CPC del fichero.** Vienen —4.294 en septiembre, con código, cantidad y precios— y
  hoy solo se consiguen leyendo la ficha de cada necesidad a una petición por necesidad. Decisión
  del 2026-10-01: primero la vía, sin ítems. No hay que volver a pedirlos: están en el fichero.
  **Cerrado el 2026-10-06**: se guardan, con el mismo formato que los de las ínfimas, en
  `docs/27-fase-4o-desglose-del-producto.md`.
- Guardar el `crudo` completo del estándar (`tender`, `awards`, `parties`…). Se guarda la fila
  plana, igual que hace hoy el listado, para no multiplicar por cinco el peso de cada registro.
- Años anteriores (el guion acepta `--anio`).

## 3. Implementaciones realizadas
| Componente | Archivo / símbolo | Qué hace |
|---|---|---|
| Traducción | `fuentes/ocds_masiva.py` · `traducir_publicacion` | Publicación OCDS → las **mismas quince claves** que publica el listado, para que `ocds_mapeos.MAPEOS_POR_DEFECTO` siga valiendo tal cual |
| Combinación | `fuentes/ocds_masiva.py` · `combinar` | Junta por `ocid` las filas del mismo proceso: el primer dato que no venga vacío; la fecha, la más antigua; un cero en un importe **no** es un dato |
| Adaptador | `fuentes/ocds_masiva.py` · `FuenteOcdsMasiva` | Lee uno o varios ZIP, traduce, combina y devuelve las filas. Siempre `parcial` |
| Importación | `scripts/importar_ocds_masivo.py` | Descarga por meses (reutiliza lo ya bajado), traduce, combina y escribe por tandas con el bloqueo de la ingesta |
| Medida | `scripts/sondear_ocds_masivo.py` | Cuántos procedimientos trae el fichero, qué campos, cuántos ítems con CPC, contrastado con `get-totals` |
| Contraste | `scripts/comparar_ocds_listado_masiva.py` | Las dos filas del mismo `ocid` una al lado de la otra, campo a campo |

## 4. Decisiones tomadas y justificación

**El endpoint de descarga, encontrado en el propio portal.** La página de datos abiertos no expone
las URLs en el HTML: el listado de descargas lo construye un script de Vue con
`/PLATAFORMA/download?type=json&year=&month=&method=all` y `/PLATAFORMA/get-totals`. Los totales
cuadran con el listado (103.628 para 2026) y el `month=0` no sirve el año entero: hay que pedir mes a
mes.

### ¿Está duplicado el año? Comprobado: no (2026-10-06)

Cuando el censo llegó a ~105.000 ofertas, la pregunta razonable fue si había filas repetidas. Se
midió, por partes, y la respuesta es que **el año tiene ese tamaño de verdad**:

| Qué se comprobó | Resultado |
|---|---|
| Filas frente a claves naturales distintas | 104.693 filas · **104.693** claves (`ocid`) · sin repetidos, en OCDS y en NCO |
| Códigos distintos | 104.542 códigos para 104.693 filas: **96 códigos aparecen dos veces** |
| Esos 96, ¿son el mismo proceso? | **Los 96 tienen el contenido idéntico** (entidad, objeto, fecha y monto): la fuente publica la misma **orden de compra** con dos `ocid` que solo difieren en el sufijo. 0 de dos procesos distintos compartiendo código |
| Reparto por meses de publicación contra los ficheros | Enero **3.812 = 3.812**, marzo 18.774 ≈ 18.772, y de ahí en adelante el exceso crece hacia los meses recientes (+214 en agosto, +208 en septiembre) |
| Total | 104.693 en la base frente a **103.906** procedimientos distintos en los ZIP: **+0,76 %**, que es lo que entra por el listado en vivo y todavía no está en la foto del mes |

Las **55 filas sin código** son publicaciones de octubre recién entradas por el rabo, cuyo anuncio
(`tender`) aún no ha llegado: no son duplicados, son procesos en curso.

**Los 96 repetidos de la fuente no se tocan, a propósito.** La identidad del registro es el `ocid`,
no el código: si se borrara una de las dos filas, la siguiente vuelta la volvería a escribir —la
fuente publica las dos—, así que la única forma de «arreglarlo» sería **ignorar** una publicación de
la fuente, y eso es una decisión con consecuencias (¿cuál de las dos se conserva?) a cambio de
0,09 % de las filas. Queda medido y escrito para que nadie lo investigue dos veces.

**Traducir en lugar de adaptar la tubería.** La ingesta —mapeos, huella, `upsert`, historial,
pendientes, invalidación de caché— no se toca: se le entrega una fila plana idéntica a la del
listado. La equivalencia de cada campo se **midió** poniendo las dos filas del mismo `ocid` una al
lado de la otra, y hay una prueba por campo. Dos diferencias, documentadas: `id` usa `tender.id` (el
listado publica un número interno que el fichero no trae) y `internal_type` se recorta en «en el
convenio», porque el fichero arrastra el convenio entero en los catálogos.

**Combinar por `ocid` es obligatorio, no una precaución.** El fichero no es la foto del proceso sino
un **delta de publicaciones**: de las 4.634 de septiembre, **2.340 no traen `tender`** —son las de
adjudicación y contrato, cuyo anuncio se publicó antes—. Escribirlas seguidas sería destruirse la una
a la otra: la de septiembre dejaría el título y la descripción en blanco, y la de agosto borraría el
proveedor y el monto.

**Un cero en un importe no es un dato.** El listado publica `0.000000` mientras no hay adjudicación,
y esa cifra bloqueaba el importe de verdad al combinar: la publicación del anuncio —que se lee
primero— dejaba el monto a cero para siempre. Se trata como ausencia.

**Seis decimales en los importes.** No es cosmética: `mapeo._a_decimal` interpreta `999.999` como
miles —el punto separa miles en el formato ecuatoriano—, así que un importe enviado como número
podría salir mil veces mayor. `999.999000` no admite esa lectura. Hay una prueba que lo deja escrito,
incluida la lectura equivocada, para que nadie «simplifique» el formato.

**Se escribe por tandas.** Cada tanda es un ciclo normal con su transacción y su registro de
sincronización: una transacción de 103.000 filas perdería el año entero por un fallo en la última
página. Así lo escrito queda escrito y volver a lanzarlo no duplica nada.

**La marca de agua no avanza.** Una foto con horas de retraso no cubre el final del listado, así que
se declara parcial. El ciclo de cada quince minutos sigue leyendo su rabo y lo publicado entre la
foto y ahora entra por ahí.

**Un mes sin fichero no es un error.** El 1 de octubre, octubre responde **500** (no 404) porque su
fichero todavía no está publicado. La primera versión abortaba la importación entera al intentar
descargarlo —antes de escribir una sola fila—; ahora se omite con su motivo y sigue con los meses que
sí están.

## 5. Casos de uso y requisitos cubiertos

| ID | Descripción | Estado |
|---|---|---|
| CU-05 | Consultar contrataciones de la fuente | El año entero en la base: 103.135 procedimientos |
| R-01 | Ninguna petición de usuario puede originar tráfico hacia el SERCOP | Sin cambios: la importación es un guion de mantenimiento, no un endpoint |
| RNF | Coste de mantenimiento hacia la fuente | 12 peticiones al año en lugar de 10.363 por vuelta completa |

## 6. Pruebas ejecutadas y resultado real

| Prueba | Comando | Resultado |
|---|---|---|
| Análisis, formato y tipos | `ruff check .` · `ruff format .` · `mypy` | `All checks passed!` · sin cambios · `no issues found in 204 source files` |
| Unidad | `pytest pruebas/unidad` | `710 passed` (32 nuevas) |
| El fichero de septiembre | `scripts/sondear_ocds_masivo.py --mes 9` | 4.634 publicaciones · 25,1 MB descomprimidos · 4.294 ítems con CPC |
| Contraste campo a campo | `scripts/comparar_ocds_listado_masiva.py` | 14 de las 15 claves idénticas al listado; `id` es la excepción documentada |
| Importación de un mes | `importar_ocds_masivo.py --desde-mes 9 --hasta-mes 9` | **4.634 filas en 13 s**, 3.973 nuevas y 661 actualizadas, **1 petición** |
| Importación del año | `importar_ocds_masivo.py` | 103.135 procedimientos · 97.057 con objeto de compra (94 %) · 94.043 con proveedor (91 %) |

## 7. Evidencia de aceptación

```
$ python scripts/sondear_ocds_masivo.py --mes 9 --fichero tmp/ocds_2026/releases_2026_septiembre.zip
  releases_2026_septiembre.json  25.1 MB descomprimido
  Publicaciones (releases): 4634 · procedimientos (ocid): 4634
    el portal dice 4798 procedimientos para 2026-09: NO cuadra
  Ítems con clasificación CPC:     4294

$ python scripts/importar_ocds_masivo.py --desde-mes 9 --hasta-mes 9
Descarga
   9 · septiembre 2.7 MB en 3 s
Lectura y combinación
  4634 publicaciones → 4634 procedimientos en 0 s
  con objeto de compra: 2294 · con proveedor adjudicado: 1906
[  1]   4634/4634 filas · nuevas  3973 · actualizadas   661 · iguales     0 · sin mapear   0
Procedimientos escritos: 4634 de 4634 en 13 s
  peticiones al portal: 1 (una por mes)

$ python scripts/importar_ocds_masivo.py --conservar     # año en curso, 9 meses publicados
  10 · octubre    no disponible (500): se omite
Lectura y combinación
  103135 publicaciones → 103135 procedimientos en 15 s
  con objeto de compra: 97057 · con proveedor adjudicado: 94043
```

El 3,4 % que «falta» —4.634 en el fichero contra 4.798 en el listado de septiembre— es lo publicado
después de generarse el fichero: se comprobó que el fichero **cubre todos los días del mes**, y ese
hueco lo cierra el ciclo de cada quince minutos.

## 8. Deuda técnica y pendientes

- **Los ítems con CPC del fichero no se guardan.** Era la mejora más grande pendiente: dar
  clasificación CPC a los procedimientos publicados, que hasta ahora solo tenían las ínfimas, y sin
  una petición por necesidad. **Resuelto el 2026-10-06** — ver
  `docs/27-fase-4o-desglose-del-producto.md` —, y sin volver a descargar nada: los ZIP ya estaban en
  `tmp/ocds_2026`.
- **El `crudo` guardado es la fila plana**, no el estándar completo. Con él no se pueden reconstruir
  `tender`/`awards`; si algún día se quieren, hay que volver a los ficheros (que el portal conserva).
- **La importación no está automatizada.** Es manual a propósito para el histórico; para el mes en
  curso podría programarse (una petición al día) y sustituir al rabo paginado, pero el fichero tiene
  horas de retraso y el rabo da frescura de quince minutos.
- **El contraste de totales del fichero contra `get-totals` se mide a mano** en la sonda; convendría
  dejarlo como comprobación del guion de importación.

## 9. Riesgos abiertos y mitigaciones

| Riesgo | Por qué importa | Mitigación |
|---|---|---|
| El portal cambia el nombre o la ruta del fichero | La importación dejaría de traer datos | `get-totals` y el ZIP se piden con la misma URL que usa su propia web; una respuesta que no sea 200 se informa con su código y no se escribe nada |
| Un mes sin publicar (el actual) | Abortaba la importación entera antes de escribir | Se omite con su motivo; el mes en curso lo cubre el ciclo de quince minutos |
| Importar sin combinar | Borraría el título de un proceso con la publicación de su adjudicación | La combinación por `ocid` es parte del adaptador, no una opción del guion, y hay prueba |
| Un importe con tres decimales | Mil veces mayor por la lectura como miles | Se escriben seis decimales, y hay prueba de la trampa |
| El peso del año en la base | ~1 GB de golpe | Medido en `docs/07`; el histórico está particionado por mes |

## 10. Aprobación

| Rol | Nombre | Fecha | Veredicto |
|---|---|---|---|
| Ingeniero QA | | | |
| Revisor de Código | | | |
| Revisor de Ingesta | | | |
