# Panel de contratación pública

Panel de seguimiento de contrataciones del SERCOP: filtra por palabra clave, provincia, estado y
fechas; resume en gráficas interactivas y en un mapa del Ecuador por provincias, y permite agregar
palabras clave desde el propio filtro.

Vue 3 (`<script setup>`) · Vite 6 · Chart.js 4 · sin biblioteca de interfaz: los estilos son
variables de CSS y componentes propios.

---

## Requisitos

| | Versión | Nota |
| --- | --- | --- |
| Node.js | **20 o superior** | Está declarado en `engines`. Vite 6 lo exige. |
| npm | 10 o superior | Se usa `npm ci`, que necesita un bloqueo de versiones `lockfileVersion 3`. |

No hace falta ninguna herramienta global: Vite vive en las dependencias del proyecto.

---

## Puesta en marcha en local

El panel **no funciona solo**: necesita la API. Primero el backend (`backend/README.md`), que se
levanta en el puerto **8001**:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
uvicorn contratacion.asgi:app --port 8001 --reload
```

Y después el panel, en otra terminal:

```powershell
cd frontend
npm ci
npm run dev          # http://localhost:5174
```

### Por qué el panel usa el puerto 5174

El 5173 lo ocupa la aplicación anterior, que sigue en servicio en `Consultoria/view/frontend`. Se
cambió para que las dos puedan estar levantadas a la vez sin pelearse por el puerto.

### Por qué en desarrollo no hace falta configurar la dirección de la API

En desarrollo, Vite **reenvía** `/v1`, `/salud` y `/listo` a `http://127.0.0.1:8001`. El navegador
cree que habla con su propio origen, así que no hay petición previa de permiso ni lista de orígenes
permitidos de por medio, que son las dos cosas que más se rompen al empezar. Esto está en
`vite.config.js`.

Si la API está en otro sitio, se cambia sin tocar el archivo:

```powershell
$env:VITE_API_PROXY = "http://127.0.0.1:9000"
npm run dev
```

---

## Variables de entorno

Están todas en `.env.example`. Copia el archivo a `.env` solo si necesitas cambiar algún valor por
defecto.

| Variable | Por defecto | Para qué |
| --- | --- | --- |
| `VITE_API_BASE` | vacío | Dirección de la API **en producción**. Vacío significa «el mismo origen», que es lo correcto en desarrollo porque el proxy se encarga. |
| `VITE_API_PROXY` | `http://127.0.0.1:8001` | Destino del proxy de desarrollo. Solo afecta a `npm run dev`. |
| `VITE_DATOS_DEMO` | activado | `0` lo apaga. Rellena las gráficas con datos inventados **solo cuando la API responde con cero resultados**, para poder revisar el diseño de un histórico todavía vacío. Mientras está activo, el panel muestra un aviso. |

> **Importante:** Vite **incrusta** las variables `VITE_*` en el código al compilar, no las lee al
> ejecutar. Por eso `VITE_API_BASE` tiene que estar puesta **en el momento de compilar**, en el
> entorno de construcción del alojamiento. Cambiarla después no tiene ningún efecto: habría que
> volver a compilar. Es el error más habitual al desplegar un panel de Vite.

En un despliegue real, `VITE_DATOS_DEMO=0` es lo recomendable. Los datos de ejemplo están pensados
para revisar el diseño, no para enseñárselos a nadie como si fueran contrataciones reales.

---

## Comandos

| Comando | Qué hace |
| --- | --- |
| `npm run dev` | Servidor de desarrollo con recarga en caliente, puerto 5174. |
| `npm run build` | Compila a `dist/`. Es lo que se publica. |
| `npm run preview` | Sirve `dist/` en el puerto 4173, para comprobar el resultado compilado antes de publicarlo. |
| `npm run revisar` | Compila y sirve, en un solo paso. |

`preview` **no** reenvía `/v1` a la API, así que en esa vista el panel mostrará «La API no responde»
a menos que `VITE_API_BASE` apunte a una API real y esa API tenga este origen entre los permitidos.

---

## Despliegue

### El directorio del proyecto es `frontend/`

Al configurar el alojamiento, el directorio raíz del proyecto tiene que ser **`frontend`**, no la
raíz del repositorio. Es el punto que más problemas da:

- Los archivos que hay que publicar son `frontend/dist`.
- En la raíz del repositorio hay un `package.json`, así que las plataformas que detectan Node por su
  presencia —Vercel, Netlify, Render, Railway— tienden a tratar **todo el repositorio** como una
  aplicación de Node. Sus scripts ya delegan en `frontend/`, pero la carpeta de salida seguiría sin
  ser la correcta. Configurar el directorio evita la ambigüedad.

| Ajuste | Valor |
| --- | --- |
| Directorio raíz | `frontend` |
| Comando de instalación | `npm ci` |
| Comando de compilación | `npm run build` |
| Carpeta de publicación | `dist` |
| Versión de Node | 20 o superior |

### CORS: la API tiene que conocer este origen

El panel habla con la API desde otro origen, así que `CORS_ORIGINS` en el backend tiene que incluir
la dirección exacta donde quede publicado el panel:

```env
CORS_ORIGINS=https://panel.midominio.ec
```

`CORS_ORIGINS` **rechaza el comodín `*`** a propósito: con `*` cualquier sitio podría hacer
peticiones con las credenciales del usuario. Si el navegador muestra un error de CORS y la respuesta
no llega, casi siempre es esta variable. La dirección debe escribirse **sin barra al final**.

### No hace falta reescribir rutas

El panel no tiene enrutador de cliente: es una sola página con pestañas que se cambian en memoria.
Por eso no hace falta la regla de reescritura hacia `index.html` que suelen necesitar las
aplicaciones de una sola página.

### Si se publica en un subdirectorio

El mapa se carga con una dirección construida a partir de `import.meta.env.BASE_URL`, de modo que
sigue funcionando si el panel no cuelga de la raíz del dominio. En ese caso hay que compilar con la
base correspondiente:

```powershell
npm run build -- --base=/panel/
```

### Aviso al instalar dependencias

Con npm 11 aparece este aviso durante `npm ci`:

```text
npm warn install-scripts   esbuild@0.25.12 (postinstall: node install.js)
```

**No es un error.** npm 11 pide autorización explícita para los guiones de instalación de los
paquetes; esbuild los usa para colocar su binario según el sistema. La compilación funciona igual, y
así queda comprobado: el resultado de `npm run build` es el mismo antes y después del aviso. Si el
aviso molesta o si el binario no llegara a instalarse, se autoriza con
`npm install-scripts approve esbuild`.

---

## Estructura

```
src/
├── api/            Cliente HTTP y lista de rutas de la API
├── assets/         Sistema de diseño: variables, componentes y animaciones
├── components/     Pantallas, panel, gráficas, mapa y tabla
├── composables/    Envoltorio de Chart.js y canal de presencia
├── stores/         Sesión, filtros y datos
└── utils/          Formato, provincias y proyección del mapa
public/data/        Mapa del Ecuador (GeoJSON), se descarga en tiempo de ejecución
```

### Cuatro decisiones que conviene conocer antes de tocar el código

**Los filtros viven en un almacén, no en los componentes.** La tabla, las gráficas y el mapa leen
el mismo estado. Si cada pestaña guardara el suyo, cambiar de pestaña perdería la búsqueda y las
tres vistas podrían mostrar conjuntos distintos del mismo filtro.

**Quien decide si faltan los términos y condiciones es el servidor, siempre.** El panel no deduce
«ya está aceptado» de ninguna marca guardada en el navegador: si lo hiciera, bastaría con editar esa
marca para entrar sin aceptar, y una versión nueva de los términos publicada un día cualquiera no se
detectaría.

**El token de acceso no se guarda.** Vive en memoria. El de renovación va en `sessionStorage`, que
se borra al cerrar el navegador: es una decisión de persistencia, no de inmunidad frente a un ataque.
Las renovaciones se agrupan en una sola petición porque **el token de renovación rota en cada uso**;
sin esa precaución, varias peticiones simultáneas con el token caducado parecerían dos copias en
circulación y el servidor cerraría todas las sesiones de la cuenta.

**El mapa tiene dos proyecciones.** Galápagos está a unos mil kilómetros del continente: encuadrado
todo junto, el continente queda reducido a una franja. Se dibuja en un recuadro aparte, como en los
mapas oficiales del Ecuador.

---

## Comprobación antes de publicar

```powershell
npm ci
npm run build
npm run preview      # http://localhost:4173
```

El mismo par de pasos —instalación limpia y compilación— se ejecuta en integración continua con cada
cambio, y además se comprueba que el mapa haya llegado a `dist/data/`.
