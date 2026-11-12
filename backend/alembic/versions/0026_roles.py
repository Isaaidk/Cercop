"""Tres roles en tablas, y el catálogo anterior migrado.

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-09

`usuario.rol` deja de ser un texto con un CHECK de cuatro valores. Pasa a apuntar a `rol`, y los
permisos de cada rol quedan en `rol_permiso`. Las filas existentes se traducen antes de crear la
clave foránea: `admin_negocio` pasa a dueño, y `consultor` y `lector` pasan a usuario.
`super_admin` no se toca.

La matriz de permisos tiene que coincidir con `PERMISOS_POR_ROL` en `dominio/roles.py`. Autorizar
lee esa matriz; estas tablas son el catálogo que se puede consultar y ampliar.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ejecutar(sql: str) -> None:
    for sentencia in sql.split(";"):
        limpia = sentencia.strip()
        if limpia:
            op.execute(limpia)


def upgrade() -> None:
    _ejecutar(
        """
        CREATE TABLE rol (
            codigo text PRIMARY KEY,
            nombre text NOT NULL,
            descripcion text NOT NULL,
            es_plataforma boolean NOT NULL DEFAULT false,
            asignable_por_dueno boolean NOT NULL DEFAULT false
        );

        CREATE TABLE permiso (
            codigo text PRIMARY KEY,
            modulo text NOT NULL,
            descripcion text NOT NULL
        );

        CREATE TABLE rol_permiso (
            rol_codigo text NOT NULL REFERENCES rol(codigo),
            permiso_codigo text NOT NULL REFERENCES permiso(codigo),
            PRIMARY KEY (rol_codigo, permiso_codigo)
        );

        INSERT INTO rol (codigo, nombre, descripcion, es_plataforma, asignable_por_dueno) VALUES
            ('super_admin', 'Superadministrador',
             'Administra la plataforma y puede actuar sobre cualquier empresa.', true, false),
            ('dueno_empresa', 'Dueño de la empresa',
             'Administra los usuarios y el perfil de su empresa. No concede plazos.', false, false),
            ('usuario', 'Usuario',
             'Consulta, filtra y exporta dentro de su empresa.', false, true);

        INSERT INTO permiso (codigo, modulo, descripcion) VALUES
            ('empresas.gestionar', 'plataforma', 'Crear y administrar empresas.'),
            ('plazos.conceder', 'accesos', 'Conceder o ampliar el plazo de uso.'),
            ('usuarios.gestionar', 'usuarios', 'Crear y dar de baja usuarios de la empresa.'),
            ('usuarios.desbloquear', 'usuarios', 'Quitar el bloqueo por intentos fallidos.'),
            ('exportar', 'datos', 'Descargar el historico.'),
            ('tdr.ver', 'tdr', 'Ver el TDR de una infima.'),
            ('tdr.rellenar', 'tdr', 'Armar el borrador de oferta con el perfil.'),
            ('empresa.editar_perfil', 'empresa', 'Editar el perfil con el que se rellenan los TDR.'),
            ('vistas.necesidades', 'datos', 'Consultar las vistas de datos concedidas.');

        INSERT INTO rol_permiso (rol_codigo, permiso_codigo)
        SELECT 'super_admin', codigo FROM permiso;

        INSERT INTO rol_permiso (rol_codigo, permiso_codigo) VALUES
            ('dueno_empresa', 'usuarios.gestionar'),
            ('dueno_empresa', 'usuarios.desbloquear'),
            ('dueno_empresa', 'exportar'),
            ('dueno_empresa', 'tdr.ver'),
            ('dueno_empresa', 'tdr.rellenar'),
            ('dueno_empresa', 'empresa.editar_perfil'),
            ('dueno_empresa', 'vistas.necesidades'),
            ('usuario', 'exportar'),
            ('usuario', 'tdr.ver'),
            ('usuario', 'vistas.necesidades');

        UPDATE usuario SET rol = 'dueno_empresa' WHERE rol = 'admin_negocio';
        UPDATE usuario SET rol = 'usuario' WHERE rol IN ('consultor', 'lector');

        ALTER TABLE usuario DROP CONSTRAINT IF EXISTS usuario_rol_check;
        ALTER TABLE usuario
            ADD CONSTRAINT usuario_rol_fk FOREIGN KEY (rol) REFERENCES rol(codigo);
        """
    )


def downgrade() -> None:
    _ejecutar(
        """
        ALTER TABLE usuario DROP CONSTRAINT IF EXISTS usuario_rol_fk;
        UPDATE usuario SET rol = 'admin_negocio' WHERE rol = 'dueno_empresa';
        UPDATE usuario SET rol = 'consultor' WHERE rol = 'usuario';
        ALTER TABLE usuario
            ADD CONSTRAINT usuario_rol_check
            CHECK (rol IN ('super_admin', 'admin_negocio', 'consultor', 'lector'));
        DROP TABLE IF EXISTS rol_permiso;
        DROP TABLE IF EXISTS permiso;
        DROP TABLE IF EXISTS rol;
        """
    )
