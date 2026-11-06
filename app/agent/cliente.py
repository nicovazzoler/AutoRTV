"""Llamada a Claude. El resto del agente habla con un `Proveedor`, así los tests no gastan."""
import json
import os
from dataclasses import dataclass, field
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
    },
    "required": ["explicacion", "tarjetas_json", "columnas_salida", "correcciones_base_json"],
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
    bloques: list = field(default_factory=list)  # con herramientas: el contenido tal cual, para reenviarlo
    parar: str = ""  # stop_reason: "tool_use" si pidió herramientas


class ErrorAgente(Exception):
    """La API de Anthropic falló. El mensaje ya está en castellano, para mostrarlo tal cual."""


class Proveedor(Protocol):
    def pedir(self, sistema: str, mensajes: list[dict], effort: str, fuerte: bool = False) -> Respuesta: ...

    def pedir_json(self, sistema: str, mensajes: list[dict], formato: dict, modelo: str, effort: str) -> Respuesta: ...

    def con_herramientas(self, sistema: str, mensajes: list[dict], herramientas: list[dict], modelo: str | None = None,
                         effort: str = "low", max_tokens: int = 4000) -> Respuesta: ...


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

    def pedir_json(self, sistema: str, mensajes: list[dict], formato: dict, modelo: str, effort: str) -> Respuesta:
        """Un pedido con su propio formato de respuesta y el modelo elegido por quien llama."""
        import anthropic

        respaldo = {} if "haiku" in modelo else {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        try:
            r = self._cliente.beta.messages.create(
                model=modelo, max_tokens=16000,
                system=[{"type": "text", "text": sistema, "cache_control": {"type": "ephemeral"}}],
                messages=mensajes,
                output_config={"effort": effort, "format": {"type": "json_schema", "schema": formato}},
                **respaldo,
            )
        except anthropic.APIError as e:
            raise ErrorAgente(explicar(e, modelo)) from e
        return _leer(r)

    def con_herramientas(self, sistema: str, mensajes: list[dict], herramientas: list[dict], modelo: str | None = None,
                         effort: str = "low", max_tokens: int = 4000) -> Respuesta:
        """Un paso de un bucle con herramientas: el modelo contesta o pide herramientas (`parar` = "tool_use")."""
        import anthropic

        modelo = modelo or MODELO_RAPIDO
        respaldo = {} if "haiku" in modelo else {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        crear = self._cliente.beta.messages.create if respaldo else self._cliente.messages.create
        try:
            r = crear(
                model=modelo, max_tokens=max_tokens,
                system=[{"type": "text", "text": sistema, "cache_control": {"type": "ephemeral"}}],
                tools=herramientas, messages=_con_cache(mensajes), output_config={"effort": effort}, **respaldo,
            )
        except anthropic.APIError as e:
            raise ErrorAgente(explicar(e, modelo)) from e
        uso = (r.usage.input_tokens + (r.usage.cache_read_input_tokens or 0)
               + (r.usage.cache_creation_input_tokens or 0), r.usage.output_tokens)
        if r.stop_reason == "refusal":
            motivo = getattr(r.stop_details, "explanation", None) or "sin detalle"
            return Respuesta("", rechazo=motivo, tokens_entrada=uso[0], tokens_salida=uso[1], modelo=r.model)
        texto = "".join(b.text for b in r.content if b.type == "text")
        # El bloque `fallback` (otro modelo siguió por un rechazo) es una marca para auditar: no se reenvía.
        return Respuesta(texto, tokens_entrada=uso[0], tokens_salida=uso[1], modelo=r.model,
                         bloques=[_bloque(b) for b in r.content if b.type != "fallback"], parar=r.stop_reason or "")


def _con_cache(mensajes: list[dict]) -> list[dict]:
    """Marca el último bloque para el caché: el paso siguiente de la charla reusa todo lo anterior."""
    if not mensajes:
        return mensajes
    ultimo = dict(mensajes[-1])
    contenido = ultimo["content"]
    bloques = [{"type": "text", "text": contenido}] if isinstance(contenido, str) else [dict(b) for b in contenido]
    bloques[-1]["cache_control"] = {"type": "ephemeral"}
    ultimo["content"] = bloques
    return [*mensajes[:-1], ultimo]


def _bloque(b) -> dict:
    return b.model_dump(exclude_none=True) if hasattr(b, "model_dump") else dict(b)


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

    # El agente de la señal necesita un guion propio de herramientas: con las respuestas de la charla no corre.
    con_agente_de_la_senal = False

    def __init__(self, respuestas: list[dict]):
        # Las que tienen "respuesta" son de la charla; las de "entrada_json", de la lectura; el resto, propuestas.
        self.charlas = [r for r in respuestas if _clave_de(r) == "charla"]
        self.lecturas = [r for r in respuestas if _clave_de(r) == "lectura"]
        self.respuestas = [r for r in respuestas if _clave_de(r) == "otra"]
        self.pedidos: list[list[dict]] = []
        self.fuertes: list[bool] = []
        self.modelos: list[str] = []
        self._texto_pendiente = ""

    def pedir(self, sistema: str, mensajes: list[dict], effort: str, fuerte: bool = False) -> Respuesta:
        self.fuertes.append(fuerte)
        return self._siguiente(self.respuestas, mensajes)

    def pedir_json(self, sistema: str, mensajes: list[dict], formato: dict, modelo: str, effort: str) -> Respuesta:
        self.modelos.append(modelo)
        if "entrada_json" in formato.get("properties", {}):
            if not self.lecturas:  # sin lectura grabada, el agente deja la del código
                return self._siguiente([{"explicacion": "", "entrada_json": "", "aceptar": True}], mensajes)
            return self._siguiente(self.lecturas, mensajes)
        return self._siguiente(self.respuestas, mensajes)

    def charlar(self, sistema: str, mensajes: list[dict]) -> Respuesta:
        if not self.charlas:  # sin charla grabada, todo pasa a propuesta
            return Respuesta("", {"respuesta": "", "proponer_cambios": True})
        return self._siguiente(self.charlas, mensajes)

    def con_herramientas(self, sistema: str, mensajes: list[dict], herramientas: list[dict], modelo: str | None = None,
                         effort: str = "low", max_tokens: int = 4000) -> Respuesta:
        """Una charla grabada como las de antes ({respuesta, acciones, proponer_cambios}) se pasa a herramientas:
        primero pide las que correspondan y, con sus resultados, contesta el texto."""
        ultimo = mensajes[-1]["content"]
        if isinstance(ultimo, list) and any(b.get("type") == "tool_result" for b in ultimo):
            self.pedidos.append([dict(m_) for m_ in mensajes])
            return Respuesta(self._texto_pendiente, bloques=[{"type": "text", "text": self._texto_pendiente}], parar="end_turn")
        r = self.charlar(sistema, mensajes)
        datos = r.datos if isinstance(r.datos, dict) else {}
        if "herramientas" in datos:  # grabada ya con herramientas: [{"nombre", "datos"}]
            usos = [(h["nombre"], h.get("datos", {})) for h in datos["herramientas"]]
        else:
            usos = [(a.get("tipo", ""), {k: v for k, v in a.items() if k in ("pantalla", "senal", "nombre") and v})
                    for a in datos.get("acciones") or []]
            if datos.get("proponer_cambios", not datos):
                usos.append(("proponer_reglas", {"pedido": ""}))
        self._texto_pendiente = str(datos.get("respuesta", ""))
        if not usos:
            return Respuesta(self._texto_pendiente, bloques=[{"type": "text", "text": self._texto_pendiente}], parar="end_turn")
        bloques = [{"type": "tool_use", "id": f"t{i}", "name": n, "input": d} for i, (n, d) in enumerate(usos)]
        return Respuesta("", bloques=bloques, parar="tool_use")

    def _siguiente(self, cola: list, mensajes: list[dict]) -> Respuesta:
        self.pedidos.append([dict(m_) for m_ in mensajes])
        datos = cola.pop(0) if len(cola) > 1 else cola[0]
        if isinstance(datos, str):  # simula una respuesta que no es JSON
            return Respuesta(datos)
        return Respuesta(json.dumps(datos, ensure_ascii=False), datos)


def _clave_de(r) -> str:
    if isinstance(r, dict) and "respuesta" in r:
        return "charla"
    if isinstance(r, dict) and ({"entrada_json", "ver_hoja", "aceptar"} & r.keys()):
        return "lectura"
    return "otra"


_grabados: dict[str, Grabado] = {}


def proveedor_configurado() -> Proveedor | None:
    if falso := os.environ.get("AGENTE_FALSO"):  # archivo JSON con respuestas, solo para tests e2e
        # Uno solo por archivo: las respuestas avanzan entre pedidos, como una charla de verdad.
        if falso not in _grabados:
            _grabados[falso] = Grabado(json.loads(Path(falso).read_text(encoding="utf-8")))
        return _grabados[falso]
    if os.environ.get("ANTHROPIC_API_KEY"):
        return Claude()
    return None
