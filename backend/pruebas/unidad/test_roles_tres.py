"""Los tres roles y la matriz de permisos."""

from contratacion.dominio.roles import (
    PERMISOS_POR_ROL,
    Rol,
    es_administrativo,
    es_de_plataforma,
    normalizar_rol,
    puede_asignar,
    puede_exportar,
    tiene_permiso,
)


def test_el_catalogo_tiene_tres_roles() -> None:
    assert set(Rol) == {Rol.SUPER_ADMIN, Rol.DUENO_EMPRESA, Rol.USUARIO}


def test_un_token_viejo_se_lee_como_el_rol_nuevo() -> None:
    assert normalizar_rol("admin_negocio") is Rol.DUENO_EMPRESA
    assert normalizar_rol("consultor") is Rol.USUARIO
    assert normalizar_rol("lector") is Rol.USUARIO


def test_el_dueno_no_asigna_otro_dueno_ni_al_superadministrador() -> None:
    assert puede_asignar(Rol.USUARIO)
    assert not puede_asignar(Rol.DUENO_EMPRESA)
    assert not puede_asignar(Rol.SUPER_ADMIN)


def test_solo_el_superadministrador_concede_plazos_y_gestiona_empresas() -> None:
    assert tiene_permiso("super_admin", "plazos.conceder")
    assert tiene_permiso("super_admin", "empresas.gestionar")
    assert not tiene_permiso("dueno_empresa", "plazos.conceder")
    assert not tiene_permiso("usuario", "empresas.gestionar")
    assert not tiene_permiso("usuario", "tdr.rellenar")
    assert tiene_permiso("dueno_empresa", "tdr.rellenar")
    assert tiene_permiso("usuario", "tdr.ver")


def test_el_superadministrador_sigue_siendo_de_plataforma() -> None:
    assert es_de_plataforma("super_admin")
    assert not es_de_plataforma("dueno_empresa")
    assert not es_de_plataforma("admin_negocio")
    assert es_administrativo("admin_negocio")
    assert puede_exportar("usuario")
    assert puede_exportar("lector")


def test_la_matriz_cubre_los_tres_roles() -> None:
    assert set(PERMISOS_POR_ROL) == set(Rol)
