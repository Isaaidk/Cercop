"""Reglas del acceso a vistas por suscripción.

Decisiones centrales, y por qué:

1. **El vencimiento es un instante absoluto y se guarda.** Guardar «30 días» y sumarlos en cada
   lectura haría que el mismo registro significara cosas distintas según cuándo se leyera, y no
   permitiría auditar cuándo venció de verdad.
2. **Se comprueba al leer, nunca al limpiar.** Una comparación `vence_en > ahora` no puede fallar;
   un proceso en segundo plano que marque vencimientos, sí. La seguridad no puede depender de que un
   job se ejecute a tiempo.
3. **Denegar por defecto.** La ausencia de concesión es la ausencia de permiso. Conceder inserta una
   fila; retirar marca `revocado_en`. «Dar acceso» y «deshabilitar la vista» son el mismo modelo.
4. **El historial no se sobrescribe.** Extender es insertar otra fila; la concesión vigente es la de
   vencimiento más lejano, de modo que **extender nunca acorta**.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from contratacion.dominio.errores import ErrorDominio, SinPermiso
from contratacion.dominio.ingesta import ZONA_FUENTE
from contratacion.dominio.plazos import sumar_meses
from contratacion.dominio.roles import Rol, es_administrativo

# Antelación con la que se avisa de un vencimiento próximo, para poder renovar a tiempo.
DIAS_AVISO_VENCIMIENTO = 7

SEGUNDOS_POR_DIA = 86_400

# El permiso se cachea muy poco a propósito: si se retira el acceso y la respuesta siguiera en
# caché, el usuario conservaría la vista. Un minuto acota la ventana sin cargar la base.
TTL_PERMISO_SEG = 60


def generacion_de_acceso(usuario_id: UUID) -> str:
    """Nombre de la generación de permisos de un usuario.

    Se usa como si fuera el nombre de una fuente: el caché compone la clave real. Retirar un acceso
    incrementa este contador, de modo que cualquier permiso cacheado queda inservible de inmediato y
    no hay que esperar a que expire.
    """
    return f"acceso:{usuario_id}"


def clave_permiso(usuario_id: UUID, generacion: int) -> str:
    """Clave del conjunto de vistas vigentes de un usuario."""
    return f"acceso:permiso:{generacion}:{usuario_id}"


def clave_tablero(usuario_id: UUID, generacion: int) -> str:
    """Clave del tablero de vistas de un usuario."""
    return f"acceso:tablero:{generacion}:{usuario_id}"


class Vista(StrEnum):
    """Vistas del panel cuyo acceso se puede conceder por separado.

    Es un conjunto **cerrado**: el cliente no puede inventar una vista nueva, porque cada miembro
    representa una frontera de autorización. Añadir una es un cambio de código y de migración, que
    es exactamente lo que se quiere en un límite de seguridad.
    """

    NECESIDADES = "necesidades"
    OFERTAS = "ofertas"
    CONTRATACIONES = "contrataciones"
    GRAFICAS = "graficas"


ETIQUETAS_VISTA: dict[Vista, str] = {
    Vista.NECESIDADES: "Necesidades",
    Vista.OFERTAS: "Ofertas",
    Vista.CONTRATACIONES: "Contrataciones",
    Vista.GRAFICAS: "Gráficas",
}


class Plazo(StrEnum):
    """Plazos que el administrador puede elegir. No hay plazos libres."""

    D7 = "7d"
    D30 = "30d"
    M3 = "3m"
    M6 = "6m"
    A1 = "1a"

    @property
    def etiqueta(self) -> str:
        """Texto para el botón del panel."""
        return ETIQUETAS_PLAZO[self]

    @property
    def es_de_calendario(self) -> bool:
        """¿Se calcula en meses de calendario en lugar de en días exactos?"""
        return self in {Plazo.M3, Plazo.M6, Plazo.A1}

    def calcular(self, desde: datetime) -> datetime:
        """Instante de vencimiento a partir de un momento de concesión.

        Los dos primeros plazos son duraciones exactas: «30 días» es una cifra comercial, y
        30 x 24 h es lo que el cliente espera. Los tres últimos son de calendario, porque «un año»
        debe caer en el mismo día del año siguiente; ahí el ajuste de día es imprescindible: sin él,
        tres meses desde el 31 de enero acabarían en marzo en lugar de terminar el 30 de abril.
        """
        if self is Plazo.D7:
            return desde + timedelta(days=7)
        if self is Plazo.D30:
            return desde + timedelta(days=30)
        if self is Plazo.M3:
            return sumar_meses(desde, 3)
        if self is Plazo.M6:
            return sumar_meses(desde, 6)
        return sumar_meses(desde, 12)


ETIQUETAS_PLAZO: dict[Plazo, str] = {
    Plazo.D7: "7 días",
    Plazo.D30: "30 días",
    Plazo.M3: "3 meses",
    Plazo.M6: "6 meses",
    Plazo.A1: "1 año",
}


def plazo_desde_codigo(codigo: str) -> Plazo:
    """Traduce el código que envía el panel. Un valor fuera del catálogo se rechaza.

    Es importante rechazar en lugar de caer a un valor por defecto: un plazo no reconocido que se
    interpretara como «el más largo» regalaría una anualidad por un error de escritura.
    """
    try:
        return Plazo(codigo.strip().lower())
    except ValueError as exc:
        permitidos = ", ".join(plazo.value for plazo in Plazo)
        raise ErrorDominio(
            f"Plazo no reconocido: {codigo!r}. Se espera uno de: {permitidos}."
        ) from exc


def vista_desde_codigo(codigo: str) -> Vista:
    """Traduce el código de vista. Igual que con el plazo, no hay valores por defecto."""
    try:
        return Vista(codigo.strip().lower())
    except ValueError as exc:
        permitidos = ", ".join(vista.value for vista in Vista)
        raise ErrorDominio(
            f"Vista no reconocida: {codigo!r}. Se espera una de: {permitidos}."
        ) from exc


@dataclass(frozen=True, slots=True)
class AccesoVista:
    """Una concesión de acceso a una vista, tal y como está registrada."""

    vista: Vista
    otorgado_en: datetime
    vence_en: datetime
    plazo: Plazo | None = None
    revocado_en: datetime | None = None

    def vigente(self, momento: datetime) -> bool:
        """¿Concede el acceso en este instante?

        Reproduce exactamente la condición que aplica la base de datos
        (`vence_en > now() AND revocado_en IS NULL`), de modo que la decisión no depende de dónde se
        evalúe. Una revocación siempre es inmediata: no existe retirar acceso «a partir de mañana».
        """
        return self.revocado_en is None and self.vence_en > momento

    def dias_restantes(self, momento: datetime) -> int:
        """Días completos que quedan, redondeando hacia arriba.

        Se redondea hacia arriba para no mostrar «0 días» mientras el acceso sigue siendo válido:
        doce horas restantes son «1 día» para quien tiene que renovar.
        """
        restante = self.vence_en - momento
        if restante <= timedelta(0):
            return 0
        return math.ceil(restante.total_seconds() / SEGUNDOS_POR_DIA)

    def por_vencer(self, momento: datetime, umbral_dias: int = DIAS_AVISO_VENCIMIENTO) -> bool:
        return self.vigente(momento) and self.dias_restantes(momento) <= umbral_dias


def concesion_vigente(
    accesos: Iterable[AccesoVista], momento: datetime
) -> dict[Vista, AccesoVista]:
    """Concesión que manda para cada vista: la vigente con el vencimiento más lejano.

    De ahí que extender sea insertar y no sobrescribir: sumar una fila con vencimiento posterior
    alarga el acceso, y una fila nueva nunca puede acortar lo ya concedido.
    """
    resultado: dict[Vista, AccesoVista] = {}
    for acceso in accesos:
        if not acceso.vigente(momento):
            continue
        actual = resultado.get(acceso.vista)
        if actual is None or acceso.vence_en > actual.vence_en:
            resultado[acceso.vista] = acceso
    return resultado


def puede_ver(accesos: Iterable[AccesoVista], vista: Vista, momento: datetime) -> bool:
    """¿El usuario tiene concedida esta vista?"""
    return vista in concesion_vigente(accesos, momento)


@dataclass(frozen=True, slots=True)
class EstadoVista:
    """Fila del tablero administrativo: una vista con su estado, tenga acceso o no."""

    vista: Vista
    etiqueta: str
    vigente: bool
    vence_en: datetime | None = None
    dias_restantes: int = 0
    plazo: Plazo | None = None
    por_vencer: bool = False


def tablero(
    accesos: Iterable[AccesoVista],
    momento: datetime,
    umbral_dias: int = DIAS_AVISO_VENCIMIENTO,
) -> tuple[EstadoVista, ...]:
    """Estado de **todas** las vistas, para que el panel pueda pintar verde y rojo.

    Se devuelven todas y no solo las concedidas porque el panel necesita distinguir «sin acceso»
    (rojo) de «vista inexistente» (error); una lista con solo las concedidas obligaría al frontend a
    conocer el catálogo, que es justo lo que se quiere evitar.
    """
    vigentes = concesion_vigente(accesos, momento)
    filas: list[EstadoVista] = []
    for vista in Vista:
        acceso = vigentes.get(vista)
        if acceso is None:
            filas.append(EstadoVista(vista=vista, etiqueta=ETIQUETAS_VISTA[vista], vigente=False))
            continue
        filas.append(
            EstadoVista(
                vista=vista,
                etiqueta=ETIQUETAS_VISTA[vista],
                vigente=True,
                vence_en=acceso.vence_en,
                dias_restantes=acceso.dias_restantes(momento),
                plazo=acceso.plazo,
                por_vencer=acceso.por_vencer(momento, umbral_dias),
            )
        )
    return tuple(filas)


def momento_local(momento: datetime) -> datetime:
    """Expresa un instante en la zona del negocio, para mostrar fechas en el panel."""
    return momento.astimezone(ZONA_FUENTE)


def puede_gestionar(rol: str) -> bool:
    """¿Este rol puede conceder o retirar accesos?

    Delega en `dominio.roles`, que es donde vive el catálogo. Antes esta comprobación tenía su
    propia lista de roles administrativos escrita a mano, y una segunda copia del mismo catálogo es
    una que se queda atrás en cuanto se añade un rol.
    """
    return es_administrativo(rol)


# Qué fuente de datos alimenta cada vista.
#
# La correspondencia es explícita y vive aquí porque es una decisión de **autorización**, no de
# presentación: el día que una vista cambiara de fuente, cambiaría quién ve qué. Una vista sin
# fuente —«Ofertas» hoy— no concede ningún dato todavía, y eso está escrito a propósito en lugar
# de dejarlo como una omisión que alguien pueda rellenar por parecido.
FUENTES_POR_VISTA: dict[Vista, tuple[str, ...]] = {
    Vista.NECESIDADES: ("NCO",),
    Vista.CONTRATACIONES: ("OCDS",),
    Vista.OFERTAS: (),
    Vista.GRAFICAS: (),
}

# Vistas que dan acceso a datos de contrataciones, para saber si alguien puede consultar algo.
VISTAS_DE_DATOS = (Vista.NECESIDADES, Vista.CONTRATACIONES)


def fuentes_para_vistas(vistas: Iterable[Vista]) -> tuple[str, ...]:
    """Fuentes que puede leer quien tiene concedidas estas vistas, sin repetir y en orden estable.

    Una tupla vacía significa **ninguna fuente**, no «todas». La distinción es la más importante
    de esta función: si una lista vacía se interpretara como «sin restricción», un usuario al que
    se le acaban de retirar todas las vistas pasaría a ver el histórico completo. El fallo sería
    silencioso y del lado peligroso.
    """
    fuentes: set[str] = set()
    for vista in vistas:
        fuentes.update(FUENTES_POR_VISTA.get(vista, ()))
    return tuple(sorted(fuentes))


def negocio_objetivo(rol: str, negocio_del_actor: UUID, negocio_solicitado: UUID | None) -> UUID:
    """Resuelve sobre qué negocio puede actuar el actor.

    - `admin_negocio`: siempre el suyo. Si la petición menciona otro, se **rechaza** en lugar de
      ignorarlo, porque ignorarlo ocultaría un intento de cruzar el aislamiento.
    - `super_admin`: puede actuar sobre el negocio que indique, y queda registrado en auditoría.

    La base de datos vuelve a comprobarlo después con RLS: esta función es la primera barrera, no la
    única.
    """
    normalizado_rol = rol.strip().lower()
    if not es_administrativo(normalizado_rol):
        raise SinPermiso("El rol de este usuario no puede gestionar accesos.")

    if normalizado_rol == Rol.SUPER_ADMIN:
        return negocio_solicitado or negocio_del_actor

    if negocio_solicitado is not None and negocio_solicitado != negocio_del_actor:
        raise SinPermiso("Un administrador solo puede gestionar su propio negocio.")
    return negocio_del_actor
