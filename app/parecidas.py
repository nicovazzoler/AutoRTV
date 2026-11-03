"""Después de corregir una celda: las otras filas donde vale el mismo arreglo."""
import re
from dataclasses import asdict, dataclass

from app.pautas import normalizar

MAX = 200


@dataclass
class Parecida:
    clave: str  # hash de la pauta en la base, o el número de fila en la semana
    programa: str
    columna: str
    antes: object
    despues: object
    motivo: str  # mismo_valor | mismo_trozo | mayusculas
    aplica: bool = True
    porque: str = ""

    def json(self) -> dict:
        return asdict(self)


def _texto(v) -> str:
    return "" if v is None else str(v)


def _trozo(antes: str, despues: str) -> tuple[str, str] | None:
    """El pedazo que cambió ("Dr Dolittle" → "Dr. Dolittle": "Dr" → "Dr."), sacando lo que quedó igual en las puntas."""
    i = 0
    while i < min(len(antes), len(despues)) and antes[i] == despues[i]:
        i += 1
    j = 0
    while j < min(len(antes), len(despues)) - i and antes[-1 - j] == despues[-1 - j]:
        j += 1
    # Se extiende a palabras enteras para no reemplazar media palabra en otra fila.
    while i > 0 and antes[i - 1].isalnum():
        i -= 1
    while j > 0 and antes[len(antes) - j].isalnum():
        j -= 1
    viejo, nuevo = antes[i:len(antes) - j], despues[i:len(despues) - j]
    return (viejo, nuevo) if viejo.strip() and viejo != nuevo else None


def _todo_mayusculas(t: str) -> bool:
    letras = [c for c in t if c.isalpha()]
    return len(letras) >= 3 and all(c.isupper() for c in letras)


def _como(antes: str, despues: str):
    """Si el cambio fue solo de mayúsculas desde TODO MAYÚSCULAS, la misma transformación para otro texto."""
    if not _todo_mayusculas(antes) or antes.lower() != despues.lower() or antes == despues:
        return None
    if despues == despues[:1].upper() + despues[1:].lower():
        return lambda t: t[:1].upper() + t[1:].lower()
    if despues == despues.title():
        return str.title
    return None


def buscar(filas: list[tuple[str, dict]], columna: str, antes, despues, programa: str | None,
           excluir: str) -> list[Parecida]:
    """`filas` son (clave, salida) de la base o de la semana; `excluir`, la clave de la fila que se corrigió."""
    a, d = _texto(antes), _texto(despues)
    trozo = _trozo(a, d) if a and d else None
    transformar = _como(a, d)
    encontradas = []
    for clave, salida in filas:
        if clave == excluir or columna not in salida:
            continue
        actual = _texto(salida.get(columna))
        nombre = _texto(salida.get(programa)) if programa else ""
        if a and normalizar(actual) == normalizar(a) and actual != d:
            encontradas.append(Parecida(clave, nombre, columna, salida.get(columna), despues, "mismo_valor"))
        elif transformar and _todo_mayusculas(actual):
            encontradas.append(Parecida(clave, nombre, columna, actual, transformar(actual), "mayusculas"))
        elif trozo and re.search(rf"(?<!\w){re.escape(trozo[0])}(?!\w)", actual) and trozo[1] not in actual:
            nuevo = re.sub(rf"(?<!\w){re.escape(trozo[0])}(?!\w)", trozo[1].replace("\\", "\\\\"), actual)
            encontradas.append(Parecida(clave, nombre, columna, actual, nuevo, "mismo_trozo"))
        if len(encontradas) >= MAX:
            break
    return encontradas
