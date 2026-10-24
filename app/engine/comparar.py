"""Compara una salida contra un EPG esperado, celda por celda."""
import datetime as dt

import pandas as pd


def normalizar(v):
    if v is None or (isinstance(v, float) and pd.isna(v)) or v is pd.NaT:
        return None
    if isinstance(v, pd.Timestamp):
        v = v.to_pydatetime()
    if isinstance(v, dt.datetime) and v.time() == dt.time(0):
        return v.date()
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


def diferencias(salida: pd.DataFrame, esperado: pd.DataFrame) -> list[dict]:
    difs = []
    for col in esperado.columns:
        for i in range(max(len(salida), len(esperado))):
            a = normalizar(salida[col].iloc[i]) if col in salida.columns and i < len(salida) else None
            b = normalizar(esperado[col].iloc[i]) if i < len(esperado) else None
            if a != b:
                difs.append({"fila": i, "columna": col, "obtenido": a, "esperado": b})
    return difs


def porcentaje_igual(salida: pd.DataFrame, esperado: pd.DataFrame) -> float:
    total = max(len(salida), len(esperado)) * len(esperado.columns)
    return 100 * (1 - len(diferencias(salida, esperado)) / total) if total else 100.0


def sugerir_correcciones(salida: pd.DataFrame, esperado: pd.DataFrame, columnas: list[str]) -> dict[str, dict[str, str]]:
    """Por columna, {texto obtenido: texto esperado} de las celdas de texto que difieren.

    Si un mismo texto se corrigió de dos formas distintas no se sugiere: no es una corrección fija.
    """
    sugerencias: dict[str, dict[str, str]] = {}
    conflictos: set[tuple[str, str]] = set()
    for d in diferencias(salida, esperado):
        a, b = d["obtenido"], d["esperado"]
        if d["columna"] not in columnas or not isinstance(a, str) or not isinstance(b, str):
            continue
        mapa = sugerencias.setdefault(d["columna"], {})
        if mapa.get(a, b) != b:
            conflictos.add((d["columna"], a))
        mapa[a] = b
    for col, a in conflictos:
        del sugerencias[col][a]
    return {col: mapa for col, mapa in sugerencias.items() if mapa}
