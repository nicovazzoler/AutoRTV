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


def diferencias(salida: pd.DataFrame, esperado: pd.DataFrame, pares: list[tuple[int, int]] | None = None) -> list[dict]:
    """Celdas distintas. Sin `pares`, fila por fila; con `pares` (fila del ejemplo, fila de la salida), solo esas."""
    if pares is None:
        pares = [(i, i) for i in range(max(len(salida), len(esperado)))]
    difs = []
    for col in esperado.columns:
        for i, j in pares:
            a = normalizar(salida[col].iloc[j]) if col in salida.columns and j < len(salida) else None
            b = normalizar(esperado[col].iloc[i]) if i < len(esperado) else None
            if a != b:
                difs.append({"fila": i, "columna": col, "obtenido": a, "esperado": b})
    return difs


def porcentaje_igual(salida: pd.DataFrame, esperado: pd.DataFrame, pares: list[tuple[int, int]] | None = None) -> float:
    filas = max(len(salida), len(esperado)) if pares is None else len(pares)
    total = filas * len(esperado.columns)
    return 100 * (1 - len(diferencias(salida, esperado, pares)) / total) if total else 100.0


def sugerir_correcciones(salida: pd.DataFrame, esperado: pd.DataFrame, columnas: list[str],
                         pares: list[tuple[int, int]] | None = None) -> dict[str, dict[str, str]]:
    """Por columna, {texto obtenido: texto esperado} de las celdas de texto que difieren.

    Si un mismo texto se corrigió de dos formas distintas no se sugiere: no es una corrección fija.
    """
    sugerencias: dict[str, dict[str, str]] = {}
    conflictos: set[tuple[str, str]] = set()
    for d in diferencias(salida, esperado, pares):
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
