# Capacidad: cuántos usuarios a la vez

Este documento responde a una pregunta concreta —**cuánta gente puede estar usando el panel al mismo
tiempo**— y lo hace con dos honestidades por delante:

1. **Esto es una estimación de diseño, no una medición.** Los costes por operación sí están medidos
   (están más abajo, con su origen), y el modelo de carga se deduce del código. Pero **no se ha
   hecho una prueba de carga**. La condición de cierre del plan —un ensayo con k6 y 900 usuarios
   simulados, flujo de eventos incluido— sigue pendiente, y hasta que se haga, cualquier cifra de
   este documento es un cálculo razonado y no un hecho.
2. **El límite no es la velocidad del sistema.** Es la memoria de la máquina y los descriptores de
   fichero. Este sistema es pequeño: su base de datos entera, con 2.263 contrataciones y 28 tablas,
   ocupa **29 MB**. Lo que decide cuánta gente cabe es cuánta memoria hay, no cuánto tarda una
   consulta.

## Lo que cuesta cada operación (medido)

| Operación | Coste | De dónde sale |
|---|---|---|
| Ida y vuelta a Supabase (una consulta cualquiera) | **~120 ms** | Medido el 29/09/2026: 6 consultas seguidas, 708 ms (118 ms cada una) |
| El mismo trozo contra PostgreSQL local | **~1 ms** | El mismo bloque, sin cruzar la red |
| Comando a Redis local | **~0.1 ms** | Medido |
| Plan de la consulta de búsqueda | **~0.5 ms** | `EXPLAIN ANALYZE` |

Dos consecuencias, y la primera es la que explica la sensación de lentitud:

1. **Una acción de la persona cuesta 4–6 idas y vueltas seguidas**, porque son consultas encadenadas
   —quién llama, cuántas hay, la página, las gráficas—. A 120 ms cada una son **0,5–0,7 s por
   acción... con dos usuarios o con dos mil**. Eso no lo arregla la capacidad: lo arregla tener la
   base al lado de la aplicación. Con PostgreSQL en el mismo servidor, la misma acción baja a unos
   pocos milisegundos.
2. **El entorno de desarrollo mide mal a propósito**: hoy la API corre en la máquina local y la
   base está en Virginia. Los números de arriba son el peor caso posible, no los del despliegue.

## Qué hace el sistema por cada panel abierto

Esto es lo que hay que entender antes de dar cualquier número: **un panel abierto no es un usuario
que está haciendo algo**. Casi todo el trabajo que genera lo genera por estar abierto.

| Concepto | Frecuencia | Coste del lado del servidor |
|---|---|---|
| Conexión al flujo de eventos | 1 abierta, permanente | 1 descriptor de fichero, 1 tarea de asyncio |
| Latido de presencia | cada 30 s | 1 petición HTTP + **0 consultas a la base** |
| Instantánea del cuadro de presencia | cada 15 s, por conexión | **0 consultas a la base durante ese plazo** |
| Acción de la persona (una búsqueda) | suponemos 1 por minuto | ~3 peticiones, 0-6 consultas según caché |

Las dos filas que antes mandaban ya no cuestan base de datos, y eso cambia el modelo entero.

## El cálculo, con N paneles abiertos y B empresas distintas

Aparece una variable nueva, **B = cuántas empresas distintas tienen a alguien conectado**, y hay que
tenerla porque el arreglo de la instantánea es **por empresa**: cien paneles de la misma empresa
cuestan un solo cuadro; cien paneles de cien empresas distintas, cien.

Consultas a la base por segundo:

| Origen | Consultas/s |
|---|---|
| Instantáneas de presencia (una cada 3 s por empresa y alcance, 3 consultas cada una) | $1{,}0 \times B$ |
| Acciones de las personas (2 consultas cada una, 1 por minuto) | $0{,}033 \times N$ |
| **Total** | $\mathbf{1{,}0B + 0{,}033N}$ |

El techo de consultas por segundo lo pone el conjunto de conexiones y la latencia: con 20 conexiones
por proceso y 120 ms por consulta, cada proceso despacha **165 consultas/s** (40 conexiones → 330).

| Paneles abiertos | Consultas/s | ¿Aguanta? |
|---|---|---|
| 100 paneles, 10 empresas | 13 | Sin nada que decir |
| 500 paneles, 20 empresas | 37 | Cómodo |
| 1.000 paneles, 40 empresas | 73 | Cómodo. Antes eran 390 |
| 3.000 paneles, 100 empresas | 199 | Alcanza el techo; a partir de aquí, la lista de espera |

Comparado con el modelo anterior (`0,39N`, todas las consultas creciendo con los paneles), lo que se
ha quitado es el término dominante: la instantánea dejó de multiplicarse por conexión.

## Qué se rompe primero, y en qué orden

**1. Los descriptores de fichero.** Cada conexión al flujo de eventos ocupa uno, y el `compose` **no
fija `ulimits`**. Si el límite del contenedor es el de una sesión de shell corriente —1.024—, el
techo aparece en mil conexiones repartidas entre los procesos, y el síntoma es un «too many open
files» en una petición cualquiera, sin relación aparente con la presencia. Es la primera pared y es
la que menos se ve venir.

**2. La memoria.** Con cuatro procesos de API, PostgreSQL y Redis:

| Componente | Memoria |
|---|---|
| 4 procesos de uvicorn (con SQLAlchemy, FastAPI y el cliente de Redis) | ~600 MB |
| PostgreSQL (`shared_buffers=1GB` más su propio consumo) | ~1,3 GB |
| Redis (el límite está en 512 MB; hoy usa 2,3 MB) | hasta 512 MB |
| Caddy y el sistema | ~330 MB |
| **Total** | **~2,7 GB** |

En 4 GB cabe, pero sin holgura: no queda sitio para un pico ni para el crecimiento de los procesos a
lo largo de los días. En 8 GB sobra.

**3. La lista de espera por conexión de base.** Ya no la tormenta de instantáneas —está arreglada—,
sino el conjunto de conexiones: cada proceso tiene 20 y cada consulta las ocupa 120 ms mientras viaja
(y en Camino B, casi nada). Cuando la demanda de consultas por segundo supera ese techo, las
peticiones esperan; `BD_POOL_TIMEOUT_SEG` corta la espera en 5 s y lo que pasa de ahí devuelve un
error. Es la única pared que se ve **antes** de romperse, y por eso el panel avisa en vez de
quedarse mudo.

**4. El número de procesos de API.** Cada proceso abre hasta 20 conexiones a PostgreSQL
(`BD_POOL_SIZE` + `BD_MAX_OVERFLOW`) y el servidor admite 200 (`max_connections`). Es decir:
**10 procesos como máximo**, entre API y worker. Con `--workers 4` y el worker de ingesta son 5. Hay
margen, pero es un techo aritmético que conviene tener escrito antes de escalar a ciegas.

**5. El ancho de banda de salida.** Cada panel recibe el cuadro completo de su empresa cada 15 s, y
ese cuadro lleva una fila por persona. Con 500 personas en una empresa son unos 100 KB por panel y
relectura: cien paneles de esa empresa son **~0,7 MB/s (5 Mbit/s)** sostenidos de salida. Con
empresas pequeñas es despreciable; con una empresa muy grande, es la primera cosa que se nota en la
factura del proveedor.

## Dimensionamiento

| Máquina | Paneles simultáneos | Para quién |
|---|---|---|
| 2 vCPU / 4 GB | **600–1.500** | Empezar. Cubre cientos de usuarios con holgura. |
| 4 vCPU / 8 GB | **2.000–4.000** | Miles de usuarios. Los dos arreglos que hacían falta ya están puestos. |

Las dos cifras suben respecto al cálculo anterior —que decía 300–600 y 1.500–3.000— porque se han
quitado los dos términos que crecían con los paneles: el latido ya no consulta la base y la
instantánea se comparte entre las conexiones de la misma empresa. **Ese es el orden de magnitud de la
mejora, y es el doble, no un cambio de escala.**

Las cifras siguen siendo de **diseño, no de medición**: la prueba de carga con k6 y 900 paneles sigue
pendiente, y hasta que se haga no hay ninguna observación real de mil conexiones simultáneas.

Y una advertencia que no es de capacidad sino de riesgo, y que importa más que el número: **un solo
servidor no tiene recambio.** Un reinicio por una actualización, un fallo del disco o una caída del
proveedor deja el panel fuera hasta que alguien lo levante. Escalar de máquina no resuelve eso;
resolverlo es tener dos, y eso multiplica el coste. La decisión es de negocio, no técnica.

## Lo que de verdad se nota, y no es la capacidad

Con todo lo anterior en la mano, conviene decirlo claro porque es lo que alguien va a percibir al
usar el sistema:

- **Hoy (API local, base en Virginia)**: cada acción es una cadena de 4–6 idas y vueltas de 120 ms, así
  que responde en **medio segundo o un segundo** con una sola persona conectada. No es lentitud por
  sobrecarga: es la distancia. El panel lo disimula pidiendo la tabla y las gráficas **a la vez** en
  lugar de encadenarlas, y sirviendo del caché lo que se repite.
- **Con Camino B (todo en el mismo servidor)**: la misma acción baja a unos pocos milisegundos, y el
  mismo hardware admite muchas más consultas por segundo porque cada una deja de ocupar 120 ms de una
  conexión. La mejora de lo que se siente es de dos órdenes de magnitud, y no cuesta más máquina.

### El multiplicador que se esconde en un bucle

Hay un patrón que no aparece en ningún modelo de concurrencia y hace más daño que la carga: **una
consulta dentro de un bucle**. El listado de palabras clave pedía el número de suscriptores de cada
término en su propia consulta, y con cuarenta palabras clave eso son cuarenta idas y vueltas
encadenadas: **16,7 segundos** medidos en el navegador para pintar el panel de filtros, sin un solo
error y con la pantalla aparentemente colgada.

Se arregló pidiendo todos los conteos en **una** consulta, y el mismo listado pasó a **3,0 s** —el
resto es el túnel de desarrollo—. La lección para el cálculo: antes de añadir máquina conviene
multiplicar. Un N+1 con N = 40 cuesta cuarenta veces más que su consulta, y no lo arregla ningún
tamaño de servidor.

## Lo que hay que arreglar, por orden de impacto

1. **Una instantánea por empresa cada quince segundos, no una por conexión.** Es el 70 % de las
   consultas del sistema. Basta con guardar el cuadro en el caché con un par de segundos de vida,
   clavado por `negocio_id`: cien paneles de la misma empresa pasarían a costar lo mismo que uno. Es
   un cambio pequeño y ya está la pieza (`Cache.guardar`).

   **Pero cuidado con la clave del caché, que este es el arreglo que puede abrir un agujero.**
   `cuadro_del_negocio` no devuelve lo mismo para todos: un rol administrativo ve la presencia de
   toda la empresa, y quien no administra **solo se ve a sí mismo**. Si la clave fuera solo
   `negocio_id`, el primer cuadro que se guardara —el de un administrador, con la lista completa— se
   serviría después a cualquiera de esa empresa, y la comprobación de permisos se habría esquivado
   por la puerta de atrás. La clave tiene que incluir el alcance: `negocio_id` **y** quién pregunta.
   No es un detalle de implementación; es la diferencia entre cachear y filtrar información de unos
   compañeros a otros.

   > **Hecho** (2026-09-29). `clave_cuadro()` incluye el alcance —`todos` para quien puede ver a sus
   > compañeros, el identificador de la persona para quien solo se ve a sí misma— y
   > `cuadro_serializado()` sirve del almacén durante `TTL_CUADRO_SEG` (3 s) en lugar de recalcular.
   > El camino de «preguntar por un negocio ajeno» **no se guarda nunca**: ahí el resultado depende
   > de quién pregunta, porque el aislamiento de la base decide qué se ve, y dos administradores de
   > empresas distintas con la misma clave se servirían el uno al otro lo que no es suyo. Las dos
   > cosas están fijadas con pruebas: un administrador y un lector de la misma empresa **no**
   > comparten entrada, y dos lectores distintos tampoco.
   >
   > Con esto, la aritmética de la tabla de abajo mejora en el término dominante: las consultas por
   > panel dejan de crecer con el número de paneles de la misma empresa. Los 1.500–3.000 usuarios
   > simultáneos de la configuración de 4 vCPU / 8 GB pasan de «pidiendo el arreglo» a «con el
   > arreglo puesto».

2. **Fijar `ulimits: nofile` en el `compose`.** Una línea que convierte una pared invisible en algo
   que no llega a ocurrir. Ya está puesto en `api` y en `proxy` —los dos procesos que mantienen las
   conexiones abiertas—.
3. **`latir()` contra Redis en lugar de la base** (Fase 1b, ya planificada): quita $0{,}03N$
   consultas por segundo, que es poco, y sobre todo quita una consulta por latido en el camino más
   transitado del sistema.

   > **Hecho** (2026-09-29). `latir()` consulta el almacén y solo pregunta a la base si el almacén
   > **no responde**. La distinción que hace que esto sea correcto y no un atajo: que el almacén diga
   > «no consta» **es** un cierre —la sesión no late—, mientras que un almacén caído no dice nada y
   > obliga a la comprobación en la base. Confundir las dos cosas daría una sesión cerrada latiendo
   > para siempre, o a toda la instalación sin presencia cuando Redis se apaga.

## Crecimiento de los datos (medido)

El coste por fila, medido con `scripts/peso_de_datos.py` (instantánea del 2026-10-01 con 5.113 filas,
mientras el relleno del año inserta: **~10,9 KB** contando índices), y no los 5,3 KB que decía esta
nota antes de medirlo. La fila guarda **dos** copias del mismo contrato: `datos` (944 bytes de media
en NCO) y `crudo` (1.097), más los ítems de CPC (693) y el texto de búsqueda (244). Las cifras se
mueven mientras el relleno está en marcha, así que lo que importa es la proporción, no el dígito.

Lo que más pesa no es la fila: son los **índices**, algo más de la mitad del total. Uno solo,
`ix_registro_datos` —un GIN sobre el jsonb `datos`—, ocupa **20,3 MB**: tres cuartas partes de todos
los índices y más que la tabla entera. El único sitio que lo usa es la consulta de catálogos, así que
es el primer candidato a quitar en cuanto un `EXPLAIN` confirme que ninguna consulta de usuario lo
necesita.

Sobre cuánto crece al día, lo medido y lo estimado van separados. **Medido**: el listado general de
OCDS publica **378 filas al día** (10.363 páginas ≈ 103.628 filas para el año 2026). **Estimado**: las
**1.000-1.400 contrataciones al día** que traía esta nota se midieron el 28 y el 29 de septiembre y no
distinguen «vistas» de «nuevas», así que la proyección es un techo, no un hecho. Con ese techo
(`scripts/peso_de_datos.py --nuevas-por-dia 1778`):

```
al día                     18.9 MB
al mes (30 días)          566.4 MB
al año                  6,890.7 MB

Con 5,113 filas hoy (54.3 MB), el histórico tardaría
en duplicarse unos 3 días.
```

Aun siendo un techo, cambia la conclusión de esta nota: **el histórico ya no «cabe en cualquier
servidor durante años»**. El relleno del año, medido, añade **~1 GB de golpe** (103.628 filas del
listado general). Y sigue siendo verdad lo que importa: esto no lo hacen crecer los usuarios, lo hace
crecer **cuántas filas nuevas publica la fuente**. Cerrar la cuenta es una consulta sobre
`primera_vez_visto` agrupada por día, y está pendiente.

El histórico está particionado por meses (`MESES_DE_PARTICION=3`), así que purgar es un `DROP
PARTITION` y no un `DELETE`; y si el ritmo aprieta, lo primero que sobra es guardar `crudo` entero
para todo el histórico en lugar de solo para los contratos recientes.

## El límite que de verdad importa

Conviene decirlo sin rodeos, porque es el que decide el producto y no la máquina: **la ingesta está
limitada por SERCOP, no por nosotros.** El worker es un solo proceso que hace como mucho
`PRESUPUESTO_PETICIONES_CICLO=60` peticiones cada quince minutos, y consulta veinte términos por
vuelta, los más olvidados primero. Con muchos clientes y cientos de palabras clave distintas, el
ciclo puede dejar de completarse a tiempo y las alertas llegarán tarde. Eso no se arregla con más
memoria: se arregla priorizando términos o hablando con la fuente.

## Cómo cerrar esta estimación

Con una prueba de carga, que es lo único que convierte lo de arriba en un hecho: levantar el
despliegue en la máquina real, simular **900 paneles** con el flujo de eventos abierto (no solo
peticiones sueltas: lo que se sospecha que limita son las conexiones, y una prueba sin flujo no lo
mide) y mirar dónde se llega primero. Los tres números que hay que observar son los descriptores
abiertos, la memoria de cada contenedor y las consultas por segundo de PostgreSQL.

El ensayo está pendiente y es el paso que sigue antes de prometer una cifra a un cliente.
