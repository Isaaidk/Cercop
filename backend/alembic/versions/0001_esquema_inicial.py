"""Esquema inicial: plano compartido, plano de negocio y tablas particionadas.

Revision ID: 0001
Revises:
Create Date: 2026-09-27

Notas de diseño
---------------
* **Sin extensiones.** Se evita `pgcrypto` porque `gen_random_uuid()` es nativo desde PostgreSQL 13,
  y se evita `citext` usando un índice único sobre `lower(email)`. Esto elimina la dependencia de
  dónde instale las extensiones un proveedor gestionado como Supabase.
* **Dos planos.** Las tablas del plano compartido no llevan `negocio_id`: los datos del SERCOP son
  públicos e idénticos para todos los clientes, así que se ingestan una sola vez. El aislamiento se
  aplica al plano de negocio en la migración 0002.
* **Particionado mensual** en `registro_historial` y `auditoria`, con partición predeterminada para
  que una inserción nunca falle por falta de partición.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MESES_DE_PARTICION = 3

TABLAS_COMPARTIDAS = (
    "campo_pendiente",
    "campo_mapeo",
    "sincronizacion",
    "punto_contacto_entidad",
    "registro",
    "termino",
    "fuente",
)

TABLAS_DE_NEGOCIO = (
    "conjunto_termino",
    "conjunto_terminos",
    "suscripcion_termino",
    "filtro_guardado",
    "exportacion",
    "consentimiento",
    "solicitud_arco",
    "sesion",
    "usuario",
    "negocio",
)


def _particiones(rango: int = MESES_DE_PARTICION) -> list[tuple[str, str]]:
    """Nombre y límite superior de cada partición mensual, empezando por el mes en curso."""
    ahora = datetime.now(UTC)
    anio, mes = ahora.year, ahora.month
    resultado: list[tuple[str, str]] = []
    for desplazamiento in range(rango):
        total = (anio * 12 + (mes - 1)) + desplazamiento
        anio_particion, mes_particion = divmod(total, 12)
        mes_particion += 1
        siguiente = divmod(total + 1, 12)
        resultado.append(
            (
                f"{anio_particion}{mes_particion:02d}",
                f"{siguiente[0]}-{siguiente[1] + 1:02d}-01",
            )
        )
    return resultado


def _ejecutar(sql: str) -> None:
    """Ejecuta un bloque SQL **sentencia a sentencia**.

    El controlador asíncrono `asyncpg` no admite varias sentencias en una sola consulta preparada
    («cannot insert multiple commands into a prepared statement»), así que hay que partirlas. El SQL
    de esta migración no contiene `;` dentro de literales, por lo que dividir por `;` es seguro.
    """
    for sentencia in sql.split(";"):
        limpia = sentencia.strip()
        if limpia:
            op.execute(limpia)


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # Plano compartido — sin negocio_id: datos públicos, idénticos para todos
    # ------------------------------------------------------------------ #
    _ejecutar(
        """
        CREATE TABLE fuente (
            id                            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            codigo                        text NOT NULL UNIQUE,
            nombre                        text NOT NULL,
            endpoint_base                 text NOT NULL,
            activa                        boolean NOT NULL DEFAULT true,
            intervalo_min                 integer NOT NULL DEFAULT 15 CHECK (intervalo_min > 0),
            ventana_solape_ciclos         integer NOT NULL DEFAULT 2 CHECK (ventana_solape_ciclos > 0),
            presupuesto_peticiones_ciclo  integer NOT NULL DEFAULT 60 CHECK (presupuesto_peticiones_ciclo > 0),
            esquema_version               integer NOT NULL DEFAULT 1,
            hash_claves                   text,
            creado_en                     timestamptz NOT NULL DEFAULT now(),
            actualizado_en                timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE campo_mapeo (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            fuente_id       uuid NOT NULL REFERENCES fuente(id) ON DELETE CASCADE,
            clave_cruda     text NOT NULL,
            campo_canonico  text NOT NULL,
            etiqueta        text NOT NULL,
            tipo_dato       text NOT NULL CHECK (tipo_dato IN
                              ('texto','fecha','fecha_hora','numero','entero','booleano','moneda')),
            transformacion  jsonb NOT NULL DEFAULT '{}'::jsonb,
            requerido       boolean NOT NULL DEFAULT false,
            activo          boolean NOT NULL DEFAULT true,
            orden           integer NOT NULL DEFAULT 0,
            ancho_excel     integer,
            UNIQUE (fuente_id, clave_cruda)
        );

        CREATE TABLE campo_pendiente (
            id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            fuente_id           uuid NOT NULL REFERENCES fuente(id) ON DELETE CASCADE,
            clave_cruda         text NOT NULL,
            valor_ejemplo       text,
            veces_visto         integer NOT NULL DEFAULT 1,
            primer_detectado_en timestamptz NOT NULL DEFAULT now(),
            ultimo_detectado_en timestamptz NOT NULL DEFAULT now(),
            mapeo_id            uuid REFERENCES campo_mapeo(id) ON DELETE SET NULL,
            resuelto_en         timestamptz,
            UNIQUE (fuente_id, clave_cruda)
        );

        CREATE TABLE termino (
            id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            texto             text NOT NULL,
            texto_normalizado text NOT NULL UNIQUE,
            origen            text NOT NULL DEFAULT 'usuario' CHECK (origen IN ('admin','usuario')),
            activo            boolean NOT NULL DEFAULT true,
            prioridad         integer NOT NULL DEFAULT 0,
            ultima_ingesta_en timestamptz,
            creado_en         timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE registro (
            id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            fuente_id         uuid NOT NULL REFERENCES fuente(id) ON DELETE CASCADE,
            clave_natural     text NOT NULL,
            datos             jsonb NOT NULL DEFAULT '{}'::jsonb,
            crudo             jsonb NOT NULL DEFAULT '{}'::jsonb,
            texto_busqueda    text NOT NULL DEFAULT '',
            hash_contenido    text NOT NULL,
            fecha_publicacion timestamptz,
            primera_vez_visto timestamptz NOT NULL DEFAULT now(),
            ultima_vez_visto  timestamptz NOT NULL DEFAULT now(),
            es_vigente        boolean NOT NULL DEFAULT true,
            terminos_ids      uuid[] NOT NULL DEFAULT '{}',
            UNIQUE (fuente_id, clave_natural)
        );
        CREATE INDEX ix_registro_fecha  ON registro (fuente_id, fecha_publicacion DESC);
        CREATE INDEX ix_registro_datos  ON registro USING gin (datos);
        CREATE INDEX ix_registro_nuevos ON registro (primera_vez_visto DESC) WHERE es_vigente;

        CREATE TABLE sincronizacion (
            id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            fuente_id        uuid NOT NULL REFERENCES fuente(id) ON DELETE CASCADE,
            iniciada_en      timestamptz NOT NULL DEFAULT now(),
            terminada_en     timestamptz,
            estado           text NOT NULL DEFAULT 'en_curso'
                               CHECK (estado IN ('en_curso','ok','parcial','error')),
            watermark_fecha  timestamptz,
            peticiones       integer NOT NULL DEFAULT 0,
            nuevos           integer NOT NULL DEFAULT 0,
            actualizados     integer NOT NULL DEFAULT 0,
            errores          integer NOT NULL DEFAULT 0,
            avisos           jsonb NOT NULL DEFAULT '[]'::jsonb
        );
        CREATE INDEX ix_sincronizacion_fuente ON sincronizacion (fuente_id, iniciada_en DESC);
        """
    )

    # ------------------------------------------------------------------ #
    # Plano de negocio — aislamiento por RLS en la migración 0002
    # ------------------------------------------------------------------ #
    _ejecutar(
        """
        CREATE TABLE negocio (
            id                              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            nombre                          text NOT NULL,
            ruc                             text,
            estado                          text NOT NULL DEFAULT 'prueba'
                                              CHECK (estado IN ('prueba','activo','suspendido','cancelado')),
            plan                            text NOT NULL DEFAULT 'base',
            limite_usuarios                 integer NOT NULL DEFAULT 5,
            limite_exportaciones_dia        integer NOT NULL DEFAULT 20,
            max_sesiones_usuario            integer NOT NULL DEFAULT 2 CHECK (max_sesiones_usuario > 0),
            retencion_dias_datos_personales integer NOT NULL DEFAULT 365
                                              CHECK (retencion_dias_datos_personales > 0),
            creado_en                       timestamptz NOT NULL DEFAULT now(),
            eliminacion_programada_en       timestamptz
        );

        CREATE TABLE usuario (
            id                          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            negocio_id                  uuid NOT NULL REFERENCES negocio(id) ON DELETE CASCADE,
            email                       text NOT NULL,
            hash_password               text NOT NULL,
            nombre                      text NOT NULL DEFAULT '',
            rol                         text NOT NULL DEFAULT 'consultor'
                                          CHECK (rol IN ('super_admin','admin_negocio','consultor','lector')),
            estado                      text NOT NULL DEFAULT 'pendiente'
                                          CHECK (estado IN ('activo','inactivo','bloqueado','pendiente')),
            intentos_fallidos           integer NOT NULL DEFAULT 0,
            bloqueado_hasta             timestamptz,
            ultimo_acceso               timestamptz,
            debe_aceptar_politica_version integer,
            creado_en                   timestamptz NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX ux_usuario_email_negocio ON usuario (negocio_id, lower(email));
        CREATE INDEX ix_usuario_email ON usuario (lower(email));

        CREATE TABLE sesion (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            negocio_id      uuid NOT NULL REFERENCES negocio(id) ON DELETE CASCADE,
            usuario_id      uuid NOT NULL REFERENCES usuario(id) ON DELETE CASCADE,
            refresh_hash    text NOT NULL,
            dispositivo     text,
            ip              inet,
            user_agent      text,
            creada_en       timestamptz NOT NULL DEFAULT now(),
            ultimo_uso_en   timestamptz NOT NULL DEFAULT now(),
            expira_en       timestamptz NOT NULL,
            estado          text NOT NULL DEFAULT 'activa'
                              CHECK (estado IN ('activa','inactiva','revocada','expirada','reemplazada')),
            revocada_motivo text CHECK (revocada_motivo IN
                              ('logout','eviccion','admin','reuso_detectado','cierre_ventana'))
        );
        CREATE INDEX ix_sesion_usuario ON sesion (usuario_id, estado, ultimo_uso_en);

        CREATE TABLE suscripcion_termino (
            id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            negocio_id uuid NOT NULL REFERENCES negocio(id) ON DELETE CASCADE,
            termino_id uuid NOT NULL REFERENCES termino(id) ON DELETE CASCADE,
            activa     boolean NOT NULL DEFAULT true,
            creada_en  timestamptz NOT NULL DEFAULT now(),
            UNIQUE (negocio_id, termino_id)
        );

        CREATE TABLE conjunto_terminos (
            id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            negocio_id uuid NOT NULL REFERENCES negocio(id) ON DELETE CASCADE,
            usuario_id uuid REFERENCES usuario(id) ON DELETE CASCADE,
            nombre     text NOT NULL,
            compartido boolean NOT NULL DEFAULT false,
            creado_en  timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE conjunto_termino (
            conjunto_id uuid NOT NULL REFERENCES conjunto_terminos(id) ON DELETE CASCADE,
            termino_id  uuid NOT NULL REFERENCES termino(id) ON DELETE CASCADE,
            PRIMARY KEY (conjunto_id, termino_id)
        );

        CREATE TABLE filtro_guardado (
            id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            negocio_id uuid NOT NULL REFERENCES negocio(id) ON DELETE CASCADE,
            usuario_id uuid REFERENCES usuario(id) ON DELETE CASCADE,
            nombre     text NOT NULL,
            fuente_id  uuid REFERENCES fuente(id) ON DELETE SET NULL,
            criterios  jsonb NOT NULL DEFAULT '{}'::jsonb,
            compartido boolean NOT NULL DEFAULT false,
            creado_en  timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE exportacion (
            id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            negocio_id           uuid NOT NULL REFERENCES negocio(id) ON DELETE CASCADE,
            usuario_id           uuid REFERENCES usuario(id) ON DELETE SET NULL,
            fuente_id            uuid REFERENCES fuente(id) ON DELETE SET NULL,
            modo                 text NOT NULL CHECK (modo IN ('criterios','seleccion')),
            criterios            jsonb NOT NULL DEFAULT '{}'::jsonb,
            claves_seleccionadas text[] NOT NULL DEFAULT '{}',
            estado               text NOT NULL DEFAULT 'en_cola'
                                   CHECK (estado IN ('en_cola','generando','listo','error','expirado')),
            filas                integer,
            archivo_ruta         text,
            archivo_bytes        bigint,
            expira_en            timestamptz,
            creado_en            timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE consentimiento (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            negocio_id    uuid NOT NULL REFERENCES negocio(id) ON DELETE CASCADE,
            usuario_id    uuid NOT NULL REFERENCES usuario(id) ON DELETE CASCADE,
            tipo          text NOT NULL CHECK (tipo IN
                            ('terminos_uso','aviso_privacidad','tratamiento_datos')),
            version_texto text NOT NULL,
            texto_hash    text NOT NULL,
            aceptado_en   timestamptz NOT NULL DEFAULT now(),
            revocado_en   timestamptz,
            ip            inet,
            user_agent    text,
            metodo        text NOT NULL DEFAULT 'formulario' CHECK (metodo IN ('formulario','api'))
        );
        CREATE INDEX ix_consentimiento_usuario ON consentimiento (usuario_id, tipo);

        CREATE TABLE solicitud_arco (
            id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            negocio_id         uuid NOT NULL REFERENCES negocio(id) ON DELETE CASCADE,
            tipo               text NOT NULL CHECK (tipo IN
                                 ('acceso','rectificacion','cancelacion','oposicion','portabilidad')),
            titular_email_hash text NOT NULL,
            estado             text NOT NULL DEFAULT 'recibida'
                                 CHECK (estado IN ('recibida','en_tramite','respondida','rechazada')),
            recibida_en        timestamptz NOT NULL DEFAULT now(),
            vence_en           timestamptz NOT NULL,
            respondida_en      timestamptz,
            fundamento         text
        );
        """
    )

    # ------------------------------------------------------------------ #
    # Datos personales: tabla aparte, cifrada, con permisos y retención propios
    # ------------------------------------------------------------------ #
    _ejecutar(
        """
        CREATE TABLE punto_contacto_entidad (
            id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            registro_id      uuid NOT NULL REFERENCES registro(id) ON DELETE CASCADE,
            nombre_cifrado   bytea,
            email_cifrado    bytea,
            telefono_cifrado bytea,
            clave_id         integer NOT NULL DEFAULT 1,
            hash_busqueda    bytea,
            vigente_hasta    timestamptz,
            creado_en        timestamptz NOT NULL DEFAULT now(),
            UNIQUE (registro_id)
        );
        CREATE INDEX ix_contacto_hash ON punto_contacto_entidad (hash_busqueda);
        CREATE INDEX ix_contacto_vigencia ON punto_contacto_entidad (vigente_hasta);

        CREATE TABLE politica_version (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tipo          text NOT NULL,
            version       integer NOT NULL CHECK (version > 0),
            texto         text NOT NULL,
            hash          text NOT NULL,
            vigente_desde timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tipo, version)
        );
        """
    )

    # ------------------------------------------------------------------ #
    # Tablas particionadas por mes (histórico y auditoría crecen sin fin)
    # ------------------------------------------------------------------ #
    _ejecutar(
        """
        CREATE TABLE registro_historial (
            id             bigserial,
            registro_id    uuid NOT NULL,
            datos          jsonb NOT NULL,
            hash_contenido text NOT NULL,
            detectado_en   timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (id, detectado_en)
        ) PARTITION BY RANGE (detectado_en);
        CREATE INDEX ix_historial_registro ON registro_historial (registro_id, detectado_en DESC);
        CREATE TABLE registro_historial_predeterminada
            PARTITION OF registro_historial DEFAULT;

        CREATE TABLE auditoria (
            id          bigserial,
            negocio_id  uuid,
            usuario_id  uuid,
            accion      text NOT NULL,
            entidad     text,
            entidad_id  text,
            resultado   text,
            ip          inet,
            user_agent  text,
            detalle     jsonb NOT NULL DEFAULT '{}'::jsonb,
            ocurrido_en timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (id, ocurrido_en)
        ) PARTITION BY RANGE (ocurrido_en);
        CREATE INDEX ix_auditoria_negocio ON auditoria (negocio_id, ocurrido_en DESC);
        CREATE TABLE auditoria_predeterminada PARTITION OF auditoria DEFAULT;
        """
    )

    for sufijo, limite in _particiones():
        op.execute(
            f"CREATE TABLE registro_historial_{sufijo} PARTITION OF registro_historial "
            f"FOR VALUES FROM ('{sufijo[:4]}-{sufijo[4:]}-01') TO ('{limite}');"
        )
        op.execute(
            f"CREATE TABLE auditoria_{sufijo} PARTITION OF auditoria "
            f"FOR VALUES FROM ('{sufijo[:4]}-{sufijo[4:]}-01') TO ('{limite}');"
        )


def downgrade() -> None:
    for sufijo, _ in _particiones():
        op.execute(f"DROP TABLE IF EXISTS registro_historial_{sufijo};")
        op.execute(f"DROP TABLE IF EXISTS auditoria_{sufijo};")

    op.execute("DROP TABLE IF EXISTS auditoria CASCADE;")
    op.execute("DROP TABLE IF EXISTS registro_historial CASCADE;")
    op.execute("DROP TABLE IF EXISTS politica_version CASCADE;")
    op.execute("DROP TABLE IF EXISTS punto_contacto_entidad CASCADE;")

    for tabla in TABLAS_DE_NEGOCIO:
        op.execute(f"DROP TABLE IF EXISTS {tabla} CASCADE;")

    op.execute("DROP TABLE IF EXISTS sincronizacion CASCADE;")
    op.execute("DROP TABLE IF EXISTS registro CASCADE;")
    op.execute("DROP TABLE IF EXISTS termino CASCADE;")
    op.execute("DROP TABLE IF EXISTS campo_pendiente CASCADE;")
    op.execute("DROP TABLE IF EXISTS campo_mapeo CASCADE;")
    op.execute("DROP TABLE IF EXISTS fuente CASCADE;")


# Referencia usada por las pruebas de estructura.
TABLAS_ESPERADAS = TABLAS_COMPARTIDAS + TABLAS_DE_NEGOCIO
