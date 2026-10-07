# Fase 9 — Prueba de carga: cuántos usuarios concurrentes aguanta el panel

| Campo | Valor |
|---|---|
| Estado | Cerrada **con la medida pendiente en el despliegue** |
| Fecha | 2026-10-06 |
| Depende de | F4.9 (rendimiento de consultas), F4.11 (columnas de provincia y tipo), F4.13 (sesiones) |
| Petición de origen | «realiza test para k6 para poder ver cuantos usuarios concurrentes aguanta el aplicativo, se quiere implementar porlomenos 1k de usuarios» |

## 1. Objetivo

Poder **medir** cuántas personas pueden estar dentro del panel a la vez, con una prueba repetible y
con las lecturas separadas por tipo —porque una consulta servida de la caché y una búsqueda por
palabra clave no cuestan lo mismo y promediarlas no informa de nada—. Y, de paso, saber **dónde**
está el techo: si en el API, en la base o en la red.

## 2. Alcance

**Incluido:** el guion de carga (`carga/panel.js`), el preparador de cuentas
(`backend/scripts/preparar_carga.py`), las instrucciones de uso (`carga/README.md`), los umbrales
por tipo de lectura, y la medida del entorno de desarrollo con su diagnóstico.

**Excluido:** ejecutar la escalera hasta 1.000 usuarios **contra el despliegue de Docker** (no hay
Docker en esta máquina), y la prueba del canal de eventos en vivo (`/v1/presencia/eventos`), que es
una conexión larga por usuario y merece su propio guion.

## 3. Implementaciones realizadas

| Archivo / símbolo | Qué hace |
|---|---|
| `carga/panel.js` | Los escenarios: escalera hasta 1.000 usuarios o un escalón fijo; cada vuelta hace lo que hace el panel; una serie por tipo de lectura; umbrales y resumen |
| `carga/panel.js` · `renovar` | Renueva el token de acceso al recibir un 401, **con la rotación incluida**, como hace el panel |
| `backend/scripts/preparar_carga.py` | Crea (y borra) las cuentas: un negocio y una cuenta por usuario, con todas las vistas y los términos aceptados. Escribe `carga/credenciales.json` |
| `carga/README.md` | Cómo se ejecuta, qué hay que mirar y por qué el entorno decide el resultado |

k6 no está instalado en la máquina y su instalador pide permisos de administrador. Se usa el `.zip`
de sus publicaciones, que no necesita ninguno:

```powershell
Invoke-WebRequest -Uri https://github.com/grafana/k6/releases/download/v2.2.0/k6-v2.2.0-windows-amd64.zip -OutFile k6.zip
Expand-Archive k6.zip -DestinationPath $env:TEMP\k6
& "$env:TEMP\k6\k6-v2.2.0-windows-amd64\k6.exe" version   # k6.exe v2.2.0
```

## 4. Decisiones tomadas y justificación

### 4.1 Una serie por tipo de lectura, y la mediana como criterio de las lecturas cacheadas

La tabla y las gráficas **se cachean**; la búsqueda por palabra clave **no**, a propósito, porque es
texto que se teclea (`Filtros.cacheable`). Promediar las tres da un número que no describe a ninguna.

Y el p95 no sirve para decidir si el panel se siente rápido: con la caché invalidándose cada cuarto
de hora, **siempre** hay consultas que llegan a la base, así que un p95 de 300 ms sobre todo lo que
pasa no se cumple ni con el sistema perfecto. Lo que se vigila es la **mediana** (< 300 ms, la meta
de una consulta cacheada) y se deja el p95 acotado por la meta de una consulta a la base (1,5 s,
`RNF-02`).

### 4.2 Las cuentas se preparan fuera de la prueba

Iniciar sesión cuesta Argon2, que es lento a propósito. Dentro de la prueba, el primer minuto mediría
el coste de los inicios de sesión y no el panel. Y cada usuario virtual necesita **su propia cuenta**:
el panel solo permite dos sesiones por cuenta, así que cien usuarios sobre una cuenta se expulsarían
entre ellos y lo que se mediría es la evicción.

### 4.3 El guion renueva el token en lugar de reutilizar uno viejo

El token de acceso dura quince minutos, así que una prueba de diez los agota. El guion renueva con el
de renovación —que rota— cuando recibe un 401, exactamente como el panel. Si no lo hiciera, la segunda
mitad de la escalera mediría sesiones caducadas.

## 5. Casos de uso y requisitos

| CU / RNF | Cómo queda |
|---|---|
| CU-03 consultar (p95 < 300 ms cacheada) | Es lo que mide la serie `tabla` y la serie `graficas` |
| RNF-02 consulta en BD < 1,5 s | Es el umbral de la serie `tabla_termino`, que nunca se cachea |
| RNF-03 escalabilidad (50+ negocios) | La escalera sube hasta 1.000 usuarios concurrentes |
| RNF-04 disponibilidad con Redis caído | **No** se cubre aquí: la prueba mide el camino normal, no la degradación |

## 6. Pruebas ejecutadas y resultado real

### 6.1 Lo que se midió del entorno, antes de la prueba

| Medida | Valor |
|---|---|
| Redis | `…db.redis.io` (gestionado, **remoto**) |
| PostgreSQL | Supabase, `aws-0-us-east-1.pooler.supabase.com`, **remoto** |
| Una consulta **servida de la caché** | **1,4 – 2,1 s** con `desde_cache=true` — cada acierto es un viaje de ida y vuelta |
| Una consulta a la base | 350 – 400 ms por viaje |
| Procesos del API en desarrollo | **1** (`uvicorn --reload`); el despliegue lleva uno por núcleo |

Con esto ya se sabe que cualquier cifra de latencia tomada aquí mide **la red**, no el aplicativo.

### 6.2 La preparación de 1.000 cuentas no cabe en este entorno

`--usuarios 1000` tardaba **6,3 s por negocio** medidos (≈ 105 minutos), porque cada alta son unas
siete idas y vueltas a una base remota. Y a los 76 negocios apareció el techo de verdad:

```
sqlalchemy.exc.InternalError: (EMAXCONNSESSION) max clients reached in session mode
- max clients are limited to pool_size: 15
```

**El pooler de sesión de Supabase admite quince clientes simultáneos.** Con dieciséis inicios de
sesión en paralelo —más el `worker` y el mantenimiento— la petición se rechaza con un **500**. En el
registro del API hay **228** apariciones de ese error.

Esto no es un defecto del aplicativo: es el límite del entorno de desarrollo. Pero cambia la
conclusión de esta fase (§ 7), y conviene decirlo con las palabras del titular: **en la configuración
actual, veinte usuarios concurrentes ya saturan la base**. Lo que hay que comprobar en el despliegue
es cuánto sube ese número con PostgreSQL local y su `max_connections` bien repartido entre procesos
(`docs/07-capacidad-y-concurrencia.md` es donde está esa aritmética).

### 6.3 Las dos ejecuciones

Con cuatro cuentas propias (cada usuario virtual reutiliza su sesión, no vuelve a iniciar sesión):

**Veinte usuarios durante dos minutos** — 867 lecturas del panel, **2,65 % de fallos**:

| Serie | Lecturas | Mediana | p95 | Máx |
|---|---|---|---|---|
| `tabla` | 257 | 1.102 ms | 3.066 ms | 4.817 ms |
| `graficas` | 257 | 1.026 ms | 2.474 ms | 6.159 ms |
| `version` | 257 | 770 ms | 879 ms | 2.602 ms |
| `tabla_termino` | 96 | 1.184 ms | 1.718 ms | 2.424 ms |

**Veinte usuarios durante un minuto** — 464 lecturas, **10,78 % de fallos**:

| Serie | Lecturas | Mediana | p95 | Máx |
|---|---|---|---|---|
| `tabla` | 136 | 1.213 ms | 1.981 ms | 2.592 ms |
| `graficas` | 136 | 1.052 ms | **11.724 ms** | **17.815 ms** |
| `version` | 136 | 794 ms | 1.177 ms | 1.902 ms |
| `tabla_termino` | 56 | 1.220 ms | 1.799 ms | 7.106 ms |

### 6.4 Qué dicen esos números

1. **El suelo de latencia lo pone la red.** 770 ms para leer un número que sale de la caché
   (`/v1/ingestas/version`) es un viaje de ida y vuelta a Redis. Nada de lo que se mida aquí dice
   nada del aplicativo.
2. **El techo de concurrencia lo pone la base.** Los fallos y el pico de 17 s coinciden en el tiempo
   con los 500 de `max clients reached in session mode`. La lectura que más sufre es `graficas`,
   porque es la única que necesita conexión de base **siempre** que falla su caché.
3. **El API no es el cuello de botella.** Es entrada y salida asíncrona: mil conexiones abiertas no
   lo tumban; lo que no puede es abrir más conexiones de base que las que el servidor admite.
4. **La consulta que no se puede cachear (`tabla_termino`) no es la peor**: 1,2 s de mediana, del
   mismo orden que las cacheadas, precisamente porque aquí la caché no aporta nada frente a 1,5 s de
   red.

## 7. Evidencia de aceptación

```
k6.exe v2.2.0 (commit/00a9a1b7f5, go1.26.5, windows/amd64)

Resumen de la prueba de carga
=============================
usuarios máximos alcanzados : 20
lecturas del panel          : 464
fallos                      : 10.78 %
renovaciones de token       : 0

Por tipo de lectura, en milisegundos
------------------------------------
tipo            lecturas   mediana       p95       máx
tabla               136     1213      1981      2592
graficas            136     1052     11724     17815
version             136      794      1177      1902
tabla_termino        56     1220      1799      7106

vuelta 1: 200 · 1392 ms · desde_cache=True · generacion=162 · total=6436
vuelta 2: 200 · 2137 ms · desde_cache=True · generacion=162 · total=6436
vuelta 3: 200 · 2103 ms · desde_cache=True · generacion=162 · total=6436

EMAXCONNSESSION en el registro del API: 228
```

## 8. Deuda técnica y pendientes

- **La escalera hasta 1.000 usuarios no se ha podido ejecutar**: ni las cuentas se pueden crear a
  este ritmo, ni el pooler de quince clientes lo permitiría. Queda pendiente **en el despliegue de
  Docker**, que es donde el número significa algo. El guion ya está listo para ello: es cambiar
  `BASE_URL`.
- `preparar_carga.py` necesita un **camino rápido**: crear las empresas por lotes en lugar de una a
  una. Con PostgreSQL local son segundos; contra una base remota son horas. No se hizo porque
  duplicar el alta de empresa en un guion de pruebas es una fuente de deriva, y aquí no hacía falta
  para lo que se quería saber.
- **No se mide el canal de eventos en vivo** (`/v1/presencia/eventos`), que mantiene una conexión por
  panel abierto y es el consumo que no se ve en las peticiones. Es el candidato número uno para el
  siguiente guion.
- Los umbrales se han fijado con las metas del proyecto (`RNF-01`, `RNF-02`). Cuando haya números del
  despliegue, conviene revisarlos: los de la mediana son plausibles, los del p95 habrá que medirlos.
- La degradación **sin Redis** (`RNF-04`) no la cubre esta prueba: con la caché apagada todo va a la
  base y el techo de conexiones manda todavía más.

## 9. Riesgos abiertos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Creerse un número medido desde desarrollo | El README y esta ficha lo dicen en la primera línea: la latencia aquí mide la red |
| Que el techo real sea el de conexiones y nadie lo mire | Medido y documentado: 15 clientes en el entorno gestionado, `EMAXCONNSESSION` en el 10 % de las respuestas bajo carga |
| Mil usuarios virtuales sobre pocas cuentas compartiendo caché | Se declara en el README; con la escalera en el despliegue y cuentas de verdad, cada usuario tiene la suya |
| Que la prueba tropiece con la evicción de sesiones | Cada usuario virtual tiene su cuenta; el guion no vuelve a iniciar sesión |

## 10. Aprobación

Pendiente: **ejecutar la escalera en el despliegue**. El entregable de esta fase es la prueba y el
diagnóstico del entorno, no un número de usuarios; el número sale de correr esto contra PostgreSQL y
Redis locales, y ahí es donde hay que tomar la decisión de cuántos procesos de API y cuántas
conexiones configurar.
