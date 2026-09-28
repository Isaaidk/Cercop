"""Comprobación del alta de palabras clave en bloque, contra la base real.

Lo que defiende, en una frase: **una lista de treinta y cinco palabras se guarda en una sola
transacción y sin duplicar nada**. Es la operación que hace el recuadro de texto separado por
comas, y la que más fácil sería de equivocar: un `ON CONFLICT` mal puesto, una lista con repetidos
o un tope comprobado palabra a palabra dejarían la mitad aplicada y nadie lo notaría hasta el día
siguiente.

Se ejecuta a mano:

    .\\.venv\\Scripts\\python.exe scripts\\verificar_terminos_lote.py

Crea una empresa temporal con credenciales generadas en memoria y la borra al terminar. Los términos
son globales, así que además se borran los que este guion haya creado: los que ya existían se dejan
como estaban, porque pueden ser de otro negocio.
"""

from __future__ import annotations

import asyncio
import secrets
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

sys.path.insert(0, "src")

from sqlalchemy import text

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.casos_uso.encolar_termino import agregar_terminos
from contratacion.aplicacion.puertos.negocios import AltaEmpresa
from contratacion.dominio.acceso import Plazo, Vista
from contratacion.dominio.errores import DatoInvalido
from contratacion.dominio.negocios import construir_datos_empresa
from contratacion.dominio.palabras import normalizar_termino
from contratacion.dominio.roles import Rol
from contratacion.infraestructura.adaptadores.salida.bd.contexto import contexto_negocio
from contratacion.infraestructura.adaptadores.salida.bd.negocios import RepositorioNegociosBd
from contratacion.infraestructura.adaptadores.salida.bd.sesion import cerrar_bd, obtener_motor
from contratacion.infraestructura.adaptadores.salida.bd.terminos import RepositorioTerminosBd
from contratacion.infraestructura.adaptadores.salida.seguridad.fabrica import obtener_contrasenas

# La lista que envió el usuario, tal cual, con sus tildes y su «trasito».
LISTA = (
    "produccion, cultura, exposicion, espectaculo, concierto, presentacion, evento, memoria, "
    "historia, gestion, museologia, festival, desfile, organización, video, cobertura, "
    "comunicacion, btl, atl, senalizacion, campana, pauta, publicidad, cinemometro, control, "
    "trasito, foto radar, "
    "camara, educativos, deportivo"
)

FALLOS: list[str] = []


def _seccion(titulo: str) -> None:
    print(f"\n{'=' * 66}\n{titulo}\n{'=' * 66}")


def _marca(condicion: bool, texto: str) -> None:
    if not condicion:
        FALLOS.append(texto)
    print(f"  {'OK ' if condicion else 'MAL'} {texto}")


async def _crear_empresa() -> UUID:
    motor = obtener_motor()
    negocio_id = uuid4()
    await RepositorioNegociosBd(motor).crear(
        AltaEmpresa(
            negocio_id=negocio_id,
            datos=construir_datos_empresa(nombre=f"Verificacion Lote {negocio_id.hex[:6]}"),
            admin_id=uuid4(),
            admin_email=f"lote-{uuid4().hex[:8]}@verificacion.ec",
            admin_nombre="Verificador",
            admin_rol=Rol.SUPER_ADMIN,
            huella=obtener_contrasenas().hash(secrets.token_urlsafe(24)),
            vistas_prueba=tuple(Vista),
            plazo_prueba=Plazo.A1,
            momento=datetime.now(UTC),
        )
    )
    return negocio_id


async def main() -> None:
    motor = obtener_motor()
    repo = RepositorioTerminosBd(motor)
    palabras = [parte.strip().lower() for parte in LISTA.split(",") if parte.strip()]
    claves = [normalizar_termino(palabra) for palabra in palabras]

    async with motor.connect() as c:
        previos: set[str] = set(
            (
                await c.execute(
                    text("SELECT texto_normalizado FROM termino WHERE texto_normalizado = ANY(:k)"),
                    {"k": claves},
                )
            )
            .scalars()
            .all()
        )
    print(f"palabras a enviar: {len(palabras)} | ya existían en el catálogo: {len(previos)}")

    negocio = await _crear_empresa()
    actor = Actor(usuario_id=uuid4(), negocio_id=negocio, rol=str(Rol.SUPER_ADMIN))

    try:
        _seccion("1. Alta en bloque")
        inicio = time.perf_counter()
        resultado = await agregar_terminos(
            palabras, actor=actor, repositorio=repo, maximo_terminos=60
        )
        transcurrido = (time.perf_counter() - inicio) * 1000
        _marca(
            len(resultado.terminos) == len(palabras),
            f"se guardaron {len(resultado.terminos)} de {len(palabras)}",
        )
        print(f"  tardó {transcurrido:.0f} ms  (una a una serían ~{len(palabras) * 2.3:.0f} s)")
        _marca(transcurrido < 3000, f"por debajo de 3 s: {transcurrido:.0f} ms")

        _seccion("2. Sin duplicados")
        async with contexto_negocio(motor, negocio) as c:
            suscritas: Sequence[str] = (
                (
                    await c.execute(
                        text(
                            """
                            SELECT t.texto FROM suscripcion_termino st
                            JOIN termino t ON t.id = st.termino_id
                            WHERE st.negocio_id = :n AND st.activa ORDER BY t.texto
                            """
                        ),
                        {"n": str(negocio)},
                    )
                )
                .scalars()
                .all()
            )
        _marca(len(suscritas) == len(palabras), f"suscripciones activas: {len(suscritas)}")

        _seccion("3. Repetir la misma lista no crea nada")
        otra = await agregar_terminos(palabras, actor=actor, repositorio=repo, maximo_terminos=60)
        _marca(otra.nuevas == 0, f"suscripciones nuevas en la segunda pasada: {otra.nuevas}")
        async with contexto_negocio(motor, negocio) as c:
            total: int = (
                await c.execute(
                    text(
                        "SELECT count(*) FROM suscripcion_termino WHERE negocio_id = :n AND activa"
                    ),
                    {"n": str(negocio)},
                )
            ).scalar_one()
        _marca(total == len(palabras), f"siguen siendo {total}")

        _seccion("4. Los repetidos dentro de la propia lista se colapsan")
        con_repetidos = ["cultura", "cultura", "CULTURA", "cultura ", "festival"]
        tercera = await agregar_terminos(
            con_repetidos, actor=actor, repositorio=repo, maximo_terminos=60
        )
        _marca(len(tercera.terminos) == 2, f"de 5 entradas quedaron {len(tercera.terminos)}")

        _seccion("5. Las palabras inservibles se descartan sin abortar el lote")
        mezcla = ["ok-palabra", "ab", "x", "", "   ", "otra-palabra"]
        cuarta = await agregar_terminos(mezcla, actor=actor, repositorio=repo, maximo_terminos=60)
        _marca(
            set(cuarta.terminos) == {"ok-palabra", "otra-palabra"},
            f"sobrevivieron {sorted(cuarta.terminos)}",
        )

        _seccion("6. Pasarse del tope rechaza el lote entero")
        try:
            await agregar_terminos(
                [f"palabra-de-relleno-{i}" for i in range(40)],
                actor=actor,
                repositorio=repo,
                maximo_terminos=35,
            )
            _marca(False, "no rechazó un lote que supera el tope")
        except DatoInvalido as exc:
            _marca(True, f"rechazado: {exc}")
        async with contexto_negocio(motor, negocio) as c:
            despues: int = (
                await c.execute(
                    text(
                        "SELECT count(*) FROM suscripcion_termino WHERE negocio_id = :n AND activa"
                    ),
                    {"n": str(negocio)},
                )
            ).scalar_one()
        # En el paso 5 se añadieron dos palabras nuevas («ok-palabra» y «otra-palabra»); el 4 no
        # añadió ninguna porque las dos que traía ya estaban suscritas.
        _marca(despues == total + 2, f"no quedó nada a medias: {despues} suscripciones")
    finally:
        async with motor.connect() as c:
            await c.execute(text("DELETE FROM negocio WHERE id = :n"), {"n": str(negocio)})
            await c.commit()
            # Los términos son globales: se borran solo los que creó esta comprobación.
            nuevos = [clave for clave in claves if clave not in previos]
            if nuevos:
                await c.execute(
                    text("DELETE FROM termino WHERE texto_normalizado = ANY(:k)"), {"k": nuevos}
                )
                await c.commit()
        print(f"\nempresa temporal borrada; términos de prueba retirados: {len(nuevos)}")

    print(f"\n{'=' * 66}")
    if FALLOS:
        print(f"FALLARON {len(FALLOS)} COMPROBACIONES:")
        for fallo in FALLOS:
            print(f"  - {fallo}")
        await cerrar_bd()
        raise SystemExit(1)
    print("Todas las comprobaciones pasaron.")
    await cerrar_bd()


if __name__ == "__main__":
    asyncio.run(main())
