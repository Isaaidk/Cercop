"""Políticas del sistema y consentimiento del usuario.

Aquí se decide **qué textos rigen, en qué versión y quién los ha aceptado**. Nada de esto depende de
HTTP ni de la base: son reglas que se pueden leer y discutir sin ejecutar nada.

Por qué la huella del texto y no solo el número de versión
----------------------------------------------------------
Guardar «aceptó la versión 3» parece suficiente y no lo es. Si alguien corrige una coma de la
versión 3 sin publicar la 4 —lo más fácil del mundo—, todas las aceptaciones existentes siguen
contando como válidas y la evidencia dice que esa persona aceptó un texto que nunca vio.

Por eso la aceptación guarda **versión y huella**, y se considera vigente solo si coinciden las dos
con el texto publicado ahora mismo. Una edición sin subir la versión no se convierte en una
aceptación fantasma: deja de coincidir, y el sistema vuelve a pedir la aceptación. La evidencia se
corrige sola.

Qué se normaliza antes de calcular la huella, y qué no
-----------------------------------------------------
Se unifican los saltos de línea y se quitan los espacios del final de cada línea. Nada más.

Es deliberado. Sin esa normalización, un archivo guardado con retornos de carro de Windows
produciría una huella distinta a la del mismo texto con saltos de línea de Unix, y obligaría a
**todo el mundo** a volver a aceptar un texto que, leído, es idéntico. Pero cualquier normalización
de más —quitar espacios internos, igualar mayúsculas, ignorar la puntuación— cambiaría el
significado y haría que la huella dejara de demostrar qué se leyó.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class TipoPolitica(StrEnum):
    """Los textos legales del sistema.

    Los tres valores coinciden con la restricción `CHECK` de la tabla de consentimientos. Añadir uno
    nuevo es un cambio de código revisado **y** una migración, nunca solo una fila.
    """

    TERMINOS_USO = "terminos_uso"
    AVISO_PRIVACIDAD = "aviso_privacidad"
    TRATAMIENTO_DATOS = "tratamiento_datos"


# Texto que acompaña a cada política en la interfaz. Se sirve desde el código y no desde la base por
# la misma razón que las vistas del panel: es una decisión de producto, no un dato editable.
TITULO_POLITICA: dict[TipoPolitica, str] = {
    TipoPolitica.TERMINOS_USO: "Términos y condiciones de uso",
    TipoPolitica.AVISO_PRIVACIDAD: "Aviso de privacidad",
    TipoPolitica.TRATAMIENTO_DATOS: "Tratamiento de datos personales",
}

# Lo que hay que aceptar para usar el aplicativo. Hoy es solo un texto, y la lista existe para que
# añadir un segundo sea cambiar esta tupla en lugar de buscar cada sitio donde se comprueba.
POLITICAS_OBLIGATORIAS: tuple[TipoPolitica, ...] = (TipoPolitica.TERMINOS_USO,)


@dataclass(frozen=True, slots=True)
class Politica:
    """Una versión publicada de un texto legal."""

    tipo: TipoPolitica
    version: int
    texto: str
    hash: str
    vigente_desde: datetime

    @property
    def titulo(self) -> str:
        return TITULO_POLITICA[self.tipo]

    def coincide_con(self, *, version: int, hash_texto: str) -> bool:
        """¿Esta es la versión y el texto que el usuario dice haber leído?

        Es la comprobación que convierte una aceptación en evidencia. Se comparan las dos cosas y no
        solo la versión, porque un texto editado sin subir la versión seguiría coincidiendo por
        número y la aceptación registraría un documento distinto del que se leyó.
        """
        return self.version == version and self.hash == hash_texto


@dataclass(frozen=True, slots=True)
class Consentimiento:
    """Una aceptación registrada, tal y como quedó en la base."""

    tipo: TipoPolitica
    version: int
    hash_texto: str
    aceptado_en: datetime
    revocado_en: datetime | None = None

    @property
    def vigente(self) -> bool:
        """Sigue en pie. Una aceptación revocada no cuenta, aunque esté en el historial."""
        return self.revocado_en is None


def huella_texto(texto: str) -> str:
    """Huella del texto que se muestra, para poder demostrar cuál se leyó.

    Se calcula sobre el texto ya normalizado, nunca sobre el original: el mismo documento guardado
    desde otro sistema operativo tiene que dar la misma huella, o cada copia del repositorio
    obligaría a revisar la aceptación de todos los usuarios.
    """
    return hashlib.sha256(_normalizar(texto).encode("utf-8")).hexdigest()


def _normalizar(texto: str) -> str:
    unificado = texto.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(linea.rstrip() for linea in unificado.strip().split("\n"))


@dataclass(frozen=True, slots=True)
class Pendientes:
    """Lo que un usuario todavía debe aceptar."""

    politicas: tuple[Politica, ...]

    @property
    def hay_pendientes(self) -> bool:
        return bool(self.politicas)

    @property
    def tipos(self) -> tuple[TipoPolitica, ...]:
        return tuple(politica.tipo for politica in self.politicas)

    def como_diccionario(self) -> dict[str, object]:
        return {
            "hay_pendientes": self.hay_pendientes,
            "politicas": [
                {
                    "tipo": str(politica.tipo),
                    "titulo": politica.titulo,
                    "version": politica.version,
                    "hash": politica.hash,
                }
                for politica in self.politicas
            ],
        }


def pendientes(
    *,
    publicadas: tuple[Politica, ...],
    aceptadas: tuple[Consentimiento, ...],
    obligatorias: tuple[TipoPolitica, ...] = POLITICAS_OBLIGATORIAS,
) -> Pendientes:
    """Qué le falta aceptar a un usuario, comparando versión **y** huella.

    Se recorre lo obligatorio y no lo aceptado: si se recorriera al revés, una política obligatoria
    nueva se colaría sin que nadie tuviera que aceptarla, que es justo el fallo que hay que evitar
    cuando se añade un texto legal.

    Una política obligatoria **sin publicar** no se exige. Bloquear a todo el mundo esperando un
    texto que todavía no existe dejaría el sistema inutilizable por un despliegue a medias; lo que
    hay que arreglar entonces es la publicación, no la puerta.
    """
    por_tipo = {politica.tipo: politica for politica in publicadas}
    aceptadas_por_tipo: dict[TipoPolitica, Consentimiento] = {}
    for consentimiento in aceptadas:
        if consentimiento.vigente:
            # Si hay varias, la última marca el estado. Las anteriores son historial.
            aceptadas_por_tipo[consentimiento.tipo] = consentimiento

    faltantes: list[Politica] = []
    for tipo in obligatorias:
        publicada = por_tipo.get(tipo)
        if publicada is None:
            continue
        aceptada = aceptadas_por_tipo.get(tipo)
        if aceptada is None or not publicada.coincide_con(
            version=aceptada.version, hash_texto=aceptada.hash_texto
        ):
            faltantes.append(publicada)

    return Pendientes(politicas=tuple(faltantes))
