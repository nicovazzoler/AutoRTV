"""Chequeos de una grilla ya armada: horarios, cobertura de 24 h y campos vacíos."""
import datetime as dt
from collections import defaultdict
from dataclasses import dataclass

import pandas as pd

from app.engine import model as m
from app.engine.tarjetas.estructura import a_fecha, a_hora

MAX_POR_REGLA = 200

# Nombres con los que se detectan las columnas si la señal no las indica.
NOMBRES = {
    "fecha": ["FECHA", "Fecha", "FechaEPG", "Date"],
    "hora": ["HORA", "Hora", "HoraEPG", "Time"],
    "duracion": ["DUR", "Duracion", "Duración", "DURACION", "Duration"],
}


@dataclass
class Aviso:
    nivel: str  # error | aviso | info
    regla: str
    mensaje: str
    fila: int | None = None  # 1 = primera fila de datos


def detectar_columnas(columnas: list[str], v: m.Validaciones) -> dict[str, str | None]:
    elegidas = {}
    for clave, candidatos in NOMBRES.items():
        propia = getattr(v, clave)
        elegidas[clave] = propia if propia else next((c for c in candidatos if c in columnas), None)
    return elegidas


def validar(salida: pd.DataFrame, v: m.Validaciones) -> list[Aviso]:
    avisos: list[Aviso] = []
    if v.filas_esperadas is not None and len(salida) != v.filas_esperadas:
        avisos.append(Aviso("aviso", "filas", f"Hay {len(salida)} filas y se esperaban {v.filas_esperadas}"))
    avisos += _obligatorias(salida, v.obligatorias)

    cols = detectar_columnas(list(salida.columns), v)
    faltan = [k for k, c in cols.items() if not c or c not in salida.columns]
    if faltan:
        avisos.append(Aviso("aviso", "config",
                            f"No se validan horarios: falta la columna de {', '.join(faltan)}. "
                            "Elegila en la sección Validaciones."))
        return _topear(avisos)
    avisos += _horarios(salida, cols, v)
    return _topear(avisos)


def _obligatorias(df: pd.DataFrame, columnas: list[str]) -> list[Aviso]:
    avisos = []
    for col in columnas:
        if col not in df.columns:
            avisos.append(Aviso("aviso", "obligatorias", f"La columna obligatoria {col} no está en la salida"))
            continue
        vacias = [i + 1 for i, x in enumerate(df[col]) if x is None or (isinstance(x, float) and pd.isna(x))
                  or (isinstance(x, str) and not x.strip())]
        for fila in vacias:
            avisos.append(Aviso("aviso", "obligatorias", f"{col} vacía", fila))
    return avisos


def _horarios(df: pd.DataFrame, cols: dict[str, str], v: m.Validaciones) -> list[Aviso]:
    avisos = []
    programas = []  # (fila, inicio, fin) de las filas legibles
    for i, (f, h, d) in enumerate(zip(df[cols["fecha"]], df[cols["hora"]], df[cols["duracion"]])):
        fila = i + 1
        fecha, hora, minutos = a_fecha(f), a_hora(h), _minutos(d)
        if fecha is None or hora is None or minutos is None:
            avisos.append(Aviso("error", "ilegible", "Fecha, hora o duración vacía o ilegible", fila))
            continue
        if minutos <= 0:
            avisos.append(Aviso("error", "duracion", f"Duración de {minutos} min", fila))
            continue
        if v.max_duracion_min and minutos > v.max_duracion_min:
            avisos.append(Aviso("error", "duracion_larga",
                                f"Duración de {minutos} min (máximo {v.max_duracion_min}): ¿falta una fila?", fila))
        inicio = dt.datetime.combine(fecha, hora)
        programas.append((fila, inicio, inicio + dt.timedelta(minutes=minutos)))

    tol = dt.timedelta(minutes=v.tolerancia_min)
    for (_, ini_a, fin_a), (fila_b, ini_b, _) in zip(programas, programas[1:]):
        if ini_b < ini_a:
            avisos.append(Aviso("error", "orden", "Empieza antes que la fila anterior: grilla desordenada", fila_b))
        elif v.superposiciones and fin_a > ini_b + tol:
            avisos.append(Aviso("error", "superposicion",
                                f"Se pisa {_min(fin_a - ini_b)} min con el programa anterior", fila_b))
        elif v.huecos and fin_a < ini_b - tol:
            avisos.append(Aviso("aviso", "hueco", f"Hueco de {_min(ini_b - fin_a)} min antes de este programa", fila_b))

    if v.dia_minutos and programas:
        avisos += _cobertura_diaria(programas, v.dia_minutos)
    return avisos


def _cobertura_diaria(programas, dia_minutos: int) -> list[Aviso]:
    """Minutos de programación por día, partiendo en la medianoche los programas que la cruzan."""
    por_dia: dict[dt.date, int] = defaultdict(int)
    primera_fila: dict[dt.date, int] = {}
    for fila, inicio, fin in programas:
        t = inicio
        while t < fin:
            corte = min(fin, dt.datetime.combine(t.date() + dt.timedelta(days=1), dt.time(0)))
            por_dia[t.date()] += _min(corte - t)
            primera_fila.setdefault(t.date(), fila)
            t = corte
    dias = sorted(por_dia)
    avisos = []
    for dia in dias:
        total = por_dia[dia]
        if total == dia_minutos:
            continue
        fecha = dia.strftime("%d/%m/%Y")
        if dia in (dias[0], dias[-1]) and total < dia_minutos:
            donde = "arranca" if dia == dias[0] else "termina"
            avisos.append(Aviso("info", "dia_parcial", f"{fecha}: {total} min (día parcial, acá {donde} la grilla)",
                                primera_fila[dia]))
        else:
            avisos.append(Aviso("error", "dia_minutos", f"{fecha} suma {total} min, no {dia_minutos}", primera_fila[dia]))
    return avisos


def _minutos(v) -> int | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return None if pd.isna(v) else int(v)
    try:
        return int(float(str(v).strip()))
    except ValueError:
        return None


def _min(delta: dt.timedelta) -> int:
    return int(delta.total_seconds() // 60)


def _topear(avisos: list[Aviso]) -> list[Aviso]:
    """Deja hasta MAX_POR_REGLA avisos por regla y suma uno que dice cuántos se omitieron."""
    cuenta: dict[str, int] = defaultdict(int)
    salida = []
    for a in avisos:
        cuenta[a.regla] += 1
        if cuenta[a.regla] <= MAX_POR_REGLA:
            salida.append(a)
    for regla, n in cuenta.items():
        if n > MAX_POR_REGLA:
            salida.append(Aviso("info", regla, f"Hay {n - MAX_POR_REGLA} avisos más de este tipo que no se muestran"))
    return salida


def resumen(avisos: list[Aviso]) -> dict[str, int]:
    return {n: sum(a.nivel == n for a in avisos) for n in ("error", "aviso", "info")}
