"""Controles que dicen, sin mirar a ojo, si lo que armó un agente está bien: números, no opiniones."""
import datetime as dt
import re

import pandas as pd

from app.engine.tarjetas.estructura import a_fecha, a_hora

# Por debajo de esto la lectura se da por mala y se le pide otra al agente (o al modelo más capaz).
UMBRAL_HORARIO = 0.95
UMBRAL_EMPAREJA = 0.80
# Al comparar con el ejemplo: la zona horaria y el redondeo de horas son cosa de las reglas, no de la lectura.
CORRIMIENTOS_HORAS = range(-14, 15)
TOLERANCIA_MIN = 2
MOMENTO_TEXTO = re.compile(r"(\d{4}-\d{2}-\d{2})[T ](\d{1,2}:\d{2})")


def _partes(v) -> tuple[dt.date | None, str | None]:
    """(fecha, "HH:MM") que trae una celda: las dos, una sola o ninguna."""
    if isinstance(v, (dt.datetime, pd.Timestamp)):
        return v.date(), v.strftime("%H:%M")
    if isinstance(v, dt.date):
        return v, None
    if isinstance(v, dt.time):
        return None, v.strftime("%H:%M")
    if isinstance(v, str) and (m := MOMENTO_TEXTO.search(v)):
        return dt.date.fromisoformat(m[1]), f"{int(m[2].split(':')[0]):02d}:{m[2].split(':')[1]}"
    hora = a_hora(v) if isinstance(v, str) else None
    if hora:
        return None, hora.strftime("%H:%M")
    return a_fecha(v), None


def _candidatas(tabla: pd.DataFrame) -> list[list[tuple | None]]:
    """Cada forma posible de sacar fecha + hora de la tabla: una columna con las dos, o una de fecha y otra de hora."""
    partes = {c: [_partes(v) for v in tabla[c]] for c in tabla.columns}
    mitad = len(tabla) / 2
    momentos, fechas, horas = [], [], []
    for c, ps in partes.items():
        con_fecha = sum(f is not None for f, _ in ps)
        con_hora = sum(h is not None for _, h in ps)
        distintas = len({h for _, h in ps if h})
        if con_fecha > mitad and con_hora > mitad and distintas > 1:
            momentos.append(c)
            horas.append(c)  # su fecha puede ser de relleno ("2009-09-20 13:00"): la hora sirve con otra fecha
        elif con_fecha > mitad:
            fechas.append(c)
        elif con_hora > mitad:
            horas.append(c)
    formas = [[(f, h) if f and h else None for f, h in partes[c]] for c in momentos]
    for cf in fechas:
        for ch in horas:
            formas.append([(f, h) if f and h else None for (f, _), (_, h) in zip(partes[cf], partes[ch])])
    return formas


def claves_de_horario(tabla: pd.DataFrame, contra: set | None = None) -> list[tuple | None]:
    """(fecha, "HH:MM") de cada fila; si hay varias formas de leerlas, la que más empareja con `contra`."""
    formas = _candidatas(tabla)
    if not formas:
        return [None] * len(tabla)
    if contra:
        return max(formas, key=lambda f: len({k for k in f if k} & contra))
    return max(formas, key=lambda f: sum(k is not None for k in f))


def _minutos(clave: tuple) -> int:
    fecha, hora = clave
    return (fecha.toordinal() * 24 + int(hora[:2])) * 60 + int(hora[3:])


def por_corrimiento(claves: list[tuple | None], del_ejemplo: set) -> dict[int, float]:
    """% de emisiones del ejemplo que están en la lectura con cada corrimiento de horas, con ±2 min de margen."""
    leidas = {_minutos(k) for k in claves if k}
    if not leidas:
        return {}
    # Solo cuentan los días que trae la grilla: el ejemplo puede ser de una semana corrida.
    primero, ultimo = min(leidas) - 1440, max(leidas) + 1440
    ejemplo = [x for k in del_ejemplo if primero <= (x := _minutos(k)) <= ultimo]
    if not ejemplo:
        return {}
    return {horas: sum(any(m + horas * 60 + d in leidas for d in range(-TOLERANCIA_MIN, TOLERANCIA_MIN + 1))
                       for m in ejemplo) / len(ejemplo)
            for horas in CORRIMIENTOS_HORAS}


def emparejadas(claves: list[tuple | None], del_ejemplo: set) -> float:
    """% de emisiones del ejemplo que están en la lectura, con el corrimiento de zona que más empareje."""
    return max(por_corrimiento(claves, del_ejemplo).values(), default=0.0)


def pares_con_ejemplo(entrada: pd.DataFrame, esperado: pd.DataFrame) -> list[tuple[int, int]] | None:
    """(fila del ejemplo, fila de la grilla) emparejadas por fecha y hora, con el corrimiento de zona que más empareje.

    Las reglas no agregan ni sacan filas: la fila de la grilla es la misma de la salida. None = comparar fila por fila
    (misma cantidad de filas, o sin horario para emparejar).
    """
    if len(entrada) == len(esperado):
        return None
    del_ejemplo = claves_de_horario(esperado)
    leidas = claves_de_horario(entrada, {k for k in del_ejemplo if k})
    por_minuto = {}
    for j, k in enumerate(leidas):
        if k:
            por_minuto.setdefault(_minutos(k), j)
    if not por_minuto:
        return None
    ejemplo = [(i, _minutos(k)) for i, k in enumerate(del_ejemplo) if k]
    margen = sorted(range(-TOLERANCIA_MIN, TOLERANCIA_MIN + 1), key=abs)  # primero la hora exacta
    mejor: list[tuple[int, int]] = []
    for horas in CORRIMIENTOS_HORAS:
        pares = [(i, j) for i, m in ejemplo
                 if (j := next((por_minuto[x] for d in margen if (x := m + horas * 60 + d) in por_minuto), None)) is not None]
        if len(pares) > len(mejor):
            mejor = pares
    return mejor or None


def lectura(tabla: pd.DataFrame, esperado: pd.DataFrame | None = None) -> dict:
    """Qué tan bien se leyó una grilla: filas, % con fecha y hora, y % del ejemplo que aparece en la lectura."""
    del_ejemplo = {k for k in claves_de_horario(esperado) if k} if esperado is not None else None
    claves = claves_de_horario(tabla, del_ejemplo)
    con_horario = sum(k is not None for k in claves) / len(tabla) if len(tabla) else 0.0
    empareja = emparejadas(claves, del_ejemplo) if del_ejemplo else None
    return {"filas": len(tabla), "con_horario": round(con_horario, 3),
            "empareja": None if empareja is None else round(empareja, 3)}


def problemas_de_lectura(medida: dict) -> list[str]:
    """Lo que falla de una lectura, en palabras para devolverle al agente. Vacío = aprobada."""
    problemas = []
    if medida["filas"] == 0:
        return ["La lectura no dio ninguna fila."]
    if medida["con_horario"] < UMBRAL_HORARIO:
        problemas.append(f"Solo el {medida['con_horario']:.0%} de las filas tiene fecha y hora legibles "
                         f"(hace falta {UMBRAL_HORARIO:.0%}).")
    if medida["empareja"] is not None and medida["empareja"] < UMBRAL_EMPAREJA:
        problemas.append(f"Solo el {medida['empareja']:.0%} de las emisiones del ejemplo aparecen con la misma "
                         f"fecha y hora en la lectura (hace falta {UMBRAL_EMPAREJA:.0%}).")
    return problemas
