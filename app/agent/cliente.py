"""Llamada a Claude. El resto del agente habla con un `Proveedor`, así los tests no gastan."""
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

MODELO = os.environ.get("AGENTE_MODELO", "claude-opus-5-5")

# Las tarjetas viajan como texto JSON y las valida Pydantic: el schema de tarjetas usa uniones y
# mapas que el modo estructurado puede no aceptar, y así el error se le devuelve tal cual.
FORMATO = {
    "type": "object",
    "properties": {
        "explicacion": {"type": "string"},
        "tarjetas_json": {"type": "string"},
        "columnas_salida": {"anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "null"}]},
    },
    "required": ["explicacion", "tarjetas_json", "columnas_salida"],
    "additionalProperties": False,
}


@dataclass
class Respuesta:
    texto: str  # lo que devolvió el modelo, para reenviarlo en la vuelta siguiente
    datos: dict | None = None
    rechazo: str | None = None  # motivo si el modelo se negó a responder
    tokens_entrada: int = 0
    tokens_salida: int = 0


class Proveedor(Protocol):
    def pedir(self, sistema: str, mensajes: list[dict], effort: str) -> Respuesta: ...


class Claude:
    def __init__(self):
        import anthropic  # solo hace falta si el asistente está configurado
        self._cliente = anthropic.Anthropic()

    def pedir(self, sistema: str, mensajes: list[dict], effort: str) -> Respuesta:
        r = self._cliente.beta.messages.create(
            model=MODELO,
            max_tokens=16000,
            # El system prompt no cambia entre pedidos: se cachea y cada llamada sale más barata.
            system=[{"type": "text", "text": sistema, "cache_control": {"type": "ephemeral"}}],
            messages=mensajes,
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": FORMATO}},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        uso = (r.usage.input_tokens + (r.usage.cache_read_input_tokens or 0)
               + (r.usage.cache_creation_input_tokens or 0), r.usage.output_tokens)
        if r.stop_reason == "refusal":
            motivo = getattr(r.stop_details, "explanation", None) or "sin detalle"
            return Respuesta("", rechazo=motivo, tokens_entrada=uso[0], tokens_salida=uso[1])
        texto = next((b.text for b in r.content if b.type == "text"), "")
        try:
            datos = json.loads(texto)
        except json.JSONDecodeError:
            datos = None  # se corta por max_tokens; el bucle lo reintenta
        return Respuesta(texto, datos, tokens_entrada=uso[0], tokens_salida=uso[1])


class Grabado:
    """Devuelve respuestas fijas en orden. Para tests y para probar la web sin key."""

    def __init__(self, respuestas: list[dict]):
        self.respuestas = list(respuestas)
        self.pedidos: list[list[dict]] = []

    def pedir(self, sistema: str, mensajes: list[dict], effort: str) -> Respuesta:
        self.pedidos.append([dict(m_) for m_ in mensajes])
        datos = self.respuestas.pop(0) if len(self.respuestas) > 1 else self.respuestas[0]
        if isinstance(datos, str):  # simula una respuesta que no es JSON
            return Respuesta(datos)
        return Respuesta(json.dumps(datos, ensure_ascii=False), datos)


def proveedor_configurado() -> Proveedor | None:
    if falso := os.environ.get("AGENTE_FALSO"):  # archivo JSON con respuestas, solo para tests e2e
        return Grabado(json.loads(Path(falso).read_text(encoding="utf-8")))
    if os.environ.get("ANTHROPIC_API_KEY"):
        return Claude()
    return None
