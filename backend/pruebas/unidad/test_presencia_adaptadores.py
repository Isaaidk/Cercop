"""Pruebas del almacén de señales en memoria y del formato de los avisos.

El almacén en memoria es la única implementación que funciona sin Redis, así que un fallo suyo se
nota en desarrollo y en los despliegues pequeños. Lo que más importa comprobar aquí es el
**aislamiento entre negocios**: las señales se listan recorriendo claves por prefijo, y si esa
separación se rompiera, un negocio vería a los conectados de otro sin ningún error de por medio.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from contratacion.dominio.presencia import (
    EstadoPresencia,
    EventoPresencia,
    Latido,
    Motivo,
    Presencia,
    TipoEvento,
    evento_conectado,
)
from contratacion.infraestructura.adaptadores.entrada.http.routers.presencia import (
    _evento_servidor,
)
from contratacion.infraestructura.adaptadores.salida.presencia.memoria import (
    MAXIMO_AVISOS_EN_COLA,
    PresenciaMemoria,
    deserializar_evento,
    serializar_evento,
)
from contratacion.infraestructura.adaptadores.salida.presencia.redis import deserializar_latido

AHORA = datetime(2026, 10, 5, 15, 0, tzinfo=UTC)
TTL = 60

NEGOCIO = UUID("22222222-2222-2222-2222-222222222222")
OTRO_NEGOCIO = UUID("33333333-3333-3333-3333-333333333333")
USUARIO = UUID("11111111-1111-1111-1111-111111111111")


def _presencia(
    usuario_id: UUID = USUARIO, estado: EstadoPresencia = EstadoPresencia.VERDE
) -> Presencia:
    return Presencia(
        usuario_id=usuario_id,
        estado=estado,
        motivo=Motivo.CONECTADO if estado is EstadoPresencia.VERDE else Motivo.SIN_SENAL,
        ultimo_latido_en=AHORA,
        dispositivos=1,
    )


# --------------------------------------------------------------------------- #
# Señales
# --------------------------------------------------------------------------- #


async def test_una_senal_marcada_se_recupera() -> None:
    registro = PresenciaMemoria()
    sesion_id = uuid4()
    await registro.marcar(
        usuario_id=USUARIO,
        sesion_id=sesion_id,
        negocio_id=NEGOCIO,
        momento=AHORA,
        ttl_seg=TTL,
    )

    vivas = await registro.vivas(negocio_id=NEGOCIO)
    assert len(vivas) == 1
    assert vivas[0] == Latido(usuario_id=USUARIO, sesion_id=sesion_id, momento=AHORA)


async def test_las_senales_de_un_negocio_no_se_ven_desde_otro() -> None:
    """El aislamiento, que aquí es una comprobación de prefijo de clave."""
    registro = PresenciaMemoria()
    await registro.marcar(
        usuario_id=USUARIO, sesion_id=uuid4(), negocio_id=NEGOCIO, momento=AHORA, ttl_seg=TTL
    )
    await registro.marcar(
        usuario_id=USUARIO, sesion_id=uuid4(), negocio_id=OTRO_NEGOCIO, momento=AHORA, ttl_seg=TTL
    )

    assert len(await registro.vivas(negocio_id=NEGOCIO)) == 1
    assert len(await registro.vivas(negocio_id=OTRO_NEGOCIO)) == 1
    assert len(await registro.vivas(negocio_id=uuid4())) == 0


async def test_la_senal_vencida_no_se_devuelve() -> None:
    """El almacén limpia lo vencido con su reloj; el dominio vuelve a comprobarlo con el suyo."""
    registro = PresenciaMemoria()
    muy_antiguo = datetime.now(UTC) - timedelta(seconds=TTL * 10)
    await registro.marcar(
        usuario_id=USUARIO,
        sesion_id=uuid4(),
        negocio_id=NEGOCIO,
        momento=muy_antiguo,
        ttl_seg=TTL,
    )

    assert await registro.vivas(negocio_id=NEGOCIO) == ()


async def test_marcar_de_nuevo_alarga_la_vigencia() -> None:
    registro = PresenciaMemoria()
    sesion_id = uuid4()
    viejo = datetime.now(UTC) - timedelta(seconds=TTL - 5)

    await registro.marcar(
        usuario_id=USUARIO, sesion_id=sesion_id, negocio_id=NEGOCIO, momento=viejo, ttl_seg=TTL
    )
    await registro.marcar(
        usuario_id=USUARIO, sesion_id=sesion_id, negocio_id=NEGOCIO, momento=AHORA, ttl_seg=TTL
    )

    vivas = await registro.vivas(negocio_id=NEGOCIO)
    assert len(vivas) == 1, "no se duplica: la clave es la sesión"
    assert vivas[0].momento == AHORA


async def test_olvidar_una_sesion_no_apaga_las_demas() -> None:
    """Dos dispositivos, y cerrar uno no desconecta al otro."""
    registro = PresenciaMemoria()
    portatil, movil = uuid4(), uuid4()
    for sesion_id in (portatil, movil):
        await registro.marcar(
            usuario_id=USUARIO,
            sesion_id=sesion_id,
            negocio_id=NEGOCIO,
            momento=AHORA,
            ttl_seg=TTL,
        )

    await registro.olvidar(negocio_id=NEGOCIO, sesion_id=portatil)

    restantes = await registro.vivas(negocio_id=NEGOCIO)
    assert [senal.sesion_id for senal in restantes] == [movil]


async def test_el_almacen_en_memoria_declara_que_no_es_compartido() -> None:
    """Para que la interfaz pueda advertirlo en lugar de mostrar un dato incompleto sin avisar."""
    assert PresenciaMemoria().compartida is False


# --------------------------------------------------------------------------- #
# El bus
# --------------------------------------------------------------------------- #


async def test_un_aviso_publicado_llega_a_quien_escucha() -> None:
    registro = PresenciaMemoria()
    evento = evento_conectado(NEGOCIO, _presencia(), AHORA)

    async with registro.suscribir(negocio_id=NEGOCIO) as canal:
        await registro.publicar(negocio_id=NEGOCIO, evento=evento)
        recibido = await canal.siguiente(1.0)

    assert recibido is not None
    assert recibido.tipo is TipoEvento.CONECTADO
    assert recibido.presencia is not None
    assert recibido.presencia.usuario_id == USUARIO


async def test_sin_avisos_la_espera_devuelve_nada() -> None:
    """Y eso es lo que permite al enrutador reenviar la instantánea en vez de quedarse bloqueado."""
    registro = PresenciaMemoria()
    async with registro.suscribir(negocio_id=NEGOCIO) as canal:
        assert await canal.siguiente(0.01) is None


async def test_un_aviso_no_llega_al_canal_de_otro_negocio() -> None:
    """Cada negocio tiene su canal, así que el aislamiento se resuelve en el transporte."""
    registro = PresenciaMemoria()
    evento = evento_conectado(OTRO_NEGOCIO, _presencia(), AHORA)

    async with registro.suscribir(negocio_id=NEGOCIO) as canal:
        await registro.publicar(negocio_id=OTRO_NEGOCIO, evento=evento)
        assert await canal.siguiente(0.01) is None


async def test_publicar_sin_nadie_escuchando_no_falla() -> None:
    """Pub/Sub no guarda historia: el aviso se pierde y nadie tiene que enterarse."""
    registro = PresenciaMemoria()
    await registro.publicar(
        negocio_id=NEGOCIO, evento=evento_conectado(NEGOCIO, _presencia(), AHORA)
    )


async def test_el_canal_se_cierra_al_salir_del_bloque() -> None:
    """Sin esto, cada pestaña cerrada dejaría una cola colgada en el servidor."""
    registro = PresenciaMemoria()
    async with registro.suscribir(negocio_id=NEGOCIO):
        pass

    # Publicar después no debe encontrar nada, y sobre todo no debe fallar.
    await registro.publicar(
        negocio_id=NEGOCIO, evento=evento_conectado(NEGOCIO, _presencia(), AHORA)
    )


async def test_un_panel_lento_no_frena_a_quien_publica() -> None:
    """Un consumidor que no lee no puede bloquear el cierre de sesión de otra persona.

    Se llena la cola y se comprueba que el aviso se descarta en lugar de esperar. La instantánea
    periódica pondrá el panel en su sitio; lo que no se puede es trasladar el problema de uno a
    todos los demás.
    """
    registro = PresenciaMemoria()
    evento = evento_conectado(NEGOCIO, _presencia(), AHORA)

    async with registro.suscribir(negocio_id=NEGOCIO) as canal:
        for _ in range(MAXIMO_AVISOS_EN_COLA + 10):
            await registro.publicar(negocio_id=NEGOCIO, evento=evento)

        # La cola conserva exactamente su capacidad y nada más.
        recibidos = 0
        while await canal.siguiente(0.01) is not None:
            recibidos += 1

    assert recibidos == MAXIMO_AVISOS_EN_COLA


async def test_dos_paneles_reciben_el_mismo_aviso() -> None:
    registro = PresenciaMemoria()
    evento = evento_conectado(NEGOCIO, _presencia(), AHORA)

    async with (
        registro.suscribir(negocio_id=NEGOCIO) as uno,
        registro.suscribir(negocio_id=NEGOCIO) as otro,
    ):
        await registro.publicar(negocio_id=NEGOCIO, evento=evento)
        assert await uno.siguiente(1.0) is not None
        assert await otro.siguiente(1.0) is not None


# --------------------------------------------------------------------------- #
# El formato de los avisos
# --------------------------------------------------------------------------- #


def test_un_aviso_sobrevive_a_la_ida_y_vuelta_por_el_canal() -> None:
    """Los avisos cruzan entre procesos como texto, así que la conversión tiene que ser exacta.

    Se compara la representación y no el objeto porque es lo que viaja: si el identificador de
    sesión perdiera su forma de UUID al reconstruirse, el panel dejaría de poder casar el aviso con
    la fila que ya tiene.
    """
    original = evento_conectado(NEGOCIO, _presencia(), AHORA)
    reconstruido = deserializar_evento(serializar_evento(original), NEGOCIO)

    assert reconstruido is not None
    assert reconstruido.tipo is original.tipo
    assert reconstruido.momento == original.momento
    assert reconstruido.presencia is not None
    assert original.presencia is not None
    assert reconstruido.presencia.como_diccionario() == original.presencia.como_diccionario()


def test_un_aviso_ilegible_se_descarta_en_vez_de_romper_la_transmision() -> None:
    """Un dato corrupto en el bus no puede tumbar la pantalla de quien solo estaba mirando."""
    assert deserializar_evento("no es json", NEGOCIO) is None
    assert deserializar_evento('{"tipo": "conectado"}', NEGOCIO) is None


def test_un_aviso_sin_persona_se_reconstruye_igual() -> None:
    """La instantánea viaja sin una persona concreta: lleva la lista del negocio y nada más."""
    evento = EventoPresencia(
        tipo=TipoEvento.INSTANTANEA,
        negocio_id=NEGOCIO,
        momento=AHORA,
        presencias=(_presencia(),),
    )
    reconstruido = deserializar_evento(serializar_evento(evento), NEGOCIO)

    assert reconstruido is not None
    assert reconstruido.tipo is TipoEvento.INSTANTANEA
    assert reconstruido.presencia is None


def test_una_senal_guardada_ilegible_se_descarta() -> None:
    """Se registra la clave y se sigue: una fila mala no puede romper el listado entero."""
    assert deserializar_latido(None, "presencia:x:y") is None
    assert deserializar_latido("{}", "presencia:x:y") is None
    assert deserializar_latido(b"texto suelto", "presencia:x:y") is None


def test_una_senal_guardada_valida_se_reconstruye() -> None:
    crudo = (
        '{"u":"11111111-1111-1111-1111-111111111111",'
        '"s":"44444444-4444-4444-4444-444444444444",'
        f'"m":"{AHORA.isoformat()}"}}'
    )
    senal = deserializar_latido(crudo, "presencia:x:y")

    assert senal is not None
    assert senal.usuario_id == USUARIO
    assert senal.momento == AHORA


# --------------------------------------------------------------------------- #
# El formato del protocolo de eventos
# --------------------------------------------------------------------------- #


def test_el_evento_sigue_el_formato_del_protocolo() -> None:
    texto = _evento_servidor("instantanea", {"momento": AHORA.isoformat(), "conectados": 3})

    assert texto.startswith("event: instantanea\n")
    assert texto.endswith("\n\n")
    assert '"conectados":3' in texto, "sin espacios: es lo que pide el formato compacto"


def test_el_nombre_del_evento_no_puede_inyectar_cabeceras() -> None:
    """Un salto de línea en el nombre lo convertiría en dos eventos distintos.

    La comprobación es sobre el número de **líneas que empiezan** por `event:`, no sobre cuántas
    veces aparece el texto: el nombre del evento lleva `event:` dentro, y lo que importa es que ese
    texto se quede en la misma línea y no llegue a declarar un evento de verdad.
    """
    texto = _evento_servidor("conectado\r\nevent: falso", {"a": 1})

    declaraciones = [linea for linea in texto.split("\n") if linea.startswith("event:")]
    assert len(declaraciones) == 1
    assert "falso" in declaraciones[0]


def test_el_contenido_no_puede_inyectar_cabeceras() -> None:
    """Los saltos dentro de las cadenas viajan escapados por el serializador, no como saltos."""
    texto = _evento_servidor("instantanea", {"nota": "linea1\nlinea2"})

    assert texto.count("\n\n") == 1, "un solo separador de evento"
    assert r"linea1\nlinea2" in texto


def test_la_espera_concurrente_no_bloquea_el_bucle() -> None:
    """La suscripción se usa desde el bucle de eventos: esperar no puede consumir el proceso."""

    async def principal() -> None:
        registro = PresenciaMemoria()
        async with registro.suscribir(negocio_id=NEGOCIO) as canal:
            await asyncio.gather(canal.siguiente(0.01), canal.siguiente(0.01))

    asyncio.run(principal())
