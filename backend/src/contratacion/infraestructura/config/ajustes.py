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

    # --- Seguridad ----------------------------------------------------------
    jwt_secreto: str
    jwt_algoritmo: str = "HS256"
    acceso_ttl_min: int = Field(default=15, ge=1)
    refresh_ttl_dias: int = Field(default=30, ge=1)
    max_sesiones_usuario: int = Field(default=2, ge=1)
    clave_cifrado_datos: str
    clave_pepper_hmac: str

    # --- Presencia ----------------------------------------------------------
    presencia_ttl_seg: int = Field(default=60, ge=5)
    heartbeat_seg: int = Field(default=30, ge=5)

    # --- CORS ---------------------------------------------------------------
    # `NoDecode` impide que pydantic-settings intente interpretar el valor como JSON, de modo que
    # el validador de abajo pueda aceptar la forma cómoda `origen1,origen2` propia de `.env`.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    # --- Ingesta ------------------------------------------------------------
    intervalo_ingesta_min: int = Field(default=15, ge=1)
    ventana_solape_ciclos: int = Field(default=2, ge=1)
    presupuesto_peticiones_ciclo: int = Field(default=60, ge=1)
    # Días que se recuperan hacia atrás la primera vez que se busca un término. Es lo que decide si
    # un cliente que agrega una palabra clave ve las contrataciones anteriores a su suscripción.
    ventana_inicial_dias: int = Field(default=90, ge=1)
    limite_terminos_por_ciclo: int = Field(default=20, ge=1)
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
