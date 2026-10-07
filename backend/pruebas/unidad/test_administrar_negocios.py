"""Pruebas del borrado de empresas y de cuentas desde la plataforma.

Son las dos únicas operaciones del sistema que **destruyen** algo sin camino de vuelta, así que la
mayor parte de estas pruebas no comprueban que borren: comprueban **cuándo se niegan**. Las guardas
son el producto; el `DELETE` es la parte fácil.

Se defienden tres cosas que un descuido rompería sin que se note hasta que es tarde:

1. **El orden de la auditoría.** Se escribe antes de borrar. Si se escribiera después, el fallo que
   más importa —el borrado que sí ocurrió y cuya anotación no— es exactamente el que se produce.
2. **Que no se pueda dejar el sistema sin puerta.** Ni borrando la empresa propia —quien lo pide se
   quedaría fuera sin forma de volver— ni borrando la última cuenta administrativa de una empresa,
   que la dejaría sin nadie que pueda gestionarla desde dentro.
3. **Que la confirmación sea del dato que se borra.** El nombre de la empresa y el correo de la
   cuenta, no un «sí» genérico: la operación destruye el registro de aceptación de los términos y
   un botón que se pulsa sin querer no puede tener esa consecuencia.

Todas las pruebas usan dobles que apuntan en una **lista compartida** lo que les van pidiendo. Es lo
que permite afirmar el orden de los pasos y no solo su presencia.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.casos_uso.administrar_negocios import (
    eliminar_cuenta_de_empresa,
    eliminar_empresa,
)
from contratacion.aplicacion.puertos.negocios import EmpresaDePlataforma, NegocioGuardado
from contratacion.aplicacion.puertos.usuarios import FichaUsuario
from contratacion.dominio.errores import DatoInvalido, NoEncontrado, SinPermiso
from contratacion.dominio.roles import Rol
from contratacion.dominio.sesiones import MotivoRevocacion

AHORA = datetime(2026, 10, 5, 15, 0, tzinfo=UTC)

PLATAFORMA_ID = UUID("00000000-0000-0000-0000-000000000001")
CLIENTE = UUID("22222222-2222-2222-2222-222222222222")
OTRO_CLIENTE = UUID("33333333-3333-3333-3333-333333333333")

ADMIN_CLIENTE = UUID("44444444-4444-4444-4444-444444444444")
CONSULTOR = UUID("55555555-5555-5555-5555-555555555555")

DE_PLATAFORMA = Actor(usuario_id=PLATAFORMA_ID, negocio_id=PLATAFORMA_ID, rol="super_admin")
ADMINISTRADOR = Actor(usuario_id=ADMIN_CLIENTE, negocio_id=CLIENTE, rol="admin_negocio")

NOMBRE = "Constructora Andina"


# --------------------------------------------------------------------------- #
# Dobles
# --------------------------------------------------------------------------- #


class NegociosFalsos:
    """Empresas en memoria. Apunta cada operación en la lista compartida."""

    def __init__(self, guardadas: dict[UUID, NegocioGuardado] | None = None) -> None:
        self.guardadas = guardadas or {}
        self.eliminados: list[UUID] = []

    async def listar(self) -> tuple[EmpresaDePlataforma, ...]:
        raise AssertionError("el borrado no debe listar empresas")

    async def cambiar_estado(self, *, negocio_id: UUID, estado: str, momento: datetime) -> None:
        raise AssertionError("el borrado no debe cambiar estados")

    async def eliminar(self, *, negocio_id: UUID) -> None:
        self.eliminados.append(negocio_id)
        self.guardadas.pop(negocio_id, None)

    async def crear(self, alta: Any) -> UUID:
        raise AssertionError("el borrado no debe crear empresas")

    async def obtener(self, *, negocio_id: UUID) -> NegocioGuardado | None:
        return self.guardadas.get(negocio_id)

    async def actualizar_datos(self, **_: Any) -> None:
        raise AssertionError("el borrado no debe actualizar datos")

    async def resumen_uso(self, *, negocio_id: UUID) -> dict[str, Any]:
        raise AssertionError("el borrado no debe pedir el resumen de uso")


class UsuariosFalsos:
    """Cuentas en memoria, indexadas por empresa.

    `listar` devuelve las de la empresa que se pide y no todas: es lo que permite comprobar que el
    borrado de una empresa no se lleva por delante las cuentas de otra.
    """

    def __init__(self, cuentas: list[FichaUsuario] | None = None) -> None:
        self.cuentas = {cuenta.usuario_id: cuenta for cuenta in (cuentas or [])}
        self.eliminadas: list[tuple[UUID, UUID]] = []

    def _de(self, negocio_id: UUID) -> list[FichaUsuario]:
        return [cuenta for cuenta in self.cuentas.values() if cuenta.negocio_id == negocio_id]

    async def crear(self, cuenta: Any) -> UUID:
        raise AssertionError("el borrado no debe crear cuentas")

    async def obtener(self, *, negocio_id: UUID, usuario_id: UUID) -> FichaUsuario | None:
        cuenta = self.cuentas.get(usuario_id)
        if cuenta is None or cuenta.negocio_id != negocio_id:
            # Una cuenta de otra empresa no existe «en esta empresa»: pedirla así no encuentra nada,
            # que es justo lo que evita un borrado sobre la empresa equivocada.
            return None
        return cuenta

    async def listar(
        self, *, negocio_id: UUID, incluir_inactivos: bool = False
    ) -> list[FichaUsuario]:
        cuentas = self._de(negocio_id)
        if not incluir_inactivos:
            cuentas = [cuenta for cuenta in cuentas if cuenta.activo]
        return cuentas

    async def contar_activos(self, *, negocio_id: UUID) -> int:
        return len([cuenta for cuenta in self._de(negocio_id) if cuenta.activo])

    async def contar_administradores(self, *, negocio_id: UUID) -> int:
        return len(
            [
                cuenta
                for cuenta in self._de(negocio_id)
                if cuenta.activo and cuenta.rol is Rol.ADMIN_NEGOCIO
            ]
        )

    async def actualizar_huella(self, **_: Any) -> None:
        raise AssertionError("el borrado no debe tocar huellas")

    async def actualizar_identidad(self, **_: Any) -> None:
        raise AssertionError("el borrado no debe tocar identidades")

    async def cambiar_estado(self, **_: Any) -> None:
        raise AssertionError("el borrado no debe cambiar estados de cuenta")

    async def eliminar(self, *, negocio_id: UUID, usuario_id: UUID) -> None:
        self.eliminadas.append((negocio_id, usuario_id))
        self.cuentas.pop(usuario_id, None)


class SesionesFalsas:
    """Cierre de sesiones. Devuelve un número distinto por cuenta para poder sumar."""

    def __init__(self, por_usuario: dict[UUID, int] | None = None) -> None:
        self.por_usuario = por_usuario or {}
        self.revocadas: list[tuple[UUID, UUID, MotivoRevocacion]] = []

    async def revocar_todas(
        self,
        *,
        negocio_id: UUID,
        usuario_id: UUID,
        motivo: MotivoRevocacion,
        momento: datetime,
    ) -> int:
        self.revocadas.append((negocio_id, usuario_id, motivo))
        return self.por_usuario.get(usuario_id, 1)

    async def revocar_todas_salvo(self, **_: Any) -> int:
        raise AssertionError("el borrado no cierra sesiones «salvo» ninguna")


class AuditoriaFalsa:
    """Anota la línea. `pasos` es la lista compartida donde se ve el orden real de lo ocurrido."""

    def __init__(self, pasos: list[str] | None = None) -> None:
        self.lineas: list[dict[str, Any]] = []
        self.pasos = pasos if pasos is not None else []

    async def auditar(
        self,
        *,
        accion: str,
        negocio_id: UUID,
        usuario_id: UUID | None = None,
        entidad: str | None = None,
        entidad_id: str | None = None,
        resultado: str | None = None,
        detalle: dict[str, Any] | None = None,
    ) -> None:
        self.pasos.append("auditar")
        self.lineas.append(
            {
                "accion": accion,
                "negocio_id": negocio_id,
                "usuario_id": usuario_id,
                "entidad": entidad,
                "entidad_id": entidad_id,
                "resultado": resultado,
                "detalle": detalle,
            }
        )


class NegociosQueApuntanPasos(NegociosFalsos):
    """Igual que el anterior, pero deja constancia del borrado en la lista compartida."""

    def __init__(
        self, pasos: list[str], guardadas: dict[UUID, NegocioGuardado] | None = None
    ) -> None:
        super().__init__(guardadas)
        self.pasos = pasos

    async def eliminar(self, *, negocio_id: UUID) -> None:
        self.pasos.append("eliminar")
        await super().eliminar(negocio_id=negocio_id)


def _empresa(
    negocio_id: UUID = CLIENTE, nombre: str = NOMBRE, estado: str = "activo"
) -> NegocioGuardado:
    return NegocioGuardado(
        negocio_id=negocio_id,
        nombre=nombre,
        ruc="1790012345001",
        estado=estado,
        plan="estandar",
        limite_usuarios=10,
        email_contacto=None,
        telefono=None,
        direccion=None,
        ciudad=None,
        creado_en=AHORA,
    )


def _cuenta(
    usuario_id: UUID,
    *,
    negocio_id: UUID = CLIENTE,
    email: str,
    rol: Rol = Rol.CONSULTOR,
    nombre: str = "Ana Pérez",
    estado: str = "activo",
) -> FichaUsuario:
    return FichaUsuario(
        usuario_id=usuario_id,
        negocio_id=negocio_id,
        email=email,
        nombre=nombre,
        rol=rol,
        estado=estado,
        ultimo_acceso=None,
        creado_en=AHORA,
    )


# --------------------------------------------------------------------------- #
# Borrado de una empresa
# --------------------------------------------------------------------------- #


async def test_eliminar_empresa_la_borra_y_cierra_las_sesiones_de_su_gente() -> None:
    pasos: list[str] = []
    negocios = NegociosQueApuntanPasos(pasos, guardadas={CLIENTE: _empresa()})
    usuarios = UsuariosFalsos(
        [
            _cuenta(ADMIN_CLIENTE, email="jefa@andina.ec", rol=Rol.ADMIN_NEGOCIO),
            _cuenta(CONSULTOR, email="ana@andina.ec"),
        ]
    )
    sesiones = SesionesFalsas({ADMIN_CLIENTE: 2, CONSULTOR: 1})
    auditoria = AuditoriaFalsa(pasos)

    resultado = await eliminar_empresa(
        DE_PLATAFORMA,
        negocio_id=CLIENTE,
        repositorio=negocios,
        usuarios=usuarios,
        sesiones=sesiones,
        auditoria=auditoria,
        confirmacion=NOMBRE,
        momento=AHORA,
    )

    assert negocios.eliminados == [CLIENTE]
    assert resultado.cuentas_borradas == 2
    assert resultado.sesiones_cerradas == 3
    assert resultado.nombre == NOMBRE
    assert sesiones.revocadas[0][2] is MotivoRevocacion.ADMIN
    assert usuarios.eliminadas == [], "las cuentas se van con la empresa, no una a una"


async def test_las_cuentas_se_van_con_la_empresa_en_una_sola_operacion() -> None:
    """No se borra cuenta a cuenta, y es a propósito.

    Borrarlas una a una dejaría la empresa medio vacía si algo fallara a mitad, y la operación más
    destructiva del sistema no puede quedar a medias. Las claves ajenas se llevan cuentas, sesiones,
    accesos y consentimientos dentro de la misma transacción que borra la empresa; lo que el caso de
    uso hace antes es **leerlas**: para poder decir cuántas eran y para cerrarles la marca del
    almacén, que no se va con la fila.

    Lo que esta prueba impide es que alguien «arregle» el borrado añadiendo un bucle de borrados
    por cuenta, que es más lento, no es atómico y no hace falta.
    """
    sesiones = SesionesFalsas()

    await eliminar_empresa(
        DE_PLATAFORMA,
        negocio_id=CLIENTE,
        repositorio=NegociosFalsos({CLIENTE: _empresa()}),
        usuarios=UsuariosFalsos([_cuenta(CONSULTOR, email="ana@andina.ec")]),
        sesiones=sesiones,
        auditoria=AuditoriaFalsa(),
        confirmacion=NOMBRE,
        momento=AHORA,
    )

    assert [usuario for _, usuario, _ in sesiones.revocadas] == [CONSULTOR]


async def test_la_auditoria_se_escribe_antes_de_borrar() -> None:
    """El orden es la prueba, no la presencia.

    La línea se escribe antes porque el fallo que importa es el borrado que sí ocurrió y cuya
    anotación no. Al revés —anotar después— ese fallo es justo el que se produce.
    """
    pasos: list[str] = []
    negocios = NegociosQueApuntanPasos(pasos, guardadas={CLIENTE: _empresa()})
    auditoria = AuditoriaFalsa(pasos)

    await eliminar_empresa(
        DE_PLATAFORMA,
        negocio_id=CLIENTE,
        repositorio=negocios,
        usuarios=UsuariosFalsos([]),
        sesiones=SesionesFalsas(),
        auditoria=auditoria,
        confirmacion=NOMBRE,
        momento=AHORA,
    )

    assert pasos == ["auditar", "eliminar"]


async def test_una_empresa_ya_borrada_se_llama_no_encontrada() -> None:
    """Se comprueba la existencia antes de tocar nada, para no anotar un borrado que no ocurre."""
    negocios = NegociosFalsos()
    auditoria = AuditoriaFalsa()

    with pytest.raises(NoEncontrado):
        await eliminar_empresa(
            DE_PLATAFORMA,
            negocio_id=CLIENTE,
            repositorio=negocios,
            usuarios=UsuariosFalsos([]),
            sesiones=SesionesFalsas(),
            auditoria=auditoria,
            confirmacion=NOMBRE,
            momento=AHORA,
        )

    assert negocios.eliminados == []
    assert auditoria.lineas == []


async def test_un_administrador_de_empresa_no_puede_eliminar_ninguna() -> None:
    """La regla no la decide el objeto sobre el que se actúa, sino quién lo pide.

    Se pide **sobre su propia empresa** y aun así se niega por rol: si solo se comprobara que nadie
    borra la suya, un administrador de empresa podría borrar las demás.
    """
    negocios = NegociosFalsos({CLIENTE: _empresa(), OTRO_CLIENTE: _empresa(OTRO_CLIENTE)})
    auditoria = AuditoriaFalsa()

    with pytest.raises(SinPermiso):
        await eliminar_empresa(
            ADMINISTRADOR,
            negocio_id=OTRO_CLIENTE,
            repositorio=negocios,
            usuarios=UsuariosFalsos([]),
            sesiones=SesionesFalsas(),
            auditoria=auditoria,
            confirmacion=NOMBRE,
            momento=AHORA,
        )

    assert negocios.eliminados == []


async def test_no_se_puede_eliminar_la_empresa_propia() -> None:
    """Quien lo pide se quedaría fuera del sistema sin ninguna forma de volver a entrar."""
    negocios = NegociosFalsos({PLATAFORMA_ID: _empresa(PLATAFORMA_ID, "La plataforma")})

    with pytest.raises(DatoInvalido) as fallo:
        await eliminar_empresa(
            DE_PLATAFORMA,
            negocio_id=PLATAFORMA_ID,
            repositorio=negocios,
            usuarios=UsuariosFalsos([]),
            sesiones=SesionesFalsas(),
            auditoria=AuditoriaFalsa(),
            confirmacion="La plataforma",
            momento=AHORA,
        )

    assert "suspenderla" in str(fallo.value)
    assert negocios.eliminados == []


@pytest.mark.parametrize("confirmacion", [None, "", "   ", "Constructora del Sur", "andina"])
async def test_la_confirmacion_tiene_que_ser_el_nombre_de_la_empresa(
    confirmacion: str | None,
) -> None:
    """Un nombre a medias no basta: la operación no se deshace y no hay nada que la revierta."""
    negocios = NegociosFalsos({CLIENTE: _empresa()})

    with pytest.raises(DatoInvalido):
        await eliminar_empresa(
            DE_PLATAFORMA,
            negocio_id=CLIENTE,
            repositorio=negocios,
            usuarios=UsuariosFalsos([]),
            sesiones=SesionesFalsas(),
            auditoria=AuditoriaFalsa(),
            confirmacion=confirmacion,
            momento=AHORA,
        )

    assert negocios.eliminados == []


@pytest.mark.parametrize(
    "confirmacion", ["Constructora Andina", "constructora andina", " Constructora Andina "]
)
async def test_el_nombre_se_compara_sin_mayusculas_ni_espacios_de_sobra(confirmacion: str) -> None:
    """Es una traba contra el descuido, no un examen de mecanografía."""
    negocios = NegociosFalsos({CLIENTE: _empresa()})

    await eliminar_empresa(
        DE_PLATAFORMA,
        negocio_id=CLIENTE,
        repositorio=negocios,
        usuarios=UsuariosFalsos([]),
        sesiones=SesionesFalsas(),
        auditoria=AuditoriaFalsa(),
        confirmacion=confirmacion,
        momento=AHORA,
    )

    assert negocios.eliminados == [CLIENTE]


async def test_la_linea_de_auditoria_guarda_lo_que_ya_no_existira() -> None:
    """Después del borrado no hay a quién preguntar cuántas cuentas tenía ni cómo se llamaba.

    La línea se lleva el nombre, el RUC, el estado y el número de cuentas porque es lo último que
    queda de esa empresa: sin ellos, el registro diría que algo se borró y nada más.
    """
    auditoria = AuditoriaFalsa()

    await eliminar_empresa(
        DE_PLATAFORMA,
        negocio_id=CLIENTE,
        repositorio=NegociosFalsos({CLIENTE: _empresa(estado="suspendido")}),
        usuarios=UsuariosFalsos(
            [_cuenta(ADMIN_CLIENTE, email="jefa@andina.ec", rol=Rol.ADMIN_NEGOCIO)]
        ),
        sesiones=SesionesFalsas(),
        auditoria=auditoria,
        confirmacion=NOMBRE,
        momento=AHORA,
    )

    linea = auditoria.lineas[0]
    assert linea["accion"] == "borrado_negocio"
    assert linea["entidad_id"] == str(CLIENTE)
    assert linea["resultado"] == "borrado"
    assert linea["detalle"] == {
        "nombre": NOMBRE,
        "ruc": "1790012345001",
        "estado": "suspendido",
        "cuentas": 1,
    }
    # La línea se escribe en el negocio de quien la provoca, no en el que desaparece: la auditoría
    # del cliente borrado se iría con él y quedaría un borrado sin autor.
    assert linea["negocio_id"] == PLATAFORMA_ID
    assert linea["usuario_id"] == PLATAFORMA_ID


async def test_solo_se_cierran_las_sesiones_de_la_empresa_borrada() -> None:
    """La lista de cuentas es la de la empresa que se borra: las de otra no se tocan."""
    ajena = uuid4()
    usuarios = UsuariosFalsos(
        [
            _cuenta(ADMIN_CLIENTE, email="jefa@andina.ec", rol=Rol.ADMIN_NEGOCIO),
            _cuenta(ajena, negocio_id=OTRO_CLIENTE, email="otro@sur.ec", rol=Rol.ADMIN_NEGOCIO),
        ]
    )
    sesiones = SesionesFalsas()

    await eliminar_empresa(
        DE_PLATAFORMA,
        negocio_id=CLIENTE,
        repositorio=NegociosFalsos({CLIENTE: _empresa()}),
        usuarios=usuarios,
        sesiones=sesiones,
        auditoria=AuditoriaFalsa(),
        confirmacion=NOMBRE,
        momento=AHORA,
    )

    assert [negocio for negocio, _, _ in sesiones.revocadas] == [CLIENTE]
    assert len(usuarios.cuentas) == 2, "el doble no borra: la empresa es la que se lleva las filas"


# --------------------------------------------------------------------------- #
# Borrado de una cuenta concreta
# --------------------------------------------------------------------------- #


async def test_eliminar_cuenta_borra_y_cierra_sus_sesiones() -> None:
    usuarios = UsuariosFalsos([_cuenta(CONSULTOR, email="ana@andina.ec")])
    sesiones = SesionesFalsas({CONSULTOR: 3})
    auditoria = AuditoriaFalsa()

    resultado = await eliminar_cuenta_de_empresa(
        DE_PLATAFORMA,
        negocio_id=CLIENTE,
        usuario_id=CONSULTOR,
        usuarios=usuarios,
        sesiones=sesiones,
        auditoria=auditoria,
        confirmacion="ana@andina.ec",
        momento=AHORA,
    )

    assert usuarios.eliminadas == [(CLIENTE, CONSULTOR)]
    assert sesiones.revocadas == [(CLIENTE, CONSULTOR, MotivoRevocacion.ADMIN)]
    assert resultado.cuentas_borradas == 1
    assert resultado.sesiones_cerradas == 3
    assert auditoria.lineas[0]["accion"] == "borrado_usuario"
    assert auditoria.lineas[0]["detalle"] is not None
    assert auditoria.lineas[0]["detalle"]["desde_plataforma"] is True


async def test_eliminar_cuenta_exige_ser_de_la_plataforma() -> None:
    usuarios = UsuariosFalsos([_cuenta(CONSULTOR, email="ana@andina.ec")])

    with pytest.raises(SinPermiso):
        await eliminar_cuenta_de_empresa(
            ADMINISTRADOR,
            negocio_id=CLIENTE,
            usuario_id=CONSULTOR,
            usuarios=usuarios,
            sesiones=SesionesFalsas(),
            auditoria=AuditoriaFalsa(),
            confirmacion="ana@andina.ec",
            momento=AHORA,
        )

    assert usuarios.eliminadas == []


async def test_no_se_puede_eliminar_la_cuenta_con_la_que_se_actua() -> None:
    """Es la única puerta que tiene el panel de plataforma: borrarla es cerrarlo desde dentro."""
    usuarios = UsuariosFalsos(
        [
            _cuenta(
                PLATAFORMA_ID,
                negocio_id=PLATAFORMA_ID,
                email="isaac@plataforma.ec",
                rol=Rol.SUPER_ADMIN,
            )
        ]
    )

    with pytest.raises(DatoInvalido):
        await eliminar_cuenta_de_empresa(
            DE_PLATAFORMA,
            negocio_id=PLATAFORMA_ID,
            usuario_id=PLATAFORMA_ID,
            usuarios=usuarios,
            sesiones=SesionesFalsas(),
            auditoria=AuditoriaFalsa(),
            confirmacion="isaac@plataforma.ec",
            momento=AHORA,
        )

    assert usuarios.eliminadas == []


async def test_una_cuenta_de_otra_empresa_se_llama_no_encontrada() -> None:
    """La búsqueda es dentro de la empresa indicada: pedirla por otro negocio no la alcanza."""
    usuarios = UsuariosFalsos([_cuenta(CONSULTOR, email="ana@andina.ec")])

    with pytest.raises(NoEncontrado):
        await eliminar_cuenta_de_empresa(
            DE_PLATAFORMA,
            negocio_id=OTRO_CLIENTE,
            usuario_id=CONSULTOR,
            usuarios=usuarios,
            sesiones=SesionesFalsas(),
            auditoria=AuditoriaFalsa(),
            confirmacion="ana@andina.ec",
            momento=AHORA,
        )

    assert usuarios.eliminadas == []


async def test_la_confirmacion_tiene_que_ser_el_correo_de_la_cuenta() -> None:
    usuarios = UsuariosFalsos([_cuenta(CONSULTOR, email="ana@andina.ec")])

    with pytest.raises(DatoInvalido):
        await eliminar_cuenta_de_empresa(
            DE_PLATAFORMA,
            negocio_id=CLIENTE,
            usuario_id=CONSULTOR,
            usuarios=usuarios,
            sesiones=SesionesFalsas(),
            auditoria=AuditoriaFalsa(),
            confirmacion="jefa@andina.ec",
            momento=AHORA,
        )

    assert usuarios.eliminadas == []


async def test_no_se_puede_dejar_una_empresa_sin_administradores() -> None:
    """Sin ninguna cuenta administrativa, esa empresa solo se arregla entrando a mano en la base."""
    usuarios = UsuariosFalsos(
        [_cuenta(ADMIN_CLIENTE, email="jefa@andina.ec", rol=Rol.ADMIN_NEGOCIO)]
    )
    auditoria = AuditoriaFalsa()

    with pytest.raises(DatoInvalido) as fallo:
        await eliminar_cuenta_de_empresa(
            DE_PLATAFORMA,
            negocio_id=CLIENTE,
            usuario_id=ADMIN_CLIENTE,
            usuarios=usuarios,
            sesiones=SesionesFalsas(),
            auditoria=auditoria,
            confirmacion="jefa@andina.ec",
            momento=AHORA,
        )

    assert "Eliminar empresa" in str(fallo.value)
    assert usuarios.eliminadas == []
    assert auditoria.lineas == []


async def test_con_dos_administradores_el_borrado_pasa() -> None:
    """La regla es «no quedarse sin ninguno», no «no borrar administradores»."""
    segunda = uuid4()
    usuarios = UsuariosFalsos(
        [
            _cuenta(ADMIN_CLIENTE, email="jefa@andina.ec", rol=Rol.ADMIN_NEGOCIO),
            _cuenta(segunda, email="jefe2@andina.ec", rol=Rol.ADMIN_NEGOCIO),
        ]
    )

    await eliminar_cuenta_de_empresa(
        DE_PLATAFORMA,
        negocio_id=CLIENTE,
        usuario_id=ADMIN_CLIENTE,
        usuarios=usuarios,
        sesiones=SesionesFalsas(),
        auditoria=AuditoriaFalsa(),
        confirmacion="jefa@andina.ec",
        momento=AHORA,
    )

    assert usuarios.eliminadas == [(CLIENTE, ADMIN_CLIENTE)]


async def test_borrar_una_cuenta_no_administrativa_no_consulta_a_los_administradores() -> None:
    """Un consultor no puede ser el último administrador, así que no hay nada que contar."""

    class UsuariosQueNoCuentan(UsuariosFalsos):
        async def contar_administradores(self, *, negocio_id: UUID) -> int:
            raise AssertionError("borrar a un consultor no exige contar administradores")

    usuarios = UsuariosQueNoCuentan([_cuenta(CONSULTOR, email="ana@andina.ec")])

    await eliminar_cuenta_de_empresa(
        DE_PLATAFORMA,
        negocio_id=CLIENTE,
        usuario_id=CONSULTOR,
        usuarios=usuarios,
        sesiones=SesionesFalsas(),
        auditoria=AuditoriaFalsa(),
        confirmacion="ana@andina.ec",
        momento=AHORA,
    )

    assert usuarios.eliminadas == [(CLIENTE, CONSULTOR)]


async def test_el_borrado_de_una_cuenta_tambien_anota_antes() -> None:
    """Misma razón que en el de la empresa: la anotación no puede depender del borrado."""
    pasos: list[str] = []

    class UsuariosQueApuntan(UsuariosFalsos):
        async def eliminar(self, *, negocio_id: UUID, usuario_id: UUID) -> None:
            pasos.append("eliminar")
            await super().eliminar(negocio_id=negocio_id, usuario_id=usuario_id)

    await eliminar_cuenta_de_empresa(
        DE_PLATAFORMA,
        negocio_id=CLIENTE,
        usuario_id=CONSULTOR,
        usuarios=UsuariosQueApuntan([_cuenta(CONSULTOR, email="ana@andina.ec")]),
        sesiones=SesionesFalsas(),
        auditoria=AuditoriaFalsa(pasos),
        confirmacion="ana@andina.ec",
        momento=AHORA,
    )

    assert pasos == ["auditar", "eliminar"]
