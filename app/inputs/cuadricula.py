"""Grilla en cuadrícula: un día por columna (fechas en una fila de arriba), una fila por franja horaria
(horas en la primera columna) y celdas combinadas: el alto de un bloque es su duración y el ancho, los días
en que se repite."""
import datetime as dt
import io
import statistics

import pandas as pd

from app.engine.tarjetas.estructura import a_hora

# Más fechas que esto en una fila = es la fila de los días.
MIN_DIAS = 3
FILAS_PARA_BUSCAR = 5
# Un número de serie de Excel por encima de esto es una fecha (20000 = año 1954).
SERIE_MINIMA = 20000
EXCEL_CERO = dt.datetime(1899, 12, 30)


def _celdas_xls(contenido: bytes, hoja) -> tuple[list[list], list[tuple]]:
    import xlrd

    libro = xlrd.open_workbook(file_contents=contenido, formatting_info=True)
    h = libro.sheet_by_name(hoja) if isinstance(hoja, str) else libro.sheet_by_index(hoja)

    def valor(r, c):
        celda = h.cell(r, c)
        if celda.ctype == xlrd.XL_CELL_DATE:
            momento = xlrd.xldate_as_datetime(celda.value, libro.datemode)
            return momento.time() if celda.value < 1 else momento
        return None if celda.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK) else celda.value

    celdas = [[valor(r, c) for c in range(h.ncols)] for r in range(h.nrows)]
    return celdas, list(h.merged_cells)


def _celdas_xlsx(contenido: bytes, hoja) -> tuple[list[list], list[tuple]]:
    from openpyxl import load_workbook

    libro = load_workbook(io.BytesIO(contenido), data_only=True)
    h = libro[hoja] if isinstance(hoja, str) else libro.worksheets[hoja]
    celdas = [list(fila) for fila in h.iter_rows(values_only=True)]
    combinadas = [(r.min_row - 1, r.max_row, r.min_col - 1, r.max_col) for r in h.merged_cells.ranges]
    return celdas, combinadas


def _celdas(contenido: bytes, hoja) -> tuple[list[list], list[tuple]]:
    """Valores de la hoja y bloques combinados (fila desde, fila hasta, col desde, col hasta; el hasta no entra)."""
    if contenido.startswith(b"PK"):
        return _celdas_xlsx(contenido, hoja)
    return _celdas_xls(contenido, hoja)


def _fecha(v) -> dt.date | None:
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    if isinstance(v, (int, float)) and v > SERIE_MINIMA:
        return (EXCEL_CERO + dt.timedelta(days=float(v))).date()
    if isinstance(v, str) and any(ch.isdigit() for ch in v):
        f = pd.to_datetime(v.strip(), dayfirst=True, errors="coerce")
        return None if pd.isna(f) else f.date()
    return None


def _hora(v) -> dt.time | None:
    if isinstance(v, dt.datetime):
        return v.time()
    if isinstance(v, dt.time):
        return v
    if isinstance(v, (int, float)) and 0 <= v < 1:
        return (dt.datetime.min + dt.timedelta(seconds=round(v * 86400))).time()
    return a_hora(v) if isinstance(v, str) else None


def _fila_de_dias(celdas: list[list]) -> int | None:
    for r, fila in enumerate(celdas[:FILAS_PARA_BUSCAR]):
        if sum(_fecha(v) is not None for v in fila[1:]) >= MIN_DIAS:
            return r
    return None


def es_cuadricula(contenido: bytes, hoja=0) -> bool:
    try:
        celdas, _ = _celdas(contenido, hoja)
    except Exception:  # un archivo que no se puede abrir así lo maneja el lector común
        return False
    r = _fila_de_dias(celdas)
    if r is None:
        return False
    abajo = [fila[0] if fila else None for fila in celdas[r + 1:]]
    return bool(abajo) and sum(_hora(v) is not None for v in abajo) > len(abajo) / 2


def _minutos(h: dt.time) -> int:
    return h.hour * 60 + h.minute


def leer(contenido: bytes, hoja=0) -> pd.DataFrame:
    """Una emisión por bloque y por día, con Fecha, Hora, Duracion (minutos) y Titulo."""
    celdas, combinadas = _celdas(contenido, hoja)
    r_dias = _fila_de_dias(celdas)
    if r_dias is None:
        raise ValueError("No encontré la fila con las fechas de cada día")
    dias = {c: _fecha(v) for c, v in enumerate(celdas[r_dias]) if c > 0 and _fecha(v)}
    filas = [(r, _hora(celdas[r][0])) for r in range(r_dias + 1, len(celdas)) if celdas[r] and _hora(celdas[r][0])]

    # Lo que dura cada franja es lo que falta hasta la siguiente; la última dura lo que dura una franja común.
    largos = [(_minutos(b) - _minutos(a)) % 1440 for (_, a), (_, b) in zip(filas, filas[1:])]
    comun = int(statistics.median(largos)) if largos else 30
    largos.append(comun)
    # Si la hora vuelve para atrás (grilla de 06:00 a 05:30), esa franja ya es del día siguiente.
    corrido, previa = [], None
    for _, hora in filas:
        corrido.append((corrido[-1] if corrido else 0) + (previa is not None and _minutos(hora) < _minutos(previa)))
        previa = hora

    dueno = {}
    for r0, r1, c0, c1 in combinadas:
        for r in range(r0, r1):
            for c in range(c0, c1):
                dueno[(r, c)] = (r0, c0)

    def valor(r, c):
        fila = celdas[r]
        return fila[c] if c < len(fila) else None

    emisiones = []
    for c, dia in dias.items():
        actual = None
        for (r, hora), largo, extra in zip(filas, largos, corrido):
            bloque = dueno.get((r, c), (r, c))
            v = valor(*bloque)
            titulo = " ".join(str(v).split()) if v not in (None, "") else ""
            if not titulo:
                actual = None
                continue
            if actual and actual["bloque"] == bloque:
                actual["Duracion"] += largo
                continue
            actual = {"bloque": bloque, "Fecha": dt.datetime.combine(dia + dt.timedelta(days=extra), dt.time()),
                      "Hora": hora, "Duracion": largo, "Titulo": titulo}
            emisiones.append(actual)
    df = pd.DataFrame(emisiones, columns=["Fecha", "Hora", "Duracion", "Titulo", "bloque"]).drop(columns="bloque")
    return df.sort_values(["Fecha", "Hora"], kind="stable").reset_index(drop=True).astype(object)
