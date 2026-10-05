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

# Las dependencias se instalan antes de copiar el código: así un cambio en un módulo no invalida la
# capa de dependencias y el despliegue no reinstala todo cada vez.
COPY pyproject.toml ./
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./

RUN pip install --upgrade pip && pip install .

# El proceso corre sin privilegios. Un contenedor como root convierte cualquier fallo de una
# dependencia en un fallo de la máquina que lo hospeda.
RUN useradd --create-home --uid 10001 app && chown -R app:app /app
USER app

# `--workers` se pasa en el `compose` y no se fija aquí: el número de procesos depende de los
# núcleos de la máquina y del tamaño del pool contra PostgreSQL, y son decisiones de despliegue. Un
# valor escrito en la imagen sería el mismo en todos los hosts y nadie podría ajustarlo.
EXPOSE 8001

CMD ["uvicorn", "contratacion.asgi:app", "--host", "0.0.0.0", "--port", "8001"]
