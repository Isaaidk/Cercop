# Prueba de carga del panel

Mide **cuántas personas pueden estar dentro del panel a la vez**, que no es lo mismo que cuántas
peticiones por segundo aguanta el API. Cada usuario virtual hace lo que hace una persona: mira la
tabla, pide las gráficas, comprueba si hay datos nuevos y vuelve a empezar unos segundos después.

## Cómo se ejecuta

```powershell
# 1. Las cuentas (una vez). Cada usuario virtual tiene su cuenta y su negocio.
cd backend
.\.venv\Scripts\python.exe scripts\preparar_carga.py --usuarios 1000

# 2. La escalera completa, hasta 1.000 usuarios, desde la raíz del repositorio
cd ..
k6 run -e BASE_URL=http://127.0.0.1:8001 carga/panel.js

# 3. Un escalón concreto, para repetir una medida
k6 run -e BASE_URL=http://127.0.0.1:8001 -e VUS=500 -e DURACION=3m carga/panel.js

# 4. Y a dejarlo como estaba
cd backend
.\.venv\Scripts\python.exe scripts\preparar_carga.py --borrar
```

k6 se instala aparte (`winget install GrafanaLabs.k6`, o el `.zip` de sus publicaciones si no se
tienen permisos de administrador). El guion se ejecuta **desde la raíz del repositorio**: escribe
`carga/resultado.json` y k6 no crea la carpeta.

## Qué hay que mirar del resultado

El resumen que imprime k6 al terminar trae cuatro series, y **no se pueden promediar entre ellas**:

| Serie | Qué es | Meta |
|---|---|---|
| `tabla` | La página de resultados con filtros | mediana < 300 ms |
| `graficas` | El reparto por provincia, el mes y las fuentes | mediana < 300 ms |
| `version` | «¿hay datos nuevos?», una lectura de caché de un número | mediana < 300 ms |
| `termino` | La búsqueda por palabra clave, que **no se cachea nunca** | p95 < 1,5 s |

La meta de 300 ms es la de una consulta **servida de la caché**. Cuando la ingesta cierra un ciclo,
la generación cambia y la siguiente consulta de cada combinación de filtros vuelve a la base: eso
cuesta segundos y es normal, no un fallo. Por eso lo que se vigila de las lecturas cacheadas es la
**mediana** y no el p95 —con mil usuarios y una invalidación cada cuarto de hora siempre hay consultas
frías— y el p95 queda acotado por la meta de una consulta a la base (`RNF-02`).

## El entorno decide el resultado

Esto es lo que hay que tener claro antes de creerse un número:

- En **desarrollo** el Redis y el PostgreSQL son **gestionados y remotos**. Medido: una consulta que
  se sirve de la caché tarda **1,4–2,1 s** porque cada acierto es un viaje de ida y vuelta a
  `…db.redis.io`, y una consulta a la base ronda los 350–400 ms por viaje. Con eso, cualquier cifra
  de latencia mide la red, no el aplicativo.
- En el **despliegue** (`deploy/docker-compose.yml`) los dos son locales, con lo que la misma
  consulta cacheada es de milisegundos. La prueba se corre **allí** para responder «cuántos usuarios
  aguanta»; desde desarrollo solo se puede comprobar que no se rompe y que no hay errores.
- El API de desarrollo lleva **un** proceso de uvicorn; el despliegue lleva tantos como núcleos
  (`API_WORKERS`). Otra razón por la que los dos números no son comparables.

## Detalles que importan

- **Las cuentas se crean fuera de la prueba.** Iniciar sesión cuesta Argon2, que es lento a
  propósito; dentro de la prueba mediría el inicio de sesión y no el panel.
- **Cada usuario virtual tiene su cuenta.** El panel solo permite dos sesiones por cuenta: con una
  sola, mil usuarios se expulsarían entre ellos y lo que se mediría es la evicción.
- **El token de acceso caduca en minutos**, así que el guion renueva con el de renovación como lo hace
  el panel —con la rotación incluida— cuando recibe un 401.
- `carga/credenciales.json` lleva **credenciales de verdad**: no se sube al repositorio y se borra
  cuando termina la prueba.
