"""Grillas semanales que vienen sin fechas, o con fechas de otra semana: se pasan a la semana que elige la persona."""
import datetime as dt
import re

import pandas as pd

from app.inputs.pdf import dia_de

FECHA_TEXTO = re.compile(r"^\s*\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}")
# Días de margen antes de avisar que la grilla trae fechas viejas.
VIEJA_DESDE_DIAS = 7


def _es_fecha(v) -> bool:
    return isinstance(v, (dt.date, pd.Timestamp)) or (isinstance(v, str) and bool(FECHA_TEXTO.match(v)))


def _mayoria(serie: pd.Series, prueba) -> bool:
    valores = [v for v in serie if v is not None and not (isinstance(v, float) and pd.isna(v))]
    return bool(valores) and sum(map(prueba, valores)) > len(valores) / 2


def columnas_de_fecha(tabla: pd.DataFrame) -> list[str]:
    return [c for c in tabla.columns if _mayoria(tabla[c], _es_fecha)]


def columna_de_dia(tabla: pd.DataFrame) -> str | None:
    """Una columna con nombres de día ("Lunes", "MON"), para las grillas semanales que no traen fechas."""
    return next((c for c in tabla.columns if _mayoria(tabla[c], lambda v: isinstance(v, str) and dia_de(v) is not None)), None)


def lunes_de(dia: dt.date) -> dt.date:
    return dia - dt.timedelta(days=dia.weekday())


def fechar(tabla: pd.DataFrame, lunes: dt.date) -> pd.DataFrame:
    """Corre las fechas a la semana de `lunes`, manteniendo el día de la semana de cada programa.

    Sin columnas de fecha, la arma desde la columna con nombres de día. Sin ninguna de las dos, queda como vino.
    """
    from app.engine.tarjetas.estructura import a_fecha
    from app.semanas import _correr_fecha

    tabla = tabla.copy()
    fechas = columnas_de_fecha(tabla)
    if fechas:
        dias = [d for c in fechas for v in tabla[c] if (d := a_fecha(v))]
        if not dias:
            return tabla
        corrimiento = (lunes_de(lunes) - lunes_de(min(dias))).days
        for c in fechas:
            tabla[c] = [v if v is None else _correr_fecha(v, corrimiento) for v in tabla[c]]
        return tabla
    if (col := columna_de_dia(tabla)) is None:
        return tabla
    lunes = lunes_de(lunes)
    tabla.insert(0, "Fecha", [dt.datetime.combine(lunes + dt.timedelta(days=d), dt.time()) if (d := dia_de(v)) is not None
                              else None for v in tabla[col]])
    return tabla


def aviso(tabla: pd.DataFrame, desde: str | None, hasta: str | None, hoy: dt.date | None = None) -> dict | None:
    """Si la grilla es semanal sin fechas o trae fechas viejas: qué pasa y qué lunes se sugiere."""
    hoy = hoy or dt.date.today()
    sugerido = lunes_de(hoy) if hoy.weekday() < 3 else lunes_de(hoy) + dt.timedelta(days=7)
    if desde is None and columna_de_dia(tabla) is not None:
        return {"tipo": "sin_fechas", "desde": None, "hasta": None, "sugerido": sugerido.isoformat()}
    if hasta and dt.date.fromisoformat(hasta) < hoy - dt.timedelta(days=VIEJA_DESDE_DIAS):
        return {"tipo": "viejas", "desde": desde, "hasta": hasta, "sugerido": sugerido.isoformat()}
    return None
