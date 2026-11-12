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
ENTORNOS_PRODUCCION = frozenset({"prod", "produccion", "production"})
ENTORNOS_CONOCIDOS = ENTORNOS_PRODUCCION | {"dev", "desarrollo", "development", "local", "test"}

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
    # Segundos de tope para conectar con el almacén y para cada respuesta suya. Sin tope, un Redis
    # inalcanzable hacía esperar a cada petición lo que tardara el sistema operativo en rendirse.
    # Ver `cache/redis.py` y `resiliencia.py`.
    cache_timeout_seg: float = Field(default=2.0, gt=0, le=30)

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
    # Segundos para abrir una conexión nueva con PostgreSQL antes de rendirse. El valor del
    # controlador (60 s) convierte una base inalcanzable en un minuto de espera por petición; diez
    # segundos cubren de sobra un servidor remoto lento y fallan a tiempo cuando no está.
    bd_conexion_timeout_seg: float = Field(default=10.0, gt=0, le=60)
    # Tope de cada sentencia, en milisegundos, que PostgreSQL aplica a las conexiones de **este**
    # proceso. Con 1.000 personas, una consulta que se queda pensando no solo tarda: retiene una
    # conexión del pool y, con unas pocas así, el resto de peticiones espera turno y acaba en 503.
    # Treinta segundos están muy por encima de cualquier pantalla (la exportación de 20.000 filas
    # tarda unos pocos) y cortan lo que ya no va a contestar a nadie. Cero lo desactiva.
    #
    # **El worker lo pone a cero por su cuenta** (`tareas/worker.py`): la ingesta y el
    # mantenimiento tienen consultas largas legítimas. Por eso no se fija por rol en la base.
    bd_statement_timeout_ms: int = Field(default=30_000, ge=0)
    # Tope de una transacción abierta **sin hacer nada**. Es la red contra una conexión que se queda
    # con la transacción a medias (una excepción mal atrapada, un `await` a un servicio ajeno dentro
    # del bloque): sin él, retiene sus bloqueos de fila y su ranura del pool para siempre. El worker
    # también lo pone a cero: su bloqueo de ingesta vive en una conexión ociosa durante el ciclo.
    bd_idle_tx_timeout_ms: int = Field(default=60_000, ge=0)
    # Cómo se presentan las conexiones en `pg_stat_activity`. El worker usa otro nombre.
    bd_nombre_aplicacion: str = "cercoapp-api"

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
    # indistinguibles. Un token robado usado un rato después sigue disparando el cierre de todo.
    # Ponerla a cero restaura el comportamiento estricto de antes.
    #
    # Cinco minutos y no los treinta segundos de antes, porque el reintento legítimo no siempre
    # tarda segundos: un portátil que se suspende, un ascensor que se queda sin cobertura o un
    # proxy que corta la conexión dejan la respuesta perdida **minutos**. Con la ventana corta, el
    # reintento caía fuera y se interpretaba como robo: la persona aparecía en el acceso sin haber
    # hecho nada. Lo que sigue sin admitirse es reutilizar **dos generaciones atrás**, que ya no
    # tiene explicación inocente.
    refresh_gracia_seg: int = Field(default=300, ge=0, le=300)
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

    # --- Borde HTTP (auditoría de seguridad, doc 38) ------------------------
    # Cuántos proxys propios hay delante de la API. La IP de quien llama se toma de la dirección
    # que añade el último de ellos en `X-Forwarded-For`, y no de la primera, que la escribe el
    # cliente. `0`: sin proxy delante, se usa la conexión directa. **En Railway y detrás de Caddy
    # tiene que ser `1`**: con `0` todas las peticiones parecen venir del proxy y el freno de inicio
    # de sesión se reparte entre todos los usuarios. Ver `entrada/http/proteccion.py`.
    proxy_saltos: int = Field(default=0, ge=0, le=5)
    # Tamaño máximo del cuerpo de cualquier petición, en MB. El archivo más grande que acepta una
    # ruta son 8 MB (RUP, PDF a firmar, plantilla de Excel); el tope deja margen para el resto del
    # formulario. Cero lo desactiva, y no hay motivo para hacerlo.
    max_cuerpo_mb: int = Field(default=20, ge=0, le=200)
    # Dominios desde los que el worker puede bajar anexos (TDR, pliegos). Un enlace a cualquier otro
    # sitio —o una redirección hacia él— se rechaza: sin esta lista, un enlace de la ficha podía
    # hacer que el worker pidiera direcciones internas de la red del despliegue (SSRF). Se admite
    # el dominio y sus subdominios.
    anexos_dominios_permitidos: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["compraspublicas.gob.ec"]
    )

    # --- Presencia ----------------------------------------------------------
    presencia_ttl_seg: int = Field(default=60, ge=5)
    heartbeat_seg: int = Field(default=30, ge=5)

    # --- CORS ---------------------------------------------------------------
    # `NoDecode` impide que pydantic-settings intente interpretar el valor como JSON, de modo que
    # el validador de abajo pueda aceptar la forma cómoda `origen1,origen2` propia de `.env`.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    # Correo de las alertas. Vacío: el aviso queda en el panel y no se intenta enviar.
    smtp_host: str = ""
    smtp_puerto: int = 587
    smtp_usuario: str = ""
    smtp_clave: str = ""
    smtp_desde: str = ""

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
    # TDR temporales. No es la base: el archivo se borra al día y la carpeta tiene tope.
    tdr_dir: str = "tdr"

    # --- IA -------------------------------------------------------------------
    # Cualquier servicio con la API de chat de OpenAI: Groq y Gemini tienen capa gratuita, y Ollama
    # corre en la misma máquina sin clave. Sin `ia_url` la oferta se arma con la plantilla y los
    # datos de la empresa, sin modelo.
    ia_url: str = ""
    ia_clave: str = ""
    ia_modelo: str = "llama-3.3-70b-versatile"
    # Llamadas al modelo a la vez por proceso. Con 4 procesos son 16 en vuelo: el resto espera turno
    # en vez de tumbar el servicio externo o agotar su cuota por minuto.
    ia_concurrencia: int = Field(default=4, ge=1, le=32)
    ia_tiempo_seg: float = Field(default=45.0, ge=5.0, le=120.0)
    # Vueltas de herramientas que el asistente (chat) puede dar antes de contestar. Cada vuelta es
    # una llamada al modelo: más vueltas responden preguntas más enrevesadas, pero tardan más.
    asistente_max_rondas: int = Field(default=4, ge=1, le=6)

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
    # Fichas que la vuelta corta lee **cuando trae necesidades nuevas**, para que la ínfima llegue
    # al panel con sus CPC y no quince minutos después. A dos en vuelo y 0,6 s entre peticiones,
    # 60 fichas son menos de un minuto, que cabe de sobra en los 150 s de la vuelta. Cero lo apaga.
    fichas_por_vigilancia: int = Field(default=60, ge=0)
    # Proxies de salida de NCO, separados por coma. Vacío: se lee `NCO_PROXY_URL` o se sale directo.
    nco_proxy_urls: str = ""
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

    # --- Mantenimiento del histórico ----------------------------------------
    # Cada cuánto se mira si algún plazo de proformas cruzó y se retira lo que ya venció.
    #
    # El vencimiento **no** se guarda en ninguna fila, se deduce de la fecha. Lo que este trabajo
    # aporta es que la caché se entere: una página guardada hace diez minutos sigue contando como
    # abierta una ínfima que ya venció, y no da ningún error. Los cinco minutos son el compromiso
    # entre eso y no estar subiendo la generación todo el rato —subirla deja inservible lo cacheado
    # y el catálogo de desplegables se paga detrás de cada subida—. La ventana de los vencimientos
    # es este mismo número, así que cada uno se cuenta una sola vez.
    intervalo_mantenimiento_seg: int = Field(default=300, ge=30)
    # Días que se conserva una ínfima **después** de que venza su plazo de proformas.
    #
    # Es una decisión de negocio, no técnica: estas filas son las de los procesos que ya se cerraron
    # o se adjudicaron, y son las que sostienen las estadísticas del periodo y la consulta de un
    # concurso pasado. Un borrado no se deshace. Cero retira en cuanto vence.
    purga_plazo_dias: int = Field(default=7, ge=0)
    # Cuántas filas se retiran como mucho en cada vuelta.
    #
    # Acota el trabajo, no la política: una pasada que borrara las cinco mil filas vencidas de golpe
    # mantendría bloqueadas sus páginas el tiempo suficiente para que el resto del sistema lo
    # notara, y compite con la ingesta por la misma base. **Cero desactiva la retención** —se sigue
    # informando de lo que venció, y no se borra nada—, que es lo que hay que poner si se prefiere
    # conservar el histórico entero.
    purga_max_filas_por_vuelta: int = Field(default=500, ge=0)

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
    @field_validator("entorno")
    @classmethod
    def _entorno_conocido(cls, valor: str) -> str:
        """Un entorno mal escrito no puede convertirse en «desarrollo» sin que nadie se entere.

        `ENTORNO=produccion ` o `ENTORNO=prd` se leían como desarrollo: documentación de la API
        publicada, secretos cortos admitidos y sin HSTS. Ahora un valor desconocido no arranca.
        """
        limpio = valor.strip().lower()
        if limpio not in ENTORNOS_CONOCIDOS:
            raise ValueError(
                f"ENTORNO={valor!r} no se reconoce. Usa uno de: {sorted(ENTORNOS_CONOCIDOS)}."
            )
        return limpio

    @field_validator("anexos_dominios_permitidos", mode="before")
    @classmethod
    def _dominios_por_comas(cls, valor: Any) -> Any:
        if isinstance(valor, str):
            return [parte.strip().lower() for parte in valor.split(",") if parte.strip()]
        return valor

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
        return self.entorno.lower() in ENTORNOS_PRODUCCION

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
