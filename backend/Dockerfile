# Imagen del API y del worker de ingesta.
#
# Los dos procesos salen de la misma imagen a propósito: comparten código y dependencias, y
# separarlos en dos imágenes solo garantizaría que un día llevaran versiones distintas del mismo
# paquete, con un fallo que aparecería únicamente en uno de los dos.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Tailscale, para poder salir por un nodo externo.
#
# Existe por una sola razón: el servidor del listado de necesidades
# (`www.compraspublicas.gob.ec`) descarta en silencio las conexiones que llegan de centros de datos,
# y desde Railway eso se ve como `ConnectTimeout` tras dos minutos de espera, sin que el portal
# llegue a ver la petición. Los datos abiertos (OCDS), que son otro servidor del mismo portal, no
# hacen eso: por eso el túnel solo lo usa NCO.
#
# Se instala **aquí arriba**, antes de copiar el código, por la misma razón que las dependencias: es
# una capa que casi nunca cambia, y cuanto más arriba esté menos veces se reconstruye. Bajarla hasta
# el `USER app` obligaría a repetir la descarga —y a esperarla— cada vez que se toca un módulo.
#
# Necesita root para instalarse, y el `USER app` de más abajo llega después: no hay conflicto.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSL https://tailscale.com/install.sh | sh \
    && rm -rf /var/lib/apt/lists/*

# Las dependencias se instalan antes de copiar el código: así un cambio en un módulo no invalida la
# capa de dependencias y el despliegue no reinstala todo cada vez.
COPY pyproject.toml ./
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./

RUN pip install --upgrade pip && pip install .

# Las herramientas de operación (`scripts/`): no las necesita el proceso para atender, pero sí quien
# administra el despliegue. Crear el superadministrador, mirar cuánto pesa la base o comprobar las
# conexiones se hace **desde dentro** del contenedor —su consola—, donde la base se llama por su
# nombre interno: así no hay que abrir ninguna puerta hacia internet ni sacar la contraseña de la
# base de su plataforma.
#
# Va **después** de instalar las dependencias, y no antes como el código: un cambio en un guion no
# tiene por qué hacer que la siguiente construcción reinstale el paquete entero.
COPY scripts ./scripts

# El arranque con túnel. No es obligatorio: sin él el contenedor se comporta como siempre. Se usa
# cuando el servicio necesita salir por un nodo de Tailscale, y se pasa el comando real como
# argumentos:
#
#     sh /app/start.sh python -m contratacion.tareas.worker
#
# Se ejecuta con `sh` y no como binario, así que el permiso de ejecución no es imprescindible; se le
# da igualmente para que nadie tenga que averiguarlo.
COPY start.sh ./start.sh

# El proceso corre sin privilegios. Un contenedor como root convierte cualquier fallo de una
# dependencia en un fallo de la máquina que lo hospeda.
RUN useradd --create-home --uid 10001 app && chmod +x start.sh && chown -R app:app /app

# El directorio de las plantillas se crea **aquí y con este dueño**, y no lo crea el volumen.
#
# El `compose` monta un volumen con nombre en esta ruta. Un volumen hereda el contenido y el dueño
# del directorio de la imagen **si ese directorio existe**; si no existe, Docker lo crea como
# `root:root` y el proceso —que corre sin privilegios— no puede escribir en él. El síntoma aparece
# en el primer despliegue y no en desarrollo: subir la plantilla de Excel falla con un error de
# permisos, y la empresa no puede configurar su exportación.
RUN mkdir -p /app/plantillas && chown app:app /app/plantillas

USER app

# `--workers` se pasa en el `compose` y no se fija aquí: el número de procesos depende de los
# núcleos de la máquina y del tamaño del pool contra PostgreSQL, y son decisiones de despliegue. Un
# valor escrito en la imagen sería el mismo en todos los hosts y nadie podría ajustarlo.
EXPOSE 8001

# El comando por defecto sigue siendo el API, que es lo que necesita el servicio `api`.
#
# El `worker` —y el API, si algún día necesitara el túnel— lo sustituyen desde la configuración del
# servicio, pasándole a `start.sh` el comando real, que termina en `exec "$@"`:
#
#     sh /app/start.sh python -m contratacion.tareas.worker
#     sh /app/start.sh sh -c "alembic upgrade head && exec uvicorn …"
#
# El `exec` no es un detalle: hace que el proceso sustituya al guion, así que recibe las señales de
# parada del contenedor y la plataforma puede reiniciarlo con limpieza en vez de matarlo.
CMD ["uvicorn", "contratacion.asgi:app", "--host", "0.0.0.0", "--port", "8001"]
