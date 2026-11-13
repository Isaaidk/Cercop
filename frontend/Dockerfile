# Panel servido desde el propio servidor, en lugar de desde Vercel.
#
# Para qué sirve este archivo, teniendo Vercel
# -------------------------------------------
# Vercel **no usa Dockerfiles** para un panel estático de Vite: lo compila con sus propios pasos de
# construcción y sirve la carpeta `dist` desde su red. Para ese camino, lo que hace falta es
# `vercel.json`, que está al lado de este archivo.
#
# Este Dockerfile es la otra opción: servir el panel desde el mismo servidor que el API. Se elige por
# tres razones concretas, no por gusto:
#
#   1. **Una cosa menos que puede fallar por fuera.** Con el panel aquí, hay un solo despliegue, un
#      solo sitio donde mirar cuando algo no va, y ningún CORS que configurar —el panel y el API
#      comparten origen—.
#   2. **La latencia deja de depender de un tercero.** El HTML y el JavaScript salen del mismo
#      servidor que las respuestas, en vez de cruzar a un CDN en otro país y volver.
#   3. **Se puede caer Vercel sin que el panel se caiga.**
#
# Lo que cuesta: se pierde el reparto global de la CDN y el certificado deja de ser de Vercel para
# serlo de Caddy (que lo renueva solo, así que no se pierde nada en realidad).
#
# Las dos opciones están soportadas y son intercambiables: la diferencia es dónde se ejecuta
# `npm run build`. Para usar esta, añadir el perfil `panel` al levantar (ver `deploy/README.md`).

# ---------------------------------------------------------------------------
# Etapa 1: compilar
# ---------------------------------------------------------------------------
# Se compila en una imagen con Node y el resultado se copia a una imagen de servidor. Así la imagen
# final no lleva Node, ni `node_modules` (45 MB), ni el código fuente: solo los archivos que el
# navegador descarga. Es la diferencia entre una imagen de ~50 MB y una de ~450 MB, y sobre todo la
# diferencia entre exponer o no las dependencias de desarrollo en el servidor.
FROM node:22-alpine AS compilacion

WORKDIR /panel

# Las dependencias primero: un cambio en un componente no obliga a reinstalar todo.
COPY package.json package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

COPY . .

# `VITE_API_BASE` se recibe como argumento de construcción porque Vite **incrusta** las variables de
# entorno en el momento de compilar: el valor queda escrito dentro del JavaScript. No es una
# variable de ejecución que se pueda cambiar al arrancar el contenedor, y confundirlo lleva a
# compilar un panel que llama a `localhost` sin que nada avise.
#
# El valor por defecto —vacío— deja las peticiones en el mismo origen, que es lo correcto cuando el
# panel y el API los sirve el mismo Caddy.
ARG VITE_API_BASE=""
ENV VITE_API_BASE=$VITE_API_BASE

RUN npm run build


# ---------------------------------------------------------------------------
# Etapa 2: servir
# ---------------------------------------------------------------------------
FROM caddy:2-alpine

# Solo los archivos compilados. Nada de código fuente ni de dependencias.
COPY --from=compilacion /panel/dist /srv

# La configuración se escribe aquí y no se copia de fuera para que este archivo se explique solo.
#
# `try_files` con `index.html` al final es lo que hace funcionar un panel de una sola página: las
# rutas del navegador no existen como archivos, así que cualquier ruta desconocida tiene que
# devolver el HTML y dejar que el JavaScript decida qué mostrar. Sin esto, recargar en una pantalla
# concreta devuelve un 404.
#
# Los `assets` llevan el hash del contenido en el nombre, así que se pueden cachear un año: si el
# contenido cambia, cambia el nombre y el navegador pide el nuevo. El `index.html` no, y por eso se
# sirve siempre revalidado — si se cacheara, un despliegue nuevo no llegaría a nadie hasta que
# caducara la caché.
RUN cat > /etc/caddy/Caddyfile <<'CONF'
:80 {
	root * /srv
	encode zstd gzip

	@estaticos path /assets/*
	header @estaticos Cache-Control "public, max-age=31536000, immutable"

	@html path / /index.html
	header @html Cache-Control "no-cache"

	# Cabeceras de seguridad del panel (docs/38, S-22).
	# - La CSP que se APLICA solo lleva lo que no puede romper la aplicación: nadie la enmarca
	#   (clickjacking), no hay plugins, no se cambia la base de las URL ni se envían formularios fuera.
	# - La CSP completa va en modo Report-Only: el navegador avisa en la consola de lo que bloquearía,
	#   sin bloquearlo. Cuando no haya avisos con el uso real (OCR, PDF, SRI, asistente), se pasa a
	#   aplicarla. El hash es el del script del tema en index.html: si ese script cambia, cambia.
	header {
		X-Content-Type-Options nosniff
		Referrer-Policy strict-origin-when-cross-origin
		X-Frame-Options DENY
		Strict-Transport-Security "max-age=31536000; includeSubDomains"
		Permissions-Policy "camera=(), geolocation=(), payment=(), usb=(), microphone=(self)"
		Cross-Origin-Opener-Policy same-origin
		Content-Security-Policy "frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action 'self'; upgrade-insecure-requests"
		Content-Security-Policy-Report-Only "default-src 'self'; script-src 'self' 'sha256-AVuBRSRnMelloLHdO6A8q89aJU6mdCnTTNrgK9zf7Tg=' https://cdn.jsdelivr.net 'wasm-unsafe-eval'; worker-src 'self' blob: https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self' https://*.up.railway.app https://srienlinea.sri.gob.ec https://datosabiertos.compraspublicas.gob.ec https://cdn.jsdelivr.net; frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action 'self'"
		-Server
	}

	try_files {path} /index.html
	file_server
}
CONF

EXPOSE 80
