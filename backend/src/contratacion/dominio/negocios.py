"""Datos de una empresa y las reglas que los validan.

Este archivo existe porque el registro de una empresa es la primera vez que el sistema
recibe datos que **no vienen de una fuente oficial** y que nadie ha revisado antes. Todo lo
demás —contrataciones, entidades, provincias— llega ya ingestado; aquí entra texto escrito a
mano, y por tanto con erratas.

Tres decisiones que merecen explicación
--------------------------------------
**El RUC se valida con su dígito verificador, no solo con «trece dígitos».** Un RUC con un
número cambiado pasa la comprobación de longitud y es un dato que no sirve para nada: no
identifica a nadie y el error no aparece hasta que alguien intenta facturar.

**El RUC es opcional.** La columna lo admite nulo y se mantiene así a propósito. Exigirlo
obligaría a tener el dígito verificador perfecto para poder entrar, y si el algoritmo tuviera
un caso mal contemplado —una sociedad recién constituida, un RUC del exterior— el registro
quedaría bloqueado sin salida. Un dato ausente es mejor que un registro imposible.

**El correo se guarda en minúsculas.** Sin normalizar, `Ana@empresa.ec` y `ana@empresa.ec`
serían dos cuentas distintas para la misma persona, y el índice único no las vería como la
misma. Se normaliza al construir el dato, en un solo sitio.

Lo que **no** se valida, y por qué
---------------------------------
El correo se comprueba con una expresión deliberadamente laxa: dos arrobas no, espacios no, un
punto en el dominio sí. Validar el estándar completo con una expresión regular es imposible
—el estándar admite comentarios entre paréntesis dentro de la dirección— y las expresiones
«completas» que circulan rechazan direcciones válidas. La comprobación de verdad es que el
correo reciba un mensaje, y eso no ocurre aquí. Rechazar de más impide registrarse.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal, overload

from contratacion.dominio.errores import DatoInvalido

LONGITUD_MINIMA_NOMBRE = 3
LONGITUD_MAXIMA_NOMBRE = 160
LONGITUD_MAXIMA_DIRECCION = 200
LONGITUD_MAXIMA_CIUDAD = 80
LONGITUD_MAXIMA_RUC = 13
LONGITUD_MAXIMA_CORREO = 254
LONGITUD_MAXIMA_TELEFONO = 20

# Códigos de provincia del RUC. El 30 no es una provincia: es el registro para quienes tributan
# desde el exterior, y existe de verdad, así que excluirlo dejaría fuera a empresas reales.
PROVINCIAS_RUC: frozenset[str] = frozenset([f"{numero:02d}" for numero in range(1, 25)] + ["30"])

# Tercer dígito: qué clase de contribuyente es. 0 a 5 son personas naturales —cédula—, 6 entidades
# públicas y 9 sociedades. Cualquier otro valor no corresponde a ningún tipo de RUC.
TIPOS_DE_RUC: frozenset[str] = frozenset({"0", "1", "2", "3", "4", "5", "6", "9"})

# Coeficientes del algoritmo del dígito verificador, por tipo de contribuyente. Están aquí,
# escritos como datos y no dentro de un bucle, porque son la única parte del cálculo que se
# puede equivocar en silencio: un coeficiente cambiado produce un dígito que valida otro número.
COEFICIENTES_CEDULA = (2, 1, 2, 1, 2, 1, 2, 1, 2)
COEFICIENTES_SOCIEDAD = (4, 3, 2, 7, 6, 5, 4, 3, 2)

CORREO = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")

# Se admite el prefijo internacional y los separadores que la gente escribe de verdad
# («+593 99 123 4567», «099-123-4567»). Se normaliza antes de comprobar.
TELEFONO = re.compile(r"^\+?\d{7,15}$")


@dataclass(frozen=True, slots=True)
class DatosEmpresa:
    """Identificación y contacto de una empresa.

    Se guarda ya validado y normalizado. Que el tipo sea inmutable no es decoración: el mismo
    objeto se usa para crear la empresa y para auditar el alta, y un dato mutable compartido
    entre los dos usos acabaría teniendo dos contenidos distintos.
    """

    nombre: str
    ruc: str | None = None
    email_contacto: str | None = None
    telefono: str | None = None
    direccion: str | None = None
    ciudad: str | None = None

    def como_diccionario(self) -> dict[str, Any]:
        return {
            "nombre": self.nombre,
            "ruc": self.ruc,
            "email_contacto": self.email_contacto,
            "telefono": self.telefono,
            "direccion": self.direccion,
            "ciudad": self.ciudad,
        }


def limpiar_texto(valor: str | None) -> str:
    """Colapsa los espacios y recorta. Un nombre con un espacio al final no es otro nombre."""
    return " ".join((valor or "").split())


def validar_nombre(valor: str | None) -> str:
    """Razón social o nombre de la empresa."""
    limpio = limpiar_texto(valor)
    if len(limpio) < LONGITUD_MINIMA_NOMBRE:
        raise DatoInvalido(
            f"El nombre de la empresa debe tener al menos {LONGITUD_MINIMA_NOMBRE} caracteres."
        )
    if len(limpio) > LONGITUD_MAXIMA_NOMBRE:
        raise DatoInvalido(
            f"El nombre de la empresa no puede superar {LONGITUD_MAXIMA_NOMBRE} caracteres."
        )
    return limpio


def normalizar_ruc(valor: str | None) -> str | None:
    """Deja solo los dígitos. «1790012345001», «179-001-234-5001» y «179 001 234 5001» son el mismo.

    Devolver `None` para un valor vacío es lo que hace que el campo sea opcional sin necesidad de
    tratar la cadena vacía como un caso aparte en cada sitio.
    """
    limpio = re.sub(r"\D", "", valor or "")
    return limpio or None


def digito_verificador_ruc(base: str) -> int:
    """Calcula el dígito verificador de los nueve primeros dígitos de un RUC.

    Los dos algoritmos son del Servicio de Rentas Internas y se distinguen por el tercer dígito:
    las personas naturales usan el de la cédula —donde el producto de dos dígitos se suma como sus
    cifras, no como el número— y las sociedades y entidades públicas el módulo 11.
    """
    if len(base) != 9 or not base.isdigit():
        raise DatoInvalido("Para calcular el dígito verificador hacen falta nueve dígitos.")

    if base[2] in {"6", "9"}:
        total = sum(
            int(digito) * coeficiente
            for digito, coeficiente in zip(base, COEFICIENTES_SOCIEDAD, strict=True)
        )
        residuo = total % 11
        verificador = 11 - residuo
        if verificador == 11:
            return 0
        if verificador == 10:
            return 1
        return verificador

    total = 0
    for digito, coeficiente in zip(base, COEFICIENTES_CEDULA, strict=True):
        producto = int(digito) * coeficiente
        # La regla de la cédula: si el producto pasa de nueve, se le resta nueve. Se aplica aquí y
        # no con la suma de las cifras porque para un dígito multiplicado por dos son lo mismo, pero
        # restar nueve es la definición y no deja lugar a interpretación.
        if producto > 9:
            producto -= 9
        total += producto
    return (10 - total % 10) % 10


def validar_ruc(valor: str | None) -> str | None:
    """Valida estructura y dígito verificador. Vacío se admite y devuelve `None`."""
    limpio = normalizar_ruc(valor)
    if limpio is None:
        return None

    if len(limpio) != LONGITUD_MAXIMA_RUC:
        raise DatoInvalido(
            f"El RUC debe tener {LONGITUD_MAXIMA_RUC} dígitos y tiene {len(limpio)}."
        )
    if limpio[:2] not in PROVINCIAS_RUC:
        raise DatoInvalido(
            f"Los dos primeros dígitos del RUC son el código de provincia, y {limpio[:2]!r} no "
            "corresponde a ninguna del Ecuador."
        )
    if limpio[2] not in TIPOS_DE_RUC:
        raise DatoInvalido(
            f"El tercer dígito del RUC indica el tipo de contribuyente, y {limpio[2]!r} no es "
            "ninguno de los que existen."
        )
    if limpio[10:] == "000":
        raise DatoInvalido(
            "Los tres últimos dígitos del RUC son el establecimiento y «000» no es un "
            "establecimiento válido."
        )

    esperado = digito_verificador_ruc(limpio[:9])
    if int(limpio[9]) != esperado:
        raise DatoInvalido(
            f"El dígito verificador del RUC no cuadra: debería ser {esperado} y es {limpio[9]}. "
            "Revisa el número."
        )
    return limpio


def normalizar_correo(valor: str | None) -> str | None:
    """Minúsculas y sin espacios. Es la forma que se guarda y con la que se busca."""
    limpio = (valor or "").strip().lower()
    return limpio or None


@overload
def validar_correo(valor: str | None, *, obligatorio: Literal[True]) -> str: ...


@overload
def validar_correo(valor: str | None, *, obligatorio: Literal[False] = False) -> str | None: ...


def validar_correo(valor: str | None, *, obligatorio: bool = False) -> str | None:
    """Correo de contacto de la empresa.

    Las dos sobrecargas no son adorno: con una sola firma, el tipo de vuelta sería `str | None`
    incluso cuando se pide el correo como obligatorio, y cada quien que lo usara tendría que añadir
    una comprobación de nulo que sabe que nunca se cumple. Peor: si alguien la omitiera, el tipo no
    lo avisaría.
    """
    limpio = normalizar_correo(valor)
    if limpio is None:
        if obligatorio:
            raise DatoInvalido("Hace falta un correo de contacto.")
        return None
    if len(limpio) > LONGITUD_MAXIMA_CORREO:
        raise DatoInvalido(f"El correo no puede superar {LONGITUD_MAXIMA_CORREO} caracteres.")
    if not CORREO.match(limpio):
        raise DatoInvalido(f"El correo {limpio!r} no tiene forma de dirección de correo.")
    return limpio


@overload
def validar_telefono(valor: str | None, *, obligatorio: Literal[True]) -> str: ...


@overload
def validar_telefono(valor: str | None, *, obligatorio: Literal[False] = False) -> str | None: ...


def validar_telefono(valor: str | None, *, obligatorio: bool = False) -> str | None:
    """Teléfono de contacto, con separadores o sin ellos."""
    crudo = (valor or "").strip()
    if not crudo:
        if obligatorio:
            raise DatoInvalido("Hace falta un teléfono de contacto.")
        return None

    # Se conserva el prefijo internacional y se quitan los separadores: «+593 99 123 4567» se guarda
    # como «+593991234567», que sigue siendo legible y se puede marcar desde cualquier país.
    compacto = re.sub(r"[\s().-]", "", crudo)
    if len(compacto) > LONGITUD_MAXIMA_TELEFONO:
        raise DatoInvalido(f"El teléfono no puede superar {LONGITUD_MAXIMA_TELEFONO} caracteres.")
    if not TELEFONO.match(compacto):
        raise DatoInvalido(
            f"El teléfono {crudo!r} no tiene forma de número. Se admiten entre 7 y 15 dígitos, "
            "con el prefijo del país si es un número internacional."
        )
    return compacto


def validar_direccion(valor: str | None) -> str | None:
    """Dirección de la empresa. Texto libre, solo se acota la longitud."""
    limpio = limpiar_texto(valor)
    if not limpio:
        return None
    if len(limpio) > LONGITUD_MAXIMA_DIRECCION:
        raise DatoInvalido(f"La dirección no puede superar {LONGITUD_MAXIMA_DIRECCION} caracteres.")
    return limpio


def validar_ciudad(valor: str | None) -> str | None:
    """Ciudad o cantón."""
    limpio = limpiar_texto(valor)
    if not limpio:
        return None
    if len(limpio) > LONGITUD_MAXIMA_CIUDAD:
        raise DatoInvalido(f"La ciudad no puede superar {LONGITUD_MAXIMA_CIUDAD} caracteres.")
    return limpio


def construir_datos_empresa(
    *,
    nombre: str | None,
    ruc: str | None = None,
    email_contacto: str | None = None,
    telefono: str | None = None,
    direccion: str | None = None,
    ciudad: str | None = None,
) -> DatosEmpresa:
    """Valida y normaliza el bloque completo. Lanza `DatoInvalido` con el motivo concreto.

    Se valida todo antes de devolver nada: el caso de uso que registra una empresa recibe un dato ya
    correcto o una excepción, y nunca un objeto a medio validar que haya que volver a comprobar.
    """
    return DatosEmpresa(
        nombre=validar_nombre(nombre),
        ruc=validar_ruc(ruc),
        email_contacto=validar_correo(email_contacto),
        telefono=validar_telefono(telefono),
        direccion=validar_direccion(direccion),
        ciudad=validar_ciudad(ciudad),
    )
