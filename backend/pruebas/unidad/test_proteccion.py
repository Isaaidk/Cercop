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


def test_railway_entrega_cliente_y_proxy_interno_y_hacen_falta_dos_saltos() -> None:
    """Cabecera real de Railway (medida con /v1/plataforma/eco-ip): cliente y proxy interno.

    Con un salto el freno contaba la IP del proxy de Railway, compartida por todos los usuarios.
    """
    from types import SimpleNamespace

    from starlette.datastructures import Headers

    from contratacion.infraestructura.adaptadores.entrada.http.proteccion import ip_cliente

    peticion = SimpleNamespace(
        client=SimpleNamespace(host="45.188.56.43"),
        headers=Headers({"x-forwarded-for": "45.188.56.43, 152.233.23.193"}),
    )
    assert ip_cliente(peticion, 2) == "45.188.56.43"  # type: ignore[arg-type]
    assert ip_cliente(peticion, 1) == "152.233.23.193"  # type: ignore[arg-type]
    # Un cliente que inventa la cabecera no elige su IP: Railway añade las dos de verdad detrás.
    falsa = SimpleNamespace(
        client=SimpleNamespace(host="1.2.3.4"),
        headers=Headers({"x-forwarded-for": "9.9.9.9, 45.188.56.43, 152.233.23.193"}),
    )
    assert ip_cliente(falsa, 2) == "45.188.56.43"  # type: ignore[arg-type]
