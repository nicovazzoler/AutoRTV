"""Una celda con varios programas pasa a una fila por programa."""
import datetime as dt
import re

import pandas as pd

from app.engine import model as m
from app.engine.tarjetas.estructura import a_fecha, a_hora
from app.engine.util import ErrorTarjeta


def _minutos(inicio: dt.time, fin: dt.time) -> int:
    total = (fin.hour * 60 + fin.minute) - (inicio.hour * 60 + inicio.minute)
    return total + 1440 if total <= 0 else total


def _repartir(total: int, partes: int, paso: int) -> list[int]:
    """Partes iguales redondeadas al paso; la última se queda con lo que sobra."""
    cada = max(paso, round(total / partes / paso) * paso)
    duraciones = [cada] * (partes - 1)
    return duraciones + [max(total - sum(duraciones), paso)]


def partir_filas(tabla: pd.DataFrame, p: m.Partir) -> pd.DataFrame:
    faltan = [c for c in (p.columna, p.inicio, p.fin) if c not in tabla.columns]
    if faltan:
        raise ErrorTarjeta(f"Para partir celdas falta la columna: {', '.join(faltan)}")
    separador, condicion = re.compile(p.separador), re.compile(p.solo_si) if p.solo_si else None
    fecha_col = next((c for c in tabla.columns if c != p.inicio and all(
        a_fecha(v) is not None for v in tabla[c].dropna().head(20)) and tabla[c].notna().any()), None)
    filas = []
    for _, fila in tabla.iterrows():
        texto, inicio, fin = fila[p.columna], a_hora(fila[p.inicio]), a_hora(fila[p.fin])
        partes = [x.strip() for x in separador.split(texto)] if isinstance(texto, str) else []
        partes = [x for x in partes if x]
        if len(partes) < 2 or inicio is None or fin is None or (condicion and not any(map(condicion.search, partes))):
            filas.append(fila.to_dict())
            continue
        momento = dt.datetime.combine(a_fecha(fila[fecha_col]) if fecha_col else dt.date(2000, 1, 1), inicio)
        for parte, minutos in zip(partes, _repartir(_minutos(inicio, fin), len(partes), p.a_minutos)):
            nueva = fila.to_dict()
            nueva.update({p.columna: parte, p.inicio: momento.time(), p.fin: (momento + dt.timedelta(minutes=minutos)).time()})
            if fecha_col:
                nueva[fecha_col] = dt.datetime.combine(momento.date(), dt.time(0))
            filas.append(nueva)
            momento += dt.timedelta(minutes=minutos)
    return pd.DataFrame(filas, columns=list(tabla.columns)).astype(object)
