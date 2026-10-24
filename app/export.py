"""Salida a xlsx/csv y a JSON para la vista previa."""
import datetime as dt
import io

import pandas as pd
from openpyxl import Workbook


def _es_fecha_sola(v) -> bool:
    return isinstance(v, dt.datetime) and v.time() == dt.time(0) or type(v) is dt.date


def celda_json(v):
    """Valor de celda tal como lo ve una persona: 01/10/2026, 06:00, texto, número."""
    if v is None or (isinstance(v, float) and pd.isna(v)) or v is pd.NaT:
        return None
    if isinstance(v, pd.Timestamp):
        v = v.to_pydatetime()
    if _es_fecha_sola(v):
        return v.strftime("%d/%m/%Y")
    if isinstance(v, dt.datetime):
        return v.strftime("%d/%m/%Y %H:%M")
    if isinstance(v, dt.time):
        return v.strftime("%H:%M") if v.second == 0 else v.strftime("%H:%M:%S")
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def a_filas(df: pd.DataFrame, limite: int | None = None) -> list[list]:
    datos = df if limite is None else df.head(limite)
    return [[celda_json(v) for v in fila] for fila in datos.itertuples(index=False)]


def a_xlsx(df: pd.DataFrame) -> bytes:
    """Fechas como fecha y horas como hora de Excel, para importarlo igual que el hecho a mano."""
    wb = Workbook()
    ws = wb.active
    ws.append(list(df.columns))
    for fila in df.itertuples(index=False):
        ws.append([_celda_excel(v) for v in fila])
    for col in ws.iter_cols(min_row=2):
        for c in col:
            if isinstance(c.value, dt.datetime):
                c.number_format = "dd/mm/yyyy" if c.value.time() == dt.time(0) else "dd/mm/yyyy hh:mm"
            elif isinstance(c.value, dt.time):
                c.number_format = "hh:mm"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _celda_excel(v):
    if v is None or (isinstance(v, float) and pd.isna(v)) or v is pd.NaT:
        return None
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    if type(v) is dt.date:
        return dt.datetime.combine(v, dt.time(0))
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def a_csv(df: pd.DataFrame) -> bytes:
    filas = [[celda_json(v) for v in f] for f in df.itertuples(index=False)]
    # utf-8 con BOM para que Excel en Windows abra bien los acentos.
    return pd.DataFrame(filas, columns=df.columns).to_csv(index=False).encode("utf-8-sig")
