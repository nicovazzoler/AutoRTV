"""Lista de programas que una señal ya emitió, sacada de EPG terminados."""
from collections import Counter

import pandas as pd

NOMBRES_PROGRAMA = ["TIT ING", "Programa", "PROGRAMA", "Program Title", "Titulo", "Título", "Title"]


def detectar_columna(columnas: list[str]) -> str | None:
    return next((c for c in NOMBRES_PROGRAMA if c in columnas), None)


def aprender(tablas: list[pd.DataFrame], columna: str | None = None) -> tuple[Counter, str | None]:
    """Cuenta cuántas veces aparece cada título. Devuelve (conteo, columna usada)."""
    conteo: Counter = Counter()
    usada = columna
    for tabla in tablas:
        col = columna or detectar_columna([str(c) for c in tabla.columns])
        if not col or col not in tabla.columns:
            continue
        usada = usada or col
        for v in tabla[col]:
            titulo = _limpio(v)
            if titulo:
                conteo[titulo] += 1
    return conteo, usada


def _limpio(v) -> str | None:
    if not isinstance(v, str):
        return None  # vacíos y números (una columna mal elegida) no son títulos
    s = " ".join(v.split())
    if not s or s.replace(".", "").replace(",", "").isdigit():
        return None
    return s
