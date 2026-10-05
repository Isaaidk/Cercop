"""Dependencias compartidas por los enrutadores.

Aquí vive una decisión incómoda pero deliberada: **todavía no hay autenticación**. Los casos de uso
necesitan saber quién llama para aplicar el aislamiento entre negocios, así que hasta que exista el
inicio de sesión (fase 4) el actor se construye a partir de cabeceras.

Eso no se deja abierto «mientras tanto». Se cierra con dos cerrojos, porque un atajo de desarrollo
que sobrevive al despliegue es la peor clase de agujero:

1. Hay que activarlo de forma explícita (`PERMITIR_ACTOR_DE_DESARROLLO`), y por defecto está
   apagado.
2. **En producción se rechaza siempre**, incluso si alguien lo enciende. La comprobación es de
   entorno, no de configuración: no depende de que nadie recuerde desactivar una bandera.

Con el actor apagado, los endpoints devuelven `503` y explican que falta la autenticación. Es un
fallo honesto: el sistema prefiere no responder antes que responder sin saber a quién.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request, status

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.casos_uso.consentimiento import exigir_aceptado
from contratacion.aplicacion.casos_uso.gestionar_acceso import vistas_vigentes
from contratacion.aplicacion.puertos.accesos import RepositorioAccesos
from contratacion.aplicacion.puertos.cache import Cache
from contratacion.aplicacion.puertos.consultas import RepositorioConsultas
from contratacion.aplicacion.puertos.cpc import RepositorioCpc
from contratacion.aplicacion.puertos.cuentas import (
    RepositorioCuentas,
    RepositorioSesiones,
    SesionGuardada,
    SesionPorId,
)
from contratacion.aplicacion.puertos.exportacion import RepositorioColumnasExportacion
from contratacion.aplicacion.puertos.negocios import RepositorioNegocios
from contratacion.aplicacion.puertos.plantillas import AlmacenPlantillas, RepositorioPlantillas
from contratacion.aplicacion.puertos.politicas import (
    RepositorioConsentimientos,
    RepositorioPoliticas,
)
from contratacion.aplicacion.puertos.presencia import BusEventos, RegistroPresencia
from contratacion.aplicacion.puertos.seguridad import Claims, ServicioContrasenas, TipoToken
from contratacion.aplicacion.puertos.terminos import RepositorioTerminos
from contratacion.aplicacion.puertos.usuarios import (
    CierreDeSesiones,
    RegistroAuditoria,
    RepositorioUsuarios,
)
from contratacion.aplicacion.sesiones_vivas import (
    SesionesConVida,
    VidaDeSesion,
    abrir,
    seguir,
)
from contratacion.dominio.acceso import Vista
from contratacion.dominio.errores import EmpresaSuspendida, SesionRevocada
from contratacion.dominio.sesiones import EstadoSesion, MotivoRevocacion
from contratacion.infraestructura.adaptadores.salida.archivos.local import obtener_almacen
from contratacion.infraestructura.adaptadores.salida.bd.accesos import RepositorioAccesosBd
from contratacion.infraestructura.adaptadores.salida.bd.columnas import RepositorioColumnasBd
from contratacion.infraestructura.adaptadores.salida.bd.consultas import RepositorioConsultasBd
from contratacion.infraestructura.adaptadores.salida.bd.cpc import RepositorioCpcBd
from contratacion.infraestructura.adaptadores.salida.bd.cuentas import (
    RepositorioCuentasBd,
    RepositorioSesionesBd,
)
from contratacion.infraestructura.adaptadores.salida.bd.negocios import RepositorioNegociosBd
from contratacion.infraestructura.adaptadores.salida.bd.plantillas import RepositorioPlantillasBd
from contratacion.infraestructura.adaptadores.salida.bd.politicas import (
    RepositorioConsentimientosBd,
    RepositorioPoliticasBd,
)
from contratacion.infraestructura.adaptadores.salida.bd.sesion import obtener_motor
from contratacion.infraestructura.adaptadores.salida.bd.terminos import RepositorioTerminosBd
from contratacion.infraestructura.adaptadores.salida.bd.usuarios import RepositorioUsuariosBd
from contratacion.infraestructura.adaptadores.salida.cache.cliente import obtener_cache
from contratacion.infraestructura.adaptadores.salida.presencia.fabrica import (
    obtener_bus,
    obtener_presencia,
)
from contratacion.infraestructura.adaptadores.salida.seguridad.fabrica import (
    obtener_contrasenas,
    obtener_tokens,
)
from contratacion.infraestructura.config.ajustes import Ajustes, obtener_ajustes

SIN_AUTENTICACION = "Falta la cabecera `Authorization` con un token de acceso válido."

MENSAJES_POR_MOTIVO: dict[MotivoRevocacion, str] = {
    # Este es el que justifica que todo esto exista. Cuando alguien entra con las mismas
    # credenciales y se supera el máximo de sesiones, la que se cae es la más antigua, y quien
    # estaba en ella tiene que enterarse de **eso** y no de un «vuelve a entrar» genérico: puede
    # ser un compañero de equipo compartiendo la cuenta o alguien que se ha quedado con la
    # contraseña, y son dos respuestas muy distintas.
    MotivoRevocacion.EVICCION: (
        "Hay otra persona conectada en tu cuenta. Se cerró tu sesión, la más antigua, porque se "
        "alcanzó el máximo de sesiones a la vez. Si no esperabas este aviso, cambia tu contraseña."
    ),
    MotivoRevocacion.LOGOUT: "Se cerró la sesión desde este equipo. Vuelve a entrar.",
    MotivoRevocacion.ADMIN: (
        "Un administrador de tu empresa cerró la sesión. Pídele que te diga por qué."
    ),
    MotivoRevocacion.REUSO_DETECTADO: (
        "Por seguridad se cerraron todas tus sesiones. Suele ocurrir cuando el panel queda abierto "
        "en dos pestañas o en dos equipos a la vez. Vuelve a entrar; si el aviso se repite, cambia "
        "tu contraseña."
    ),
    MotivoRevocacion.CIERRE_VENTANA: "Se cerró la ventana del navegador. Vuelve a entrar.",
}


def _sesion_cerrada(guardada: SesionGuardada | None) -> SesionRevocada:
    """El error de la sesión del token cuando ya no sirve, con el motivo explicado.

    Se distinguen los tres finales posibles porque no se arreglan igual: una sesión caducada se
    resuelve volviendo a entrar, una revocada por otra persona exige mirar quién tiene la
    contraseña, y una que no existe significa que ya se borró.
    """
    if guardada is None:
        return SesionRevocada("Tu sesión ya no existe. Vuelve a entrar.", motivo="inexistente")

    sesion = guardada.sesion
    # Estado activo pero pasada de fecha: caducó, nadie la revocó.
    if sesion.estado is EstadoSesion.ACTIVA:
        return SesionRevocada("Tu sesión ha caducado. Vuelve a entrar.", motivo="expirada")

    motivo = sesion.motivo_revocacion
    if motivo is None:
        return SesionRevocada("Tu sesión se cerró. Vuelve a entrar.", motivo="desconocido")
    return SesionRevocada(
        MENSAJES_POR_MOTIVO.get(motivo, "Tu sesión se cerró. Vuelve a entrar."),
        motivo=str(motivo),
    )


def ajustes_de_la_app() -> Ajustes:
    """Ajustes ya validados del proceso."""
    return obtener_ajustes()


AjustesDep = Annotated[Ajustes, Depends(ajustes_de_la_app)]

# Rutas que comprueban la sesión **sin rearmar el plazo de inactividad**.
#
# Son las dos que mantienen la conexión abierta por su cuenta: el latido, que el panel repite cada
# treinta segundos, y el flujo de eventos, que reenvía una instantánea cada quince. Ninguna de las
# dos es actividad de nadie —se repiten solas, con la persona delante o sin ella—, así que si
# rearmaran el plazo, la pestaña de un equipo que nadie mira no se cerraría jamás.
#
# Se declaran por ruta y no por caso de uso porque el plazo se rearma en una sola puerta, la que
# atraviesan todas las peticiones. La alternativa —que cada ruta dijera si cuenta o no— obligaría a
# acordarse en cada endpoint nuevo, y el que se olvidara no daría ningún error: simplemente dejaría
# sesiones abiertas para siempre.
RUTAS_QUE_NO_REARMAN_EL_PLAZO = frozenset(
    {
        "/v1/presencia/latido",
        "/v1/presencia/eventos",
    }
)

MENSAJE_POR_INACTIVIDAD = (
    "Tu sesión se cerró por inactividad. Vuelve a entrar; no se ha perdido nada de tu trabajo."
)

# El nombre lleva «avisos» porque en este módulo `registro` ya se usa para otras cosas y no conviene
# confundirlos al leer una traza.
registro_de_avisos = logging.getLogger(__name__)


async def _sesion_verificada(
    *,
    cache: Cache,
    sesiones: RepositorioSesiones,
    claims: Claims,
    inactividad_seg: int,
    renovar: bool,
) -> None:
    """Comprueba que la sesión del token siga viva, y lanza si no lo está.

    El camino barato es el almacén: una lectura, sin viaje a la base. La base solo se consulta
    cuando el almacén **no responde** —no está configurado, o está caído—, y entonces el
    comportamiento es el de antes de que existiera este módulo.

    Que el almacén no responda y que la sesión no conste son cosas distintas, y confundirlas tiene
    los dos finales que hay que evitar: echar a todo el mundo cuando el almacén se apaga, o no
    cerrar ninguna sesión cuando no hay almacén. Por eso `seguir` devuelve tres estados.
    """
    vida = await seguir(
        cache,
        sesion_id=claims.sesion_id,
        usuario_id=claims.usuario_id,
        inactividad_seg=inactividad_seg,
        renovar=renovar,
    )

    if vida is VidaDeSesion.VIVA:
        return

    if vida is VidaDeSesion.SIN_RESPUESTA:
        guardada = await sesiones.por_id(negocio_id=claims.negocio_id, sesion_id=claims.sesion_id)
        if guardada is None or not guardada.sesion.vigente(datetime.now(UTC)):
            raise _sesion_cerrada(guardada)
        if guardada.sesion.usuario_id != claims.usuario_id:
            raise _sesion_cerrada(None)
        return

    # La sesión ya no consta en el almacén. Aquí **sí** se pregunta a la base, y lo que responda
    # decide entre dos finales que se parecen y no son lo mismo: cerrar la sesión de verdad, o
    # reponer la clave que el almacén perdió.
    return await _resolver_clave_ausente(
        cache=cache, sesiones=sesiones, claims=claims, inactividad_seg=inactividad_seg
    )


async def _resolver_clave_ausente(
    *,
    cache: Cache,
    sesiones: SesionPorId,
    claims: Claims,
    inactividad_seg: int,
) -> None:
    """Decide si la ausencia de la clave es un cierre o una pérdida del almacén.

    Antes esto daba por hecho que **lo único** que borra la clave sin cambiar el estado de la sesión
    es el plazo de inactividad, y no es cierto: una política de memoria que desaloje claves, un
    reinicio del almacén o un cambio de instancia también la borran. En esos casos el sistema
    echaba a la persona con el mensaje «se cerró por inactividad» —que era falso, no había estado
    inactiva— y desde fuera se veía como «de vez en cuando me saca sin motivo».

    La distinción sale del dato que ya está en la base: **cuándo se usó la sesión por última vez**.

    - Si la última vez fue hace más de lo que dura el plazo, la inactividad hizo su trabajo: se
      cierra, y con su motivo.
    - Si fue hace menos, la persona estaba trabajando y la clave se perdió por otra razón: se
      repone y se la deja pasar.
    """
    guardada = await sesiones.por_id(negocio_id=claims.negocio_id, sesion_id=claims.sesion_id)
    if guardada is None or guardada.sesion.usuario_id != claims.usuario_id:
        # La fila no está, o es de otro: no hay nada que explicar sin revelar información de otra
        # cuenta, y el mensaje tiene que ser el mismo en los dos casos.
        raise _sesion_cerrada(None)

    instante = datetime.now(UTC)
    sesion = guardada.sesion
    if not sesion.vigente(instante):
        # Estado revocado o fecha pasada: un cierre de verdad, con su motivo.
        raise _sesion_cerrada(guardada)

    restante = inactividad_seg - int((instante - sesion.ultimo_uso_en).total_seconds())
    if restante <= 0:
        # Cumplido el plazo sin usarse: se cierra por inactividad, que es lo que se le dice.
        raise SesionRevocada(MENSAJE_POR_INACTIVIDAD, motivo="inactividad")

    # La clave se perdió mientras la sesión seguía viva y usándose. Se repone **con el tiempo que le
    # queda** y no con el plazo entero: reponerlo completo correría el vencimiento hacia delante en
    # cada pérdida, y una sesión que se pierde de vez en cuando acabaría sin cerrarse nunca por
    # inactividad. Con el tiempo restante, el vencimiento sigue contándose desde el último uso real.
    await abrir(
        cache,
        sesion_id=claims.sesion_id,
        usuario_id=claims.usuario_id,
        inactividad_seg=max(1, restante),
    )
    registro_de_avisos.warning(
        "La clave de la sesión %s no estaba en el almacén y la sesión seguía viva: se repone",
        claims.sesion_id,
    )


async def obtener_actor(
    peticion: Request,
    ajustes: AjustesDep,
    sesiones: SesionesDep,
    negocios: NegociosDep,
    # El alias explícito no es cosmético: FastAPI convierte los guiones bajos del nombre del
    # parámetro en guiones, así que sin él la cabecera esperada sería `autorizacion` y ningún
    # cliente la manda. El síntoma era el peor posible: el inicio de sesión respondía bien y
    # **todas** las peticiones siguientes devolvían 401 «falta la cabecera Authorization», que es
    # literalmente cierto y no ayuda nada a averiguar por qué.
    autorizacion: Annotated[str | None, Header(alias="Authorization")] = None,
    x_desarrollo_usuario: Annotated[str | None, Header()] = None,
    x_desarrollo_negocio: Annotated[str | None, Header()] = None,
    x_desarrollo_rol: Annotated[str | None, Header()] = None,
) -> Actor:
    """Actor de la petición: quién llama y con qué ámbito.

    El camino normal es el token de acceso: se verifican la firma, la caducidad y el tipo, y de él
    salen el usuario, el negocio y el rol. **El negocio viene siempre del token**, nunca de un
    parámetro de la petición (R-04).

    Además de la firma se comprueba que **la sesión siga viva**, y esa comprobación es la que decide
    cuánto dura una sesión sin usarse. El token de acceso no lleva estado: una vez firmado vale
    hasta que caduca, así que sin esto expulsar una sesión no expulsaba nada durante los quince
    minutos siguientes —seguía leyendo datos como si nada— y el aviso al usuario llegaba cuando ya
    no importaba.

    Cuesta una lectura del almacén, y de paso **rearma el plazo de inactividad**: es aquí, en la
    puerta por la que pasa todo lo que la persona pide de verdad, donde tiene sentido contar que
    alguien está usando el sistema. Las rutas que se repiten solas quedan fuera, y están declaradas
    en `RUTAS_QUE_NO_REARMAN_EL_PLAZO`.

    Sin token queda el atajo de desarrollo, que solo funciona con `PERMITIR_ACTOR_DE_DESARROLLO` y
    **jamás en producción**: sin autenticación no hay forma de saber quién llama.
    """
    if autorizacion and autorizacion.lower().startswith("bearer "):
        token = autorizacion.split(" ", 1)[1].strip()
        claims = obtener_tokens().verificar(token, TipoToken.ACCESO)
        await _sesion_verificada(
            cache=obtener_cache(),
            sesiones=sesiones,
            claims=claims,
            inactividad_seg=ajustes.sesion_inactividad_seg,
            renovar=peticion.scope.get("path", "").rstrip("/") not in RUTAS_QUE_NO_REARMAN_EL_PLAZO,
        )

        # Una empresa suspendida no deja pasar a nadie, ni a su propio administrador. Se comprueba
        # aquí, en la puerta por la que pasan todas las peticiones, y no en cada endpoint: si
        # hubiera que acordarse de añadirlo en cada sitio, el día que se añadiera uno nuevo la
        # empresa suspendida volvería a leer datos por esa puerta nueva. Cuesta una lectura por
        # clave primaria y es lo que hace que la suspensión surta efecto en la siguiente petición en
        # vez de cuando caduque el token de acceso, que son quince minutos de servicio cortado.
        #
        # Se deja tal cual aunque la sesión ya no cueste una lectura: convertirla en una caché con
        # unos segundos de vida retrasaría la suspensión, y la suspensión es justo lo que tiene que
        # notarse en la petición siguiente.
        empresa = await negocios.obtener(negocio_id=claims.negocio_id)
        if empresa is None or not empresa.activo:
            raise EmpresaSuspendida()

        return Actor(
            usuario_id=claims.usuario_id,
            negocio_id=claims.negocio_id,
            rol=claims.rol,
        )

    if ajustes.es_produccion or not ajustes.permitir_actor_de_desarrollo:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=SIN_AUTENTICACION,
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not x_desarrollo_usuario or not x_desarrollo_negocio:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Sin token, y faltan las cabeceras X-Desarrollo-Usuario y X-Desarrollo-Negocio. "
                "Son un sustituto temporal del inicio de sesión."
            ),
        )

    try:
        return Actor(
            usuario_id=UUID(x_desarrollo_usuario),
            negocio_id=UUID(x_desarrollo_negocio),
            rol=x_desarrollo_rol or "consultor",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El identificador de usuario o de negocio no es un UUID válido.",
        ) from exc


ActorDep = Annotated[Actor, Depends(obtener_actor)]


def repositorio_consultas() -> RepositorioConsultas:
    """Repositorio de lectura del histórico."""
    return RepositorioConsultasBd(obtener_motor())


def repositorio_terminos() -> RepositorioTerminos:
    """Catálogo de términos y suscripciones."""
    return RepositorioTerminosBd(obtener_motor())


def repositorio_accesos() -> RepositorioAccesos:
    """Concesiones de acceso a vistas."""
    return RepositorioAccesosBd(obtener_motor())


def repositorio_cuentas() -> RepositorioCuentas:
    """Cuentas de usuario."""
    return RepositorioCuentasBd(obtener_motor())


def repositorio_sesiones() -> RepositorioSesiones:
    """Sesiones abiertas, con el almacén de sesiones vivas al día.

    El envoltorio se construye **aquí y solo aquí**, y por eso todos los caminos que abren o cierran
    una sesión —el inicio, el cierre, la expulsión, la revocación administrativa y el cambio de
    contraseña— pasan por él sin que ninguno tenga que acordarse de nada.
    """
    return SesionesConVida(
        RepositorioSesionesBd(obtener_motor()),
        obtener_cache(),
        inactividad_seg=obtener_ajustes().sesion_inactividad_seg,
    )


def repositorio_politicas() -> RepositorioPoliticas:
    """Versiones publicadas de los textos legales."""
    return RepositorioPoliticasBd(obtener_motor())


def repositorio_consentimientos() -> RepositorioConsentimientos:
    """Aceptaciones y revocaciones, dentro del plano de negocio."""
    return RepositorioConsentimientosBd(obtener_motor())


def repositorio_negocios() -> RepositorioNegocios:
    """Empresas registradas."""
    return RepositorioNegociosBd(obtener_motor())


def repositorio_plantillas() -> RepositorioPlantillas:
    """Plantilla de Excel de cada empresa."""
    return RepositorioPlantillasBd(obtener_motor())


def repositorio_columnas() -> RepositorioColumnasExportacion:
    """Columnas que cada empresa quiere en sus exportaciones."""
    return RepositorioColumnasBd(obtener_motor())


def repositorio_cpc() -> RepositorioCpc:
    """Términos de CPC que cada empresa vigila."""
    return RepositorioCpcBd(obtener_motor())


def almacen_plantillas() -> AlmacenPlantillas:
    """Dónde vive el archivo de la plantilla."""
    return obtener_almacen()


def repositorio_usuarios() -> RepositorioUsuarios:
    """Alta, baja y consulta de las cuentas del negocio."""
    return RepositorioUsuariosBd(obtener_motor())


ConsultasDep = Annotated[RepositorioConsultas, Depends(repositorio_consultas)]
TerminosDep = Annotated[RepositorioTerminos, Depends(repositorio_terminos)]
AccesosDep = Annotated[RepositorioAccesos, Depends(repositorio_accesos)]
CuentasDep = Annotated[RepositorioCuentas, Depends(repositorio_cuentas)]
SesionesDep = Annotated[RepositorioSesiones, Depends(repositorio_sesiones)]
PoliticasDep = Annotated[RepositorioPoliticas, Depends(repositorio_politicas)]
ConsentimientosDep = Annotated[RepositorioConsentimientos, Depends(repositorio_consentimientos)]
NegociosDep = Annotated[RepositorioNegocios, Depends(repositorio_negocios)]
UsuariosDep = Annotated[RepositorioUsuarios, Depends(repositorio_usuarios)]

# El puerto estrecho y el repositorio grande se declaran por separado a propósito: el caso de uso
# recibe el estrecho, así que no puede llamar a nada que no necesite. El objeto que se le
# entrega es el de siempre —la comprobación es estructural—, sin dos implementaciones.
CierreSesionesDep = Annotated[CierreDeSesiones, Depends(repositorio_sesiones)]
AuditoriaDep = Annotated[RegistroAuditoria, Depends(repositorio_cuentas)]
PlantillasDep = Annotated[RepositorioPlantillas, Depends(repositorio_plantillas)]
AlmacenPlantillasDep = Annotated[AlmacenPlantillas, Depends(almacen_plantillas)]
ColumnasDep = Annotated[RepositorioColumnasExportacion, Depends(repositorio_columnas)]
CpcDep = Annotated[RepositorioCpc, Depends(repositorio_cpc)]

# El caché entra en pocos routers, pero cuando entra es para leer un contador y nada más: el de la
# versión de los datos, que el panel consulta cada minuto para saber si hay algo nuevo. Se expone el
# puerto (`Cache`), no el cliente concreto, porque lo único que se hace con él es leer una clave.
CacheDep = Annotated[Cache, Depends(obtener_cache)]


def servicio_contrasenas() -> ServicioContrasenas:
    """Derivación y comprobación de contraseñas."""
    return obtener_contrasenas()


ContrasenasDep = Annotated[ServicioContrasenas, Depends(servicio_contrasenas)]


def registro_de_presencia() -> RegistroPresencia:
    """Almacén de señales de vida.

    Se resuelve por la fábrica en cada petición en lugar de guardarse en el estado de la aplicación:
    la fábrica ya memoriza la instancia, y así esta dependencia no impone nada sobre cómo se
    construye ni obliga a que las pruebas monten el ciclo de vida entero.
    """
    return obtener_presencia()


def bus_de_presencia() -> BusEventos:
    """Bus de avisos entre procesos."""
    return obtener_bus()


PresenciaDep = Annotated[RegistroPresencia, Depends(registro_de_presencia)]
BusDep = Annotated[BusEventos, Depends(bus_de_presencia)]


async def vistas_del_actor(actor: ActorDep, accesos: AccesosDep) -> frozenset[Vista]:
    """Vistas que tiene concedidas quien llama.

    Es la puerta que convierte el control de vistas en algo efectivo: hasta ahora los permisos se
    guardaban y se podían consultar, pero no se exigían al leer. El permiso se resuelve con una
    caché de un minuto, y retirar un acceso sube la generación, así que el cambio se nota en la
    petición siguiente y no cuando caduque el caché.
    """
    return await vistas_vigentes(
        negocio_id=actor.negocio_id,
        usuario_id=actor.usuario_id,
        repositorio=accesos,
        cache=obtener_cache(),
    )


VistasDep = Annotated[frozenset[Vista], Depends(vistas_del_actor)]


async def consentimiento_del_actor(actor: ActorDep, consentimientos: ConsentimientosDep) -> None:
    """Puerta de bloqueo: niega el paso si la cuenta debe aceptar alguna política.

    **No es una dependencia global.** Se aplica enrutador por enrutador a propósito: una dependencia
    global alcanzaría también a `/salud`, al inicio de sesión y a la pantalla de aceptación, y
    habría que ir excluyéndolos con casos concretos. La primera ruta que alguien añada y se olvide
    de excluir dejaría fuera de servicio algo tan básico como poder entrar o poder aceptar.

    Se aplica a lo que devuelve datos o cambia el estado del negocio, no a lo que solo informa de
    quién tiene la página abierta: la presencia no da ningún dato del sistema, y bloquearla dejaría
    a la pantalla de aceptación sin poder avisar de que sigue abierta.
    """
    await exigir_aceptado(actor, consentimientos=consentimientos)


# El valor que devuelve la dependencia no se usa: existe para que la comprobación se ejecute. Se
# tipa como `None` para que quede claro que ningún endpoint debe leerlo.
ConsentimientoDep = Annotated[None, Depends(consentimiento_del_actor)]
