"""Armar las reglas de una señal desde sus ejemplos: primero Haiku y, si no alcanza, Sonnet arrancando de lo de Haiku.

Solo devuelve la receta si mejora el % del ejemplo; aplicarla es cosa de quien llama.
"""
from dataclasses import dataclass, field

from app.agent import asistente
from app.engine import model as m

PEDIDO = "Ajustá las tarjetas para que la grilla de entrada de este ejemplo quede igual al EPG esperado."
# Por debajo de esto, lo de Haiku pasa a Sonnet (la escalera del banco de agentes).
UMBRAL = 90.0


@dataclass
class Armado:
    receta: m.Senal | None  # None = ninguna propuesta mejoró el ejemplo
    antes: float
    despues: float
    modelos: list[str] = field(default_factory=list)
    problemas: list[str] = field(default_factory=list)
    pedidos: list[asistente.Propuesta] = field(default_factory=list)  # para registrar el uso de cada uno


def _porcentaje(metricas: asistente.Metricas | None, objetivo: str) -> float:
    return metricas.ejemplos.get(objetivo, 0.0) if metricas else 0.0


def armar(receta: m.Senal, ejemplos: list[asistente.Ejemplo], objetivo: str, proveedor,
          orden_columnas: list[str] = (), entorno: asistente.Entorno | None = None) -> Armado:
    ejemplo = next(e for e in ejemplos if e.nombre == objetivo)
    pedir = lambda base, fuerte: asistente.pedir(  # noqa: E731
        base, ejemplo.entrada, PEDIDO, proveedor, ejemplos, objetivo=objetivo, orden_columnas=orden_columnas,
        entorno=entorno, fuerte=fuerte)
    haiku = pedir(receta, False)
    resultado = Armado(None, _porcentaje(haiku.antes, objetivo), _porcentaje(haiku.antes, objetivo),
                       pedidos=[haiku])
    candidatas = [(haiku, haiku.modelo)]
    if _porcentaje(haiku.despues, objetivo) < UMBRAL:
        base = m.Senal(**haiku.receta) if haiku.receta else receta
        sonnet = pedir(base, True)
        resultado.pedidos.append(sonnet)
        candidatas.append((sonnet, sonnet.modelo))
    for p, modelo in candidatas:
        resultado.modelos.append(modelo)
        despues = _porcentaje(p.despues, objetivo)
        if p.receta and despues > resultado.despues:
            resultado.receta, resultado.despues = m.Senal(**p.receta), despues
    resultado.problemas = candidatas[-1][0].problemas[:3]
    return resultado
