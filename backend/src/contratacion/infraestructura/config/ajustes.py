"""Ajustes de la aplicación, validados al arrancar (fallo rápido).

Reglas:
- Los secretos son **obligatorios**: sin ellos la aplicación no arranca.
- El comodín `*` en `CORS_ORIGINS` se **rechaza**: es la vulnerabilidad V1 del ADR-000
  (credenciales permitidas desde cualquier origen).
- En producción se exige longitud mínima de secreto.

Los nombres de los campos coinciden con las variables de `.env.example` (sin distinguir mayúsculas).

El archivo `.env` se busca en `backend/` y en la raíz del repositorio, de modo que la configuración
no dependa del directorio desde el que se arranque el proceso.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

LONGITUD_MINIMA_SECRETO = 32
CAMPOS_SECRETOS = ("jwt_secreto", "clave_cifrado_datos", "clave_pepper_hmac")

# Rutas deterministas: el archivo de entorno no depende del directorio de ejecución.
RAIZ_BACKEND = Path(__file__).resolve().parents[4]
RAIZ_REPOSITORIO = RAIZ_BACKEND.parent
ARCHIVOS_ENTORNO: tuple[Path, ...] = (RAIZ_BACKEND / ".env", RAIZ_REPOSITORIO / ".env")


class Ajustes(BaseSettings):
    """Configuración tipada y validada del proceso."""

    model_config = SettingsConfigDict(
        # Precedencia creciente entre archivos: gana el último que exista. Las variables de entorno
        # siempre tienen prioridad sobre cualquier archivo.
        env_file=ARCHIVOS_ENTORNO,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Entorno ------------------------------------------------------------
    entorno: str = "dev"

    # --- Dependencias -------------------------------------------------------
    # PostgreSQL es obligatorio: contiene las credenciales de la base de datos.
    database_url: str
    # El caché es OPCIONAL. Vacío significa «desarrollo sin caché»: el sistema funciona leyendo de
    # la base de datos. Al desplegar se configura con el almacén gestionado (`rediss://...`).
    redis_url: str = ""

    # --- Base de datos ------------------------------------------------------
    # Dimensiones del pool de conexiones **por proceso**. Cada worker de uvicorn abre el suyo, así
    # que el total contra PostgreSQL es la suma de `bd_pool_size` y `bd_max_overflow` multiplicada
    # por el número de procesos. Con la base en la misma máquina conviene un pool moderado y varios
    # workers; con la base remota, muy pocos procesos, porque cada ranura es una conexión que el
    # proveedor limita.
    #
    # Los valores por defecto de SQLAlchemy (5 + 10) son un compromiso razonable para una base
    # cercana, pero no son visibles en ningún sitio: sin declararlos aquí, quien ajuste el
    # despliegue no tiene forma de saber cuál es el techo real de conexiones por proceso.
    bd_pool_size: int = Field(default=10, ge=1)
    bd_max_overflow: int = Field(default=10, ge=0)
    # Segundos que una petición espera por una conexión libre antes de fallar. El valor por defecto
    # de SQLAlchemy son 30 s, que convierten una saturación en medio minuto de espera por cliente;
    # cinco segundos hacen que el fallo sea rápido y visible, que es lo que se quiere diagnosticar.
    bd_pool_timeout_seg: int = Field(default=5, ge=1)
    # Segundos tras los cuales una conexión del pool se cierra y se reabre. Tiene que ser **más
    # corto** que la inactividad máxima del servidor: si fuera más largo, la conexión moriría antes
    # de reciclarse y volvería a hacer falta la comprobación previa que se quitó por cara.
    bd_pool_recycle_seg: int = Field(default=180, ge=1)

    # --- Seguridad ----------------------------------------------------------
    jwt_secreto: str
    jwt_algoritmo: str = "HS256"
    acceso_ttl_min: int = Field(default=15, ge=1)
    refresh_ttl_dias: int = Field(default=30, ge=1)
    max_sesiones_usuario: int = Field(default=2, ge=1)
    # Segundos en los que el token de renovación **anterior** sigue valiendo después de una
    # rotación.
    #
    # Existe por un falso positivo que se da solo: el servidor rota el token y la respuesta se
    # pierde —se corta la conexión, se duerme el portátil—, así que el navegador reintenta con el
    # viejo. Sin esta ventana eso se lee como «hay dos copias en circulación» y se cierran **todas**
    # las sesiones de la cuenta. Pasó tres veces en un día, con el usuario delante del panel sin
    # hacer nada raro.
    #
    # Es corta a propósito: solo cubre el intervalo en el que un reintento y un robo son
    # indistinguibles. Un token robado usado un minuto después sigue disparando el cierre de todo.
    # Ponerla a cero restaura el comportamiento estricto de antes.
    refresh_gracia_seg: int = Field(default=30, ge=0, le=300)
    # Minutos de inactividad tras los cuales una sesión deja de servir. Ocho horas cubre una jornada
    # con margen: quien se va a comer no vuelve a entrar, y quien deja el panel abierto el fin de
    # semana no sigue dentro el lunes.
    #
    # El plazo lo aplica el almacén de sesiones vivas con el tiempo de vida de la clave, así que no
    # hay ninguna tarea que recorra sesiones para cerrarlas. **Lo rearman solo las peticiones de
    # verdad**: ni el latido del panel ni el refresco de token cuentan, porque una pestaña olvidada
    # hace las dos cosas sola y mantendría la sesión abierta indefinidamente.
    #
    # Con el almacén caído o sin configurar, el plazo no se aplica y se comprueba contra la base de
    # datos como antes. Es una degradación deliberada: el sistema sigue entero, solo cierra sesiones
    # por caducidad del token y no por inactividad.
    sesion_inactividad_min: int = Field(default=480, ge=1)
    clave_cifrado_datos: str
    clave_pepper_hmac: str

    @property
    def sesion_inactividad_seg(self) -> int:
        """El plazo de inactividad en segundos, que es como lo quieren el almacén y el dominio.

        Se calcula en vez de declararse como un ajuste aparte para que no puedan separarse: dos
        campos que dicen lo mismo son dos campos que acaban diciendo cosas distintas.
        """
        return self.sesion_inactividad_min * 60

    # --- Presencia ----------------------------------------------------------
    presencia_ttl_seg: int = Field(default=60, ge=5)
    heartbeat_seg: int = Field(default=30, ge=5)

    # --- CORS ---------------------------------------------------------------
    # `NoDecode` impide que pydantic-settings intente interpretar el valor como JSON, de modo que
    # el validador de abajo pueda aceptar la forma cómoda `origen1,origen2` propia de `.env`.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    # --- Exportación ---------------------------------------------------------
    # Directorio donde viven las plantillas de Excel que sube cada empresa.
    #
    # En el despliegue apunta a un volumen del `compose`, para que sobreviva a recrear el contenedor
    # —una actualización de imagen no puede llevarse por delante las plantillas de los clientes—.
    # Por defecto es relativo al directorio de trabajo, que es lo cómodo en desarrollo.
    #
    # `deploy/copias.sh` copia este directorio además de la base: una plantilla perdida no es
    # irrecuperable —cada empresa tiene su archivo— pero sí es una molestia evitable.
    plantillas_dir: str = "plantillas"

    # --- Ingesta ------------------------------------------------------------
    intervalo_ingesta_min: int = Field(default=15, ge=1)
    # Cada cuánto se relee **solo el listado** de necesidades, al margen del ciclo completo.
    #
    # La fuente no publica histórico: solo lo que está vigente en el momento de pedirlo. Una
    # necesidad que entre y salga entre dos ciclos completos no se puede recuperar después —se
    # midió: con el worker parado 49 horas se perdieron 19 necesidades del Excel del cliente—, así
    # que esperar un cuarto de hora entre lecturas del listado deja un hueco por el que se escapan
    # datos. La vuelta corta lo estrecha a dos minutos y medio.
    #
    # No puede bajarse mucho más: cada vuelta es una petición de ~1,9 MB a un origen que responde
    # 429 con facilidad, y el listado entero se procesa y se compara contra la huella de cada fila.
    intervalo_vigilancia_seg: int = Field(default=150, ge=10)
    ventana_solape_ciclos: int = Field(default=2, ge=1)
    # Peticiones por ciclo, para todas las fuentes.
    #
    # OCDS gasta una por término y año leído (la primera página y las últimas de cada uno), así que
    # con veinte términos rondan las sesenta. El tope tiene que quedar por encima o el último
    # término del lote se queda a medias en cada vuelta y **nunca llega a cerrarse**, y entonces la
    # cola deja de avanzar. Estaba en 60 y el `.env.example` ya decía 90 por este motivo: el
    # defecto se alinea con lo documentado para que un despliegue que olvide la variable no
    # empeore en silencio.
    presupuesto_peticiones_ciclo: int = Field(default=90, ge=1)
    # Fichas de necesidad que se leen por ciclo para guardar sus ítems con el CPC.
    #
    # Es un presupuesto **aparte** del de arriba y mucho mayor, porque son trabajos distintos: el
    # listado de necesidades se trae entero con **una** petición, mientras que cada ficha con su
    # tabla de CPC cuesta una. Con el listado medido —1.779 necesidades— el histórico completo son
    # 1.779 peticiones, así que a 300 por ciclo se pone al día en unos seis ciclos y, a partir de
    # ahí, solo hay que leer lo que cambia. El valor está acotado por el tiempo, no por el deseo:
    # a 0,6 s por petición son unos tres minutos, que caben entre dos ciclos sin retrasar el
    # siguiente. Bajarlo a cero desactiva la lectura de fichas.
    fichas_items_por_ciclo: int = Field(default=300, ge=0)
    # Días que se recuperan hacia atrás la primera vez que se busca un término. Es lo que decide si
    # un cliente que agrega una palabra clave ve las contrataciones anteriores a su suscripción.
    ventana_inicial_dias: int = Field(default=90, ge=1)
    limite_terminos_por_ciclo: int = Field(default=20, ge=1)
    # Páginas del **rabo del listado general** de OCDS que se leen como mucho en una vuelta.
    #
    # El rabo es una secuencia ordenada por fecha, así que lo que se publica está al final: se lee
    # la última página y hacia atrás mientras haga falta. Cuánto hace falta se estima por el tiempo
    # transcurrido desde el último ciclo (el listado crece 37,8 páginas al día), y este tope solo
    # entra en juego cuando esa estimación se dispara: el primer arranque, o un worker que estuvo
    # parado semanas. Sin tope, la primera vuelta se traería el año entero de golpe —10.363 páginas
    # contra un origen que responde 429—.
    paginas_generales_por_ciclo: int = Field(default=40, ge=1)
    # Cuántas palabras clave puede vigilar un negocio a la vez.
    #
    # Estaba en 20 y el uso real lo desbordó en la primera semana: una lista de temas de interés
    # razonable —«produccion, cultura, exposicion, espectaculo…»— pasa de treinta. El tope no
    # protege a la fuente, porque el que la protege es `limite_terminos_por_ciclo`: el `worker`
    # consulta como mucho veinte términos por vuelta, los más olvidados primero. Lo único que
    # cambiaba con el tope bajo era que el cliente no podía **guardar** lo que quería vigilar.
    maximo_terminos_negocio: int = Field(default=60, ge=1)

    # --- Búsqueda y palabras clave ------------------------------------------
    ttl_resultados_seg: int = Field(default=900, ge=1)
    # Los agregados de las gráficas caducan con el mismo criterio que una página de resultados: no
    # tiene sentido que un total siga siendo válido cuando las filas que lo componen ya no lo son.
    ttl_estadisticas_seg: int = Field(default=900, ge=1)
    # Los desplegables cambian cuando entra una contratación nueva, no cuando alguien los mira: son
    # los mismos para todos los usuarios y para todas las pantallas. Con un TTL más largo que el de
    # los resultados se paga el recorrido del histórico —que es la consulta más cara del sistema—
    # una vez por hora en lugar de una vez por ciclo.
    ttl_catalogo_seg: int = Field(default=3600, ge=1)

    # --- Caché en proceso ---------------------------------------------------
    # Segundos que un proceso recuerda en su propia memoria la generación del caché y los permisos
    # vigentes. Es lo que quita un comando a Redis por petición: sin esto, cada lectura consulta
    # primero la generación y después su clave, y con cientos de usuarios por segundo eso son
    # millones de comandos al día.
    #
    # Unos segundos de desfase son irrelevantes frente a los 900 s de vida de una entrada, y la
    # generación solo cambia al cerrar un ciclo de ingesta. **Cero lo desactiva**, y es el valor que
    # usan las pruebas: un memo que sobrevive de una prueba a la siguiente haría que una viera la
    # generación que dejó la anterior.
    cache_proceso_seg: int = Field(default=5, ge=0)

    # --- Desarrollo ---------------------------------------------------------
    # Permite construir el actor a partir de cabeceras para poder probar los endpoints antes de que
    # exista el inicio de sesión. **Nunca se acepta en producción**, ni aunque se ponga a `true`:
    # sin autenticación no hay forma de saber quién llama, y con el actor en el aire todas las
    # decisiones de autorización (incluido el aislamiento entre negocios) dejarían de ser ciertas.
    permitir_actor_de_desarrollo: bool = False

    # --- Módulo administrativo (solo v1) -----------------------------------
    modulo_admin_habilitado: bool = True

    # --- Retención y exportación -------------------------------------------
    retencion_dias_datos_personales: int = Field(default=365, ge=1)
    export_async_umbral_filas: int = Field(default=20_000, ge=1)
    export_ttl_horas: int = Field(default=24, ge=1)

    # --- Observabilidad ----------------------------------------------------
    log_nivel: str = "INFO"

    # --- Validaciones ------------------------------------------------------
    @field_validator("cors_origins", mode="before")
    @classmethod
    def _separar_por_comas(cls, valor: Any) -> Any:
        """Permite `A,B,C` en `.env` además del formato JSON."""
        if isinstance(valor, str):
            return [parte.strip() for parte in valor.split(",") if parte.strip()]
        return valor

    @field_validator("cors_origins")
    @classmethod
    def _prohibir_comodin(cls, valor: list[str]) -> list[str]:
        if "*" in valor:
            raise ValueError(
                "CORS_ORIGINS no puede contener '*': permitiría credenciales desde cualquier "
                "origen. Enumera los orígenes exactos."
            )
        return valor

    @field_validator("jwt_algoritmo")
    @classmethod
    def _algoritmo_permitido(cls, valor: str) -> str:
        permitidos = {"HS256", "HS384", "HS512"}
        if valor not in permitidos:
            raise ValueError(f"JWT_ALGORITMO debe ser uno de {sorted(permitidos)}.")
        return valor

    @model_validator(mode="after")
    def _exigir_secretos_fuertes_en_produccion(self) -> Ajustes:
        if self.es_produccion:
            for campo in CAMPOS_SECRETOS:
                if len(getattr(self, campo)) < LONGITUD_MINIMA_SECRETO:
                    raise ValueError(
                        f"{campo.upper()} debe tener al menos {LONGITUD_MINIMA_SECRETO} "
                        "caracteres en producción."
                    )
        return self

    # --- Derivados ---------------------------------------------------------
    @property
    def es_produccion(self) -> bool:
        return self.entorno.lower() in {"prod", "produccion", "production"}

    @property
    def cache_habilitada(self) -> bool:
        """Hay caché configurado. Sin `REDIS_URL` el sistema funciona sin caché."""
        return bool(self.redis_url.strip())

    @property
    def ventana_solape_min(self) -> int:
        """Margen de relectura entre ciclos de ingesta, para no perder registros."""
        return self.intervalo_ingesta_min * self.ventana_solape_ciclos


@lru_cache(maxsize=1)
def obtener_ajustes() -> Ajustes:
    """Devuelve los ajustes validados (se calculan una sola vez por proceso)."""
    return Ajustes()
