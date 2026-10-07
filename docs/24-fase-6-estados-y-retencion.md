# Fase 6 — Estados que vencen solos y retención de lo que ya no es una oportunidad

| Campo | Valor |
|---|---|
| Estado | Cerrada |
| Fecha | 2026-10-06 |
| Depende de | F4 (plazo de proformas, `solo_con_plazo`), F4.9/F4.11 (rendimiento) |
| Petición de origen | «actualización de estadísticas en ofertas e ínfimas cada 5 minutos con los workers, implementar un worker de actualización de estados» · «agregar un worker que elimine las ínfimas cuantías que estén con el plazo finalizado, para que no se vuelva pesada la bd» |

## 1. Objetivo

Que el sistema **se entere** de que una ínfima cuantía dejó de admitir proformas, y que deje de
guardar lo que ya no se va a mirar. Son dos trabajos distintos con la misma clave: la fecha límite de
proformas, que hasta ahora vivía dentro del `jsonb` de cada fila y se recalculaba en cada consulta.

## 2. Alcance

**Incluido:** `registro.plazo_proformas_en` con su índice parcial, la escritura de esa columna en la
ingesta, el filtro «solo con plazo» pasando a usarla, la tercera cadencia del `worker` (cada cinco
minutos) que avisa de los vencimientos y retira lo vencido, `scripts/purgar_vencidas.py` con
simulación, y tres ajustes con sus valores por defecto documentados.

**Excluido:** un estado calculado por fila (§ 4.1), el borrado de ofertas de OCDS (no tienen plazo), y
la compactación de la tabla (`VACUUM FULL` sigue esperando sitio en disco; ver `docs/16`).

## 3. Implementaciones realizadas

| Archivo / símbolo | Qué se hizo |
|---|---|
| `alembic/versions/0021_plazo_proformas.py` | Columna, relleno acotado a las filas que traen el campo, índice parcial y `ANALYZE` |
| `dominio/plazos.py` · `PATRON_FECHA_ISO`, `instante_de_limite` | El valor del JSON se convierte en instante **con guarda de patrón**: un texto que no sea fecha deja la columna en nulo en lugar de romper la escritura de la tanda |
| `salida/bd/ingesta.py` | La columna se escribe al guardar y al actualizar, para que una ínfima recién ingestada no quede fuera del filtro ni de la retención |
| `salida/bd/consultas.py` · `solo_con_plazo` | Pasa de un `CAST` sobre el texto a un rango sobre la columna |
| `aplicacion/puertos/mantenimiento.py` | Puerto nuevo: contar vencimientos, contar vencidas y purgar |
| `infraestructura/.../bd/mantenimiento.py` | Adaptador: la purga va en **una sola sentencia** con las dos escrituras dentro |
| `aplicacion/casos_uso/mantener_registros.py` | La vuelta: cuenta lo que venció, sube la generación si algo cambió y retira hasta el tope |
| `tareas/worker.py` | Tercera cadencia (300 s) y las opciones `--mantenimiento` y `--simular` |
| `infraestructura/config/ajustes.py`, `.env.example` | `intervalo_mantenimiento_seg`, `purga_plazo_dias`, `purga_max_filas_por_vuelta` |
| `scripts/purgar_vencidas.py` | Retención a mano, **simulando por defecto**, con `--dias`, `--limite`, `--aplicar` y `--todas` |

### 3.1 Lo que se midió antes de decidir

| Medida | Valor |
|---|---|
| Filas de `registro` | 111.212 |
| Con plazo de proformas (`NCO`) | 6.896 (**todas** las ínfimas) |
| Con el plazo ya pasado | 5.132 · con el plazo por delante: 1.764 |
| Ínfimas todavía «vigentes» en el listado y con el plazo pasado | 72 |
| Estados que publica la fuente en NCO | **uno solo**: `En Curso`, en las 6.896 |
| Purgables con 7 días de retención | 1.433 |
| Tamaño de la tabla | 575 MB (registro), 605 MB la base |

Ese «un solo estado» es el dato que decidió el diseño: la fuente **no** publica un estado útil, así
que no hay nada que copiar a una columna.

## 4. Decisiones tomadas y justificación

### 4.1 No hay ningún «estado» guardado, y por eso no hay `worker` que lo reescriba

La petición pedía un `worker` de actualización de estados. Lo que se hizo es lo contrario: **quitar el
estado de la base**. Un campo `estado = 'en plazo' | 'vencida'` es una copia de una cuenta que
depende del reloj, y se queda obsoleta en cuanto el `worker` se para un rato —con la particularidad
de que entonces la base afirma algo falso sobre filas de las que ya nadie se acuerda—. La fecha y la
comparación no se estropean nunca.

Lo que **sí** hacía falta era la otra mitad, la que no se deduce: cuando un plazo cruza, **las
respuestas que ya están en la caché se calcularon con la foto anterior**. Una página guardada hace
diez minutos sigue contando como abierta una ínfima que ya venció, y no da ningún error. Eso es lo
que arregla la vuelta de mantenimiento: cuenta los cruces y sube la generación, lo que invalida en
bloque lo cacheado.

### 4.2 El vencimiento se cuenta por ventana, no por acumulado

`contar_vencimientos(desde, hasta)` con la ventana igual al intervalo entre vueltas. Así cada
vencimiento se cuenta **una sola vez**, en la vuelta siguiente, y no hace falta guardar en ningún
sitio cuándo fue la última pasada: preguntarle al reloj cuesta lo mismo y no puede desincronizarse.

Con un «todo lo vencido hasta ahora» el contador crecería para siempre y no distinguiría una vuelta
tranquila de una que dejó pasar veinte vencimientos.

### 4.3 La generación sube solo si algo cambió

Subirla en cada vuelta de cinco minutos dejaría inservible todo lo cacheado cada cinco minutos, y el
catálogo de desplegables —que recorre el histórico entero, 14,6 s medidos— se pagaría detrás de cada
subida. Con una vuelta que casi siempre no encuentra nada, la comprobación es un `count` sobre un
rango estrecho de un índice parcial.

### 4.4 La retención está acotada y se puede apagar

`purga_max_filas_por_vuelta = 500`: acota el trabajo, no la política. Retirar las 1.433 filas
purgables de golpe mantendría bloqueadas sus páginas y competiría con la ingesta por la misma base;
en tandas, cada vuelta dura milisegundos y en unas horas está al día. **Cero desactiva la retención**:
se sigue informando de lo que venció y no se borra nada.

`purga_plazo_dias = 7` es una decisión **de negocio**, no técnica, y por eso está escrita y se puede
cambiar sin tocar código: un borrado no se deshace, y estas filas son las de los procesos ya cerrados
que sostienen las estadísticas del periodo. Cero retira en cuanto vence.

### 4.5 El `UPDATE` del relleno es barato, y por eso se hace en la migración

La guarda del patrón deja fuera a las 104.316 filas de OCDS, que no tienen el campo: se reescriben
6.896 filas, unos 14 MB, contra las 111.000 del relleno de la 0017 —que dejó 230 MB de espacio muerto
y llevó la base de 410 a 704 MB—. El índice es **parcial** por el mismo motivo: las filas sin plazo no
entran.

### 4.6 Borrar en una sola sentencia

`registro_historial` **no** tiene clave foránea hacia `registro` (a propósito: es una tabla
particionada y append-only). Si se borrara primero el registro y después el histórico, un fallo entre
las dos dejaría versiones apuntando a un registro inexistente y nada lo impediría. Las dos escrituras
van en la misma sentencia, con la lista de objetivos referenciada desde las dos: o pasan las dos o no
pasa ninguna.

`punto_contacto_entidad` sí tiene `ON DELETE CASCADE`, así que se va sola y no hay que acordarse.

## 5. Casos de uso y requisitos

| CU / RF | Cómo queda |
|---|---|
| CU-03 consultar | El filtro «ocultar lo ya vencido» pasa a ser un rango de índice en lugar de un recorrido |
| CU-12 sincronizar | La ingesta no gasta ni una petición más: el mantenimiento no habla con la fuente |
| RNF-02 consulta en BD < 1,5 s | El filtro de plazo deja de ser el caso lento |
| RNF-11 trazabilidad | Cada vuelta deja una línea con vencimientos, vencidas y retiradas |
| R-01/R-02 (límite de tasa) | El mantenimiento es base de datos y caché, nunca SERCOP |

## 6. Pruebas ejecutadas y resultado real

- **796 pruebas de unidad** (24 nuevas): `test_mantener_registros.py` (9, con un doble que implementa
  el protocolo completo), `test_plazos.py` (+5), `test_consultas_bd.py` (+4, una de ellas compara el
  patrón de la migración con el del dominio), `test_ajustes.py` (+2), `test_worker.py` (+2).
- `ruff`, `ruff format` y `mypy` limpios (216 archivos).
- Migración aplicada: `0020 → 0021 (head)`.
- Columna rellena: **6.897** filas con valor y 0 sin rellenar de las que traen el campo. Las 4 que
  aparecieron sin rellenar justo después de migrar las había escrito el `worker` **viejo**, que
  seguía corriendo: al reiniciarlo, la vuelta del listado las reescribe con la columna. Es el
  recordatorio de que la migración y el proceso que escribe van juntos.
- Planes con `enable_seqscan = off`, para ver qué índice **querría** usar el planificador:

```
retención:             Index Scan using ix_registro_plazo_proformas
                       Index Cond: (plazo_proformas_en < (now() - '7 days'::interval))
filtro solo con plazo: Index Only Scan using ix_registro_plazo_proformas
                       Index Cond: (plazo_proformas_en >= now())
```

- Retención simulada (`scripts/purgar_vencidas.py`, sin `--aplicar`): **1.433** ínfimas vencidas hace
  más de siete días, 1.029 versiones del histórico asociadas, 574 MB → 574 MB (no cambia, y es un dato:
  la retención de ínfimas **no** es lo que engorda la base; las 104.316 ofertas pesan mucho más).
- Retención real, con dos filas para verificar el camino de borrado sin retirar material que el cliente
  pueda querer:

```
registros=111224 historial=14641 contactos=0 · histórico huérfano=0
--aplicar --dias 0 --limite 2 →  retiradas: 2 ínfimas y 24 versiones del histórico
registros=111222 historial=14617 contactos=0 · histórico huérfano=0
```

  Las dos filas, sus veinticuatro versiones y nada más; **cero** versiones huérfanas antes y después.

## 7. Evidencia de aceptación

```
alembic current → 0021 (head)

con plazo en columna         6897        vencidas hace >7d            1433
sin plazo en columna       104316        solo con plazo (filtro)      1765
faltan por rellenar             4

Worker iniciado. Ciclo completo: 15 min. Vigilancia del listado: 150 s.
Mantenimiento: 300 s (retirar lo vencido hace 7 días, 500 por vuelta).

pytest: 796 passed · ruff: All checks passed · mypy: no issues found in 216 source files
```

## 8. Deuda técnica y pendientes

- La retención **reduce las estadísticas del periodo** a medida que pasa el tiempo: las ínfimas de
  hace un mes dejan de contar. Es el precio de la política pedida y está a un ajuste de distancia
  (`PURGA_PLAZO_DIAS`, o `PURGA_MAX_FILAS_POR_VUELTA=0` para no retirar nada).
- Las 1.433 ínfimas purgables son un 1,3 % de las filas y unos pocos megas: **la base no está pesada
  por las ínfimas**. Lo que pesa son las ofertas de OCDS (~2 KB por fila × 104.316). Si el objetivo
  era el tamaño, esta retención no lo consigue y habría que decidir una política sobre las ofertas.
- El `worker` no consume todavía la cola priorizada ni hay mantenimiento de particiones
  (`registro_historial` ya tiene 14.637 filas en la partición predeterminada).
- `VACUUM FULL registro` sigue pendiente de sitio en disco.
- El mantenimiento corre **en el mismo proceso** que la ingesta. Es deliberado (§ 4.4 de
  `docs/10`), pero significa que una retención que se alargue retrasa el ciclo siguiente.

## 9. Riesgos abiertos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Un despliegue que aplique la migración y no reinicie el `worker` | Las filas escritas por el proceso viejo quedan sin columna; la vuelta del listado las reescribe. Está anotado aquí y en el mensaje de cierre |
| Retirar material que alguien quería | Simulación por defecto en el guion, tope por vuelta, ventana configurable y línea de registro por cada vuelta |
| El relleno de la migración en una base más grande | La guarda del patrón acota el `UPDATE` a las filas con el campo; con 6.896 tardó segundos |

## 10. Aprobación

Pendiente de decisión del cliente sobre la **política de retención**: el valor por defecto (7 días) es
el que se pidió, y con él se retiran 1.433 ínfimas en las primeras vueltas. Si prefiere conservarlas,
`PURGA_MAX_FILAS_POR_VUELTA=0` lo desactiva sin tocar el código.
