"""El freno por IP corta al pasar el tope y deja pasar a otra IP."""

from contratacion.infraestructura.adaptadores.entrada.http.proteccion import FrenoPorIp


def test_freno_corta_al_pasar_el_tope() -> None:
    freno = FrenoPorIp()
    clave = ("POST", "/v1/auth/sesion", "10.0.0.1")
    assert all(freno.permite(clave, 3, 60) == 0 for _ in range(3))
    assert freno.permite(clave, 3, 60) > 0


def test_freno_separa_las_ips() -> None:
    freno = FrenoPorIp()
    for _ in range(3):
        freno.permite(("POST", "/v1/auth/sesion", "10.0.0.1"), 3, 60)
    assert freno.permite(("POST", "/v1/auth/sesion", "10.0.0.2"), 3, 60) == 0
