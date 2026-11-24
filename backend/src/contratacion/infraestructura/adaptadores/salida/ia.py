"""Modelo de lenguaje por la API de chat de OpenAI.

Sirve para Groq, Gemini (endpoint compatible), OpenRouter u Ollama local: solo cambian la URL, la
clave y el nombre del modelo. Un semáforo por proceso limita las llamadas en vuelo para que mil
usuarios no agoten la cuota del proveedor en un minuto ni dejen al API sin conexiones.

Encima del semáforo va el cortacircuitos `ia` (ver `resiliencia.py`). El semáforo limita las
llamadas **en vuelo**; el circuito limita además cuántas pueden **esperar turno** —cuatro por cada
ranura— y, si el proveedor encadena fallos, deja de llamarlo un rato y responde al instante. Sin
eso, con el proveedor caído cada petición agotaba sus tres intentos (más de dos minutos) antes de
fallar, y con ellas se iban las corrutinas del proceso.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Literal

import httpx

from contratacion.dominio.errores import EstadoInvalido
from contratacion.infraestructura.adaptadores.salida.resiliencia import (
    Cortacircuitos,
    EstadoCircuito,
    FalloDelServicio,
    circuito,
)
from contratacion.infraestructura.config.ajustes import obtener_ajustes

registro = logging.getLogger(__name__)

_JSON = re.compile(r"\{.*\}", re.DOTALL)
# Para qué se llama al modelo: leer el TDR y redactar documentos, o el asistente (chat).
Uso = Literal["documentos", "chat", "avanzado"]
# Tokens que se suman a `max_tokens` cuando el modelo razona antes de responder.
_CUPO_RAZONAMIENTO = 16000
_ILEGIBLE = "La IA no devolvió datos legibles. Vuelve a intentarlo."


class ModeloIa:
    def __init__(
        self,
        *,
        url: str,
        clave: str,
        modelo: str,
        concurrencia: int,
        tiempo_seg: float,
        modelo_documentos: str = "",
        pensar_documentos: bool | None = None,
        pensar_chat: bool | None = None,
        modelo_avanzado: str = "",
        pensar_avanzado: bool | None = None,
    ) -> None:
        self._url = url.rstrip("/")
        self._clave = clave
        # `modelo` es el del asistente (chat); `modelo_documentos`, el de leer el TDR y redactar la
        # proforma. Sin modelo propio para documentos, se usa el mismo.
        self.modelo = modelo
        self.modelo_documentos = modelo_documentos.strip() or modelo
        self._pensar: dict[str, bool | None] = {
            "documentos": pensar_documentos,
            "chat": pensar_chat,
            "avanzado": pensar_avanzado,
        }
        # El modelo que el usuario elige pagando más créditos. Vacío: no se ofrece.
        self.modelo_avanzado = modelo_avanzado.strip()
        self._tiempo = tiempo_seg
        self._concurrencia = concurrencia
        self._turnos = asyncio.Semaphore(concurrencia)
        self._cliente: httpx.AsyncClient | None = None

    @property
    def disponible(self) -> bool:
        return bool(self._url)

    @property
    def avanzado_disponible(self) -> bool:
        return self.disponible and bool(self.modelo_avanzado)

    def modelo_de(self, uso: Uso) -> str:
        if uso == "avanzado" and self.modelo_avanzado:
            return self.modelo_avanzado
        if uso in ("documentos", "avanzado"):
            return self.modelo_documentos
        return self.modelo

    def _http(self) -> httpx.AsyncClient:
        if self._cliente is None:
            cabeceras = {"Content-Type": "application/json"}
            if self._clave:
                cabeceras["Authorization"] = f"Bearer {self._clave}"
            self._cliente = httpx.AsyncClient(
                base_url=self._url,
                headers=cabeceras,
                timeout=httpx.Timeout(self._tiempo, connect=10.0),
                limits=httpx.Limits(max_connections=16, max_keepalive_connections=8),
            )
        return self._cliente

    def _circuito(self) -> Cortacircuitos:
        return circuito(
            "ia",
            mensaje=(
                "El servicio de IA no responde ahora. Inténtalo en unos minutos; mientras tanto "
                "puedes seguir usando el resto del panel."
            ),
            umbral_fallos=4,
            enfriamiento_seg=45.0,
            max_concurrencia=self._concurrencia * 4,
            espera_turno_seg=5.0,
        )

    @property
    def en_servicio(self) -> bool:
        """Configurado y con el circuito sin abrir: se le puede pedir algo ahora mismo.

        Lo usa el asistente para decidir, **antes** de cobrar, si responde con el modelo o por el
        camino sin IA. Con el circuito abierto la llamada fallaría al instante igualmente; saberlo
        antes ahorra el cobro y la devolución.
        """
        return self.disponible and self._circuito().estado is not EstadoCircuito.ABIERTO

    async def completar(
        self,
        sistema: str,
        usuario: str,
        *,
        como_json: bool = False,
        max_tokens: int = 1800,
        uso: Uso = "documentos",
    ) -> str:
        """Una respuesta de texto. `uso` elige modelo y modo «pensar»: documentos o chat."""
        if not self.disponible:
            raise EstadoInvalido("No hay un modelo de IA configurado.")
        async with self._circuito().proteger():
            return await self._completar(
                sistema, usuario, como_json=como_json, max_tokens=max_tokens, uso=uso
            )

    def _modo(self, cuerpo: dict[str, Any], uso: Uso) -> None:
        """Pone en el cuerpo el modelo y el modo «pensar» del uso.

        Con `pensar` sin definir no se envía el parámetro: Groq, Gemini u Ollama no lo conocen. El
        razonamiento gasta del mismo cupo de `max_tokens`: con él, el cupo se amplía, o el modelo
        lo agota pensando y deja la respuesta vacía.
        """
        cuerpo["model"] = self.modelo_de(uso)
        pensar = self._pensar.get(uso)
        if pensar is not None:
            cuerpo["thinking"] = {"type": "enabled" if pensar else "disabled"}
        if pensar:
            cuerpo["max_tokens"] = int(cuerpo.get("max_tokens") or 0) + _CUPO_RAZONAMIENTO

    async def _completar(
        self,
        sistema: str,
        usuario: str,
        *,
        como_json: bool,
        max_tokens: int,
        uso: Uso = "documentos",
    ) -> str:
        cuerpo: dict[str, Any] = {
            "model": self.modelo,
            "temperature": 0.2,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": sistema},
                {"role": "user", "content": usuario},
            ],
        }
        self._modo(cuerpo, uso)
        if como_json:
            cuerpo["response_format"] = {"type": "json_object"}
        # Solo `content`: el razonamiento (`reasoning_content` de DeepSeek en modo «pensar») no se
        # enseña ni se guarda.
        texto = str((await self._pedir(cuerpo)).get("content") or "")
        # Gemini 2.5 y 3 gastan parte del cupo en su razonamiento interno y dejan el texto vacío
        # aunque la petición haya salido bien. Se pide de nuevo con más cupo, una sola vez.
        if not texto.strip() and not como_json and max_tokens < 4000:
            # Por `_completar` y no por `completar`: la llamada ya tiene su turno en el circuito, y
            # pedir otro podría esperar a sí misma con el compartimento lleno.
            return await self._completar(
                sistema,
                usuario,
                como_json=como_json,
                max_tokens=max(max_tokens * 3, 4000),
                uso=uso,
            )
        return texto

    async def conversar(
        self,
        mensajes: list[dict[str, Any]],
        herramientas: list[dict[str, Any]] | None = None,
        *,
        max_tokens: int = 700,
        temperatura: float = 0.1,
    ) -> dict[str, Any]:
        """Un turno de chat con herramientas. Devuelve el mensaje del asistente tal cual.

        El resultado trae `content` (texto o `None`) y `tool_calls` (lista, vacía si el modelo
        respondió directamente). Pasa por el mismo circuito, semáforo y reintentos que `completar`:
        el asistente es un consumidor más del mismo proveedor y no puede saltarse sus topes.
        """
        if not self.disponible:
            raise EstadoInvalido("No hay un modelo de IA configurado.")
        cuerpo: dict[str, Any] = {
            "model": self.modelo,
            "temperature": temperatura,
            "max_tokens": max_tokens,
            "messages": mensajes,
        }
        self._modo(cuerpo, "chat")
        if herramientas:
            cuerpo["tools"] = herramientas
            cuerpo["tool_choice"] = "auto"
        async with self._circuito().proteger():
            mensaje = await self._pedir(cuerpo)
        llamadas = mensaje.get("tool_calls") or []
        salida: dict[str, Any] = {
            "content": mensaje.get("content"),
            "tool_calls": [llamada for llamada in llamadas if isinstance(llamada, dict)],
        }
        # En modo «pensar» con herramientas, DeepSeek exige recibir de vuelta el razonamiento del
        # turno anterior (sin él responde 400). Viaja aparte solo para reenviarlo; no se enseña.
        razonamiento = mensaje.get("reasoning_content")
        if isinstance(razonamiento, str) and razonamiento:
            salida["reasoning_content"] = razonamiento
        return salida

    async def _pedir(self, cuerpo: dict[str, Any]) -> dict[str, Any]:
        """Envía el cuerpo con reintentos y devuelve `choices[0].message`.

        Es la parte común de `completar` y `conversar`: los reintentos ante 429/503, la traducción
        de los errores y la marca de causa que lee el cortacircuitos viven en un solo sitio.
        """
        # 429 y 503 son picos de demanda de Gemini: pasan solos en segundos, así que se reintenta.
        respuesta = None
        for intento in range(3):
            try:
                async with self._turnos:
                    respuesta = await self._http().post("/chat/completions", json=cuerpo)
            except httpx.HTTPError as error:
                registro.warning("El modelo de IA no respondió: %s", type(error).__name__)
                if intento == 2:
                    raise EstadoInvalido(
                        "El servicio de IA no respondió. Vuelve a intentarlo."
                    ) from error
                await asyncio.sleep(2**intento)
                continue
            if respuesta.status_code < 400:
                break
            registro.info("La IA respondió %s (intento %s)", respuesta.status_code, intento + 1)
            await asyncio.sleep(2**intento)
        if respuesta is not None and respuesta.status_code in (429, 503):
            # La causa marca el fallo para el cortacircuitos: es el proveedor el que no da abasto.
            raise EstadoInvalido(
                "El servicio de IA está saturado en este momento. Espera un minuto y vuelve a "
                "intentarlo; tus créditos no se descontaron."
            ) from FalloDelServicio(f"HTTP {respuesta.status_code}")
        if respuesta is None or respuesta.status_code >= 400:
            codigo = respuesta.status_code if respuesta else "sin respuesta"
            registro.warning("El modelo de IA devolvió %s", codigo)
            # Un 5xx es del proveedor y cuenta como fallo; un 4xx es de la configuración (clave,
            # modelo) y no: abrir el circuito por él no arreglaría nada.
            causa = (
                FalloDelServicio(f"HTTP {codigo}")
                if respuesta is None or respuesta.status_code >= 500
                else None
            )
            raise EstadoInvalido(
                "El servicio de IA rechazó la petición. Revisa la configuración."
            ) from causa
        try:
            mensaje = respuesta.json()["choices"][0]["message"]
        except (KeyError, IndexError, ValueError, TypeError) as error:
            raise EstadoInvalido("El servicio de IA devolvió una respuesta vacía.") from error
        if not isinstance(mensaje, dict):
            raise EstadoInvalido("El servicio de IA devolvió una respuesta vacía.")
        return mensaje

    async def completar_json(self, sistema: str, usuario: str, **opciones: Any) -> dict[str, Any]:
        texto = await self.completar(sistema, usuario, como_json=True, **opciones)
        hallado = _JSON.search(texto)
        try:
            valor = json.loads(hallado.group(0) if hallado else texto)
        except ValueError as error:
            raise EstadoInvalido(_ILEGIBLE) from error
        if not isinstance(valor, dict):
            raise EstadoInvalido(_ILEGIBLE)
        return valor

    async def cerrar(self) -> None:
        if self._cliente is not None:
            await self._cliente.aclose()
            self._cliente = None


_MODELO: ModeloIa | None = None


def obtener_modelo() -> ModeloIa:
    global _MODELO
    if _MODELO is None:
        ajustes = obtener_ajustes()
        _MODELO = ModeloIa(
            url=ajustes.ia_url,
            clave=ajustes.ia_clave,
            modelo=ajustes.ia_modelo,
            concurrencia=ajustes.ia_concurrencia,
            tiempo_seg=ajustes.ia_tiempo_seg,
            modelo_documentos=ajustes.ia_modelo_documentos,
            pensar_documentos=ajustes.ia_pensar_documentos,
            pensar_chat=ajustes.ia_pensar_chat,
            modelo_avanzado=ajustes.ia_modelo_avanzado,
            pensar_avanzado=ajustes.ia_pensar_avanzado,
        )
    return _MODELO


async def cerrar_modelo() -> None:
    if _MODELO is not None:
        await _MODELO.cerrar()
