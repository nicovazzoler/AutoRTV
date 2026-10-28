"""Llamada a Claude. El resto del agente habla con un `Proveedor`, así los tests no gastan."""
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

# Las propuestas van al modelo barato: el servidor prueba cada una y le devuelve lo que falló.
MODELO = os.environ.get("AGENTE_MODELO", "claude-haiku-5-5")
# Solo si la persona lo pide, para lo que el barato no resuelve.
MODELO_FUERTE = os.environ.get("AGENTE_MODELO_FUERTE", "claude-sonnet-5-5")
# Modelo rápido y barato para charlar y decidir si hace falta armar una propuesta.
MODELO_RAPIDO = os.environ.get("AGENTE_MODELO_RAPIDO", "claude-haiku-5-5")

# Las tarjetas viajan como texto JSON y las valida Pydantic: el schema de tarjetas usa uniones y
# mapas que el modo estructurado puede no aceptar, y así el error se le devuelve tal cual.
FORMATO = {
    "type": "object",
    "properties": {
        "explicacion": {"type": "string"},
        "tarjetas_json": {"type": "string"},
        "columnas_salida": {"anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "null"}]},
        "correcciones_base_json": {"type": "string"},
        "acciones_admin_json": {"type": "string"},
    },
    "required": ["explicacion", "tarjetas_json", "columnas_salida", "correcciones_base_json", "acciones_admin_json"],
    "additionalProperties": False,
}

FORMATO_CHARLA = {
    "type": "object",
    "properties": {"respuesta": {"type": "string"}, "proponer_cambios": {"type": "boolean"}},
    "required": ["respuesta", "proponer_cambios"],
    "additionalProperties": False,
}


@dataclass
class Respuesta:
    texto: str  # lo que devolvió el modelo, para reenviarlo en la vuelta siguiente
    datos: dict | None = None
    rechazo: str | None = None
    tokens_entrada: int = 0
    tokens_salida: int = 0
    modelo: str = ""  # el que respondió de verdad, para calcular el costo
    aviso: str = ""


class ErrorAgente(Exception):
    """La API de Anthropic falló. El mensaje ya está en castellano, para mostrarlo tal cual."""


class Proveedor(Protocol):
    def pedir(self, sistema: str, mensajes: list[dict], effort: str, fuerte: bool = False) -> Respuesta: ...

    def charlar(self, sistema: str, mensajes: list[dict]) -> Respuesta: ...


class Claude:
    def __init__(self):
        import anthropic  # solo hace falta si el asistente está configurado
        self._cliente = anthropic.Anthropic()

    def pedir(self, sistema: str, mensajes: list[dict], effort: str, fuerte: bool = False) -> Respuesta:
        import anthropic

        try:
            return self._pedir(MODELO_FUERTE if fuerte else MODELO, sistema, mensajes, effort)
        except anthropic.APIStatusError as e:
            if not (fuerte and _es_de_modelo(e)):
                raise ErrorAgente(explicar(e, MODELO_FUERTE if fuerte else MODELO)) from e
            r = self.pedir(sistema, mensajes, effort)
            r.aviso = f"Se usó el modelo barato porque {MODELO_FUERTE} no está disponible para esta key."
            return r
        except anthropic.APIError as e:
            raise ErrorAgente(explicar(e, MODELO_FUERTE if fuerte else MODELO)) from e

    def _pedir(self, modelo: str, sistema: str, mensajes: list[dict], effort: str) -> Respuesta:
        # Haiku no tiene fallback del lado del servidor: un rechazo vuelve como tal.
        respaldo = {} if "haiku" in modelo else {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        r = self._cliente.beta.messages.create(
            model=modelo,
            max_tokens=16000,
            # El system prompt no cambia entre pedidos: se cachea y cada llamada sale más barata.
            system=[{"type": "text", "text": sistema, "cache_control": {"type": "ephemeral"}}],
            messages=mensajes,
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": FORMATO}},
            **respaldo,
        )
        return _leer(r)

    def charlar(self, sistema: str, mensajes: list[dict]) -> Respuesta:
        import anthropic

        try:
            r = self._cliente.messages.create(
                model=MODELO_RAPIDO,
                max_tokens=4000,
                system=sistema,
                messages=mensajes,
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": FORMATO_CHARLA}},
            )
        except anthropic.APIError as e:
            raise ErrorAgente(explicar(e, MODELO_RAPIDO)) from e
        return _leer(r)


def _es_de_modelo(e) -> bool:
    return e.status_code == 404 or (e.status_code == 400 and "model" in str(e).lower())


def explicar(e, modelo: str) -> str:
    """Un error de la API de Anthropic contado para quien usa la web."""
    import anthropic

    if isinstance(e, anthropic.APITimeoutError):
        return "El agente tardó demasiado en responder. Probá de nuevo."
    if not isinstance(e, anthropic.APIStatusError):
        return "No se pudo conectar con Anthropic. Probá de nuevo en un rato."
    texto = str(e).lower()
    if e.status_code == 401:
        return "La API key de Anthropic no es válida: revisá ANTHROPIC_API_KEY en Railway."
    if e.status_code in (402, 403) or "credit" in texto or "billing" in texto or "spend" in texto:
        return "La key de Anthropic se quedó sin crédito o llegó al tope de gasto: revisalo en la Console de Anthropic."
    if _es_de_modelo(e):
        return f"El modelo {modelo} no está disponible para esta key."
    if e.status_code == 429:
        return "Se llegó al límite de pedidos por minuto de la key. Probá en unos minutos."
    if e.status_code >= 500:
        return "Anthropic está saturado o con problemas. Probá en unos minutos."
    return f"Anthropic rechazó el pedido ({e.status_code}): {e.message}"


def _leer(r) -> Respuesta:
    uso = (r.usage.input_tokens + (r.usage.cache_read_input_tokens or 0)
           + (r.usage.cache_creation_input_tokens or 0), r.usage.output_tokens)
    if r.stop_reason == "refusal":
        motivo = getattr(r.stop_details, "explanation", None) or "sin detalle"
        return Respuesta("", rechazo=motivo, tokens_entrada=uso[0], tokens_salida=uso[1], modelo=r.model)
    texto = next((b.text for b in r.content if b.type == "text"), "")
    try:
        datos = json.loads(texto)
    except json.JSONDecodeError:
        datos = None  # se corta por max_tokens; el bucle lo reintenta
    return Respuesta(texto, datos, tokens_entrada=uso[0], tokens_salida=uso[1], modelo=r.model)


class Grabado:
    """Devuelve respuestas fijas en orden. Para tests y para probar la web sin key."""

    def __init__(self, respuestas: list[dict]):
        # Las que tienen "respuesta" son de la charla; el resto, propuestas de tarjetas.
        self.charlas = [r for r in respuestas if isinstance(r, dict) and "respuesta" in r]
        self.respuestas = [r for r in respuestas if not (isinstance(r, dict) and "respuesta" in r)]
        self.pedidos: list[list[dict]] = []
        self.fuertes: list[bool] = []

    def pedir(self, sistema: str, mensajes: list[dict], effort: str, fuerte: bool = False) -> Respuesta:
        self.fuertes.append(fuerte)
        return self._siguiente(self.respuestas, mensajes)

    def charlar(self, sistema: str, mensajes: list[dict]) -> Respuesta:
        if not self.charlas:  # sin charla grabada, todo pasa a propuesta
            return Respuesta("", {"respuesta": "", "proponer_cambios": True})
        return self._siguiente(self.charlas, mensajes)

    def _siguiente(self, cola: list, mensajes: list[dict]) -> Respuesta:
        self.pedidos.append([dict(m_) for m_ in mensajes])
        datos = cola.pop(0) if len(cola) > 1 else cola[0]
        if isinstance(datos, str):  # simula una respuesta que no es JSON
            return Respuesta(datos)
        return Respuesta(json.dumps(datos, ensure_ascii=False), datos)


def proveedor_configurado() -> Proveedor | None:
    if falso := os.environ.get("AGENTE_FALSO"):  # archivo JSON con respuestas, solo para tests e2e
        return Grabado(json.loads(Path(falso).read_text(encoding="utf-8")))
    if os.environ.get("ANTHROPIC_API_KEY"):
        return Claude()
    return None
