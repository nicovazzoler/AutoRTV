"""Grilla en cuadrícula: un día por columna (fechas o nombres de día en una fila de arriba) y celdas combinadas.

Dos formas: por franjas (una fila cada media hora, el alto de un bloque es su duración) o por programa
(cada programa con su hora en la columna HORA más cercana a la izquierda, y el detalle en las filas de abajo).
"""
import datetime as dt
import io
import re
import statistics
import unicodedata

import pandas as pd

from app.engine.tarjetas.estructura import a_hora

# Más días que esto en una fila = es la fila de los días.
MIN_DIAS = 3
FILAS_PARA_BUSCAR = 10
DIAS_SEMANA = {
    0: ("lunes", "lun", "monday", "mon", "segunda", "seg"),
    1: ("martes", "mar", "tuesday", "tue", "terca", "ter"),
    2: ("miercoles", "mie", "mier", "wednesday", "wed", "quarta", "qua"),
    3: ("jueves", "jue", "thursday", "thu", "quinta", "qui"),
    4: ("viernes", "vie", "friday", "fri", "sexta", "sex"),
    5: ("sabado", "sab", "saturday", "sat"),
    6: ("domingo", "dom", "sunday", "sun"),
}
MESES = {"ene": 1, "jan": 1, "feb": 2, "fev": 2, "mar": 3, "abr": 4, "apr": 4, "may": 5, "mai": 5, "jun": 6,
         "jul": 7, "ago": 8, "aug": 8, "sep": 9, "set": 9, "oct": 10, "out": 10, "nov": 11, "dic": 12, "dec": 12, "dez": 12}
# "LUNES 26", "Lun. 26 de octubre", "Monday": nombre del día, número y mes opcionales.
DIA_NOMBRADO = re.compile(r"([a-z]+)\.?\s*(\d{1,2})?(?:\s*(?:de\s+)?([a-z]+)\.?)?(?:\s*(\d{4}))?")
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


def _sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")


def _dia_nombrado(v) -> tuple[int, int | None, int | None] | None:
    """(día de la semana, número del día, mes) de un encabezado como "MIÉRCOLES 28"."""
    if not isinstance(v, str) or len(v) > 30:
        return None
    m = DIA_NOMBRADO.fullmatch(" ".join(_sin_tildes(v).split()))
    if not m:
        return None
    semana = next((d for d, nombres in DIAS_SEMANA.items() if m[1] in nombres), None)
    if semana is None:
        return None
    mes = MESES.get((m[3] or "")[:3])
    return semana, int(m[2]) if m[2] else None, mes


def _referencia(celdas: list[list], hasta_fila: int) -> dt.date:
    """La primera fecha que diga el título ("DEL 26 DE OCT AL 01 NOV 2026"); si no hay, hoy."""
    texto = _sin_tildes(" ".join(str(v) for fila in celdas[:hasta_fila + 1] for v in fila if isinstance(v, str)))
    anio = re.search(r"\b(20\d{2})\b", texto)
    dia_mes = re.search(r"\b(\d{1,2})\s*(?:de\s+)?([a-z]{3})[a-z]*\b", texto)
    if anio and dia_mes and dia_mes[2] in MESES:
        try:
            return dt.date(int(anio[1]), MESES[dia_mes[2]], int(dia_mes[1]))
        except ValueError:
            pass
    return dt.date.today()


def _fechas_de_nombres(nombrados: dict[int, tuple], referencia: dt.date) -> dict[int, dt.date]:
    """Cada día con número cae en la fecha más cercana a la referencia con ese número y ese día de la semana;
    los que no traen número siguen al de su izquierda."""
    fechas, previa = {}, None
    for c, (semana, numero, mes) in sorted(nombrados.items()):
        if numero:
            candidatas = [referencia + dt.timedelta(days=d) for d in range(-200, 201)]
            candidatas = [f for f in candidatas if f.day == numero and f.weekday() == semana and (not mes or f.month == mes)]
            fecha = min(candidatas, key=lambda f: abs((f - referencia).days)) if candidatas else None
        elif previa:
            fecha = previa + dt.timedelta(days=(semana - previa.weekday()) % 7 or 7)
        else:
            fecha = referencia + dt.timedelta(days=(semana - referencia.weekday()) % 7)
        if fecha:
            fechas[c] = previa = fecha
    return fechas


def _dias_de_fila(celdas: list[list], r: int, minimo: int) -> dict[int, dt.date] | None:
    fila = celdas[r]
    fechas = {c: f for c, v in enumerate(fila) if c > 0 and (f := _fecha(v))}
    if len(fechas) >= minimo:
        return fechas
    nombrados = {c: d for c, v in enumerate(fila) if (d := _dia_nombrado(v))}
    if len(nombrados) >= minimo:
        return _fechas_de_nombres(nombrados, _referencia(celdas, r))
    return None


def _fila_de_dias(celdas: list[list], fila_dada: int | None = None) -> tuple[int, dict[int, dt.date]] | None:
    if fila_dada is not None:
        r = fila_dada - 1
        dias = _dias_de_fila(celdas, r, 1) if 0 <= r < len(celdas) else None
        return (r, dias) if dias else None
    for r in range(min(FILAS_PARA_BUSCAR, len(celdas))):
        if dias := _dias_de_fila(celdas, r, MIN_DIAS):
            return r, dias
    return None


def _indice_columna(letras: str) -> int:
    n = 0
    for letra in letras.strip().upper():
        n = n * 26 + ord(letra) - ord("A") + 1
    return n - 1


def _columnas_de_hora(celdas: list[list], r_dias: int, dias: dict[int, dt.date]) -> list[int]:
    ancho = max((len(f) for f in celdas), default=0)
    columnas = []
    for c in range(ancho):
        if c in dias:
            continue
        llenas = [f[c] for f in celdas[r_dias + 1:] if c < len(f) and f[c] not in (None, "") and str(f[c]).strip()]
        if len(llenas) >= MIN_DIAS and sum(_hora(v) is not None for v in llenas) > len(llenas) / 2:
            columnas.append(c)
    return columnas


def _estructura(celdas: list[list], fila_dias: int | None = None,
                columnas_hora: list[str] = ()) -> tuple[int, dict[int, dt.date], list[int]] | None:
    dias = _fila_de_dias(celdas, fila_dias)
    if dias is None:
        return None
    r, fechas = dias
    horas = sorted(_indice_columna(c) for c in columnas_hora) if columnas_hora else _columnas_de_hora(celdas, r, fechas)
    fechas = {c: f for c, f in fechas.items() if c not in horas}
    if not fechas or not horas or not any(h < min(fechas) for h in horas):
        return None
    return r, fechas, horas


def es_cuadricula(contenido: bytes, hoja=0) -> bool:
    try:
        celdas, _ = _celdas(contenido, hoja)
    except Exception:  # un archivo que no se puede abrir así lo maneja el lector común
        return False
    return _estructura(celdas) is not None


def _por_franjas(celdas: list[list], r_dias: int, horas: list[int]) -> bool:
    """Una sola columna de horas, la primera, con hora en casi todas las filas: una fila por franja fija."""
    if horas != [0]:
        return False
    filas = [f for f in celdas[r_dias + 1:] if any(v not in (None, "") for v in f)]
    return bool(filas) and sum(_hora(f[0]) is not None for f in filas) >= 0.9 * len(filas)


def _minutos(h: dt.time) -> int:
    return h.hour * 60 + h.minute


def _duenos(combinadas: list[tuple]) -> dict[tuple, tuple]:
    """Para cada celda tapada por una combinada, la celda de arriba a la izquierda que tiene el valor."""
    dueno = {}
    for r0, r1, c0, c1 in combinadas:
        for r in range(r0, r1):
            for c in range(c0, c1):
                dueno[(r, c)] = (r0, c0)
    return dueno


def leer(contenido: bytes, hoja=0, fila_dias: int | None = None, columnas_hora: list[str] = (),
         doce_horas: bool | None = None) -> pd.DataFrame:
    """Una emisión por bloque y por día, con Fecha, Hora, Duracion (minutos) y Titulo (y Detalle, por programa).

    `fila_dias`, `columnas_hora` y `doce_horas` fuerzan lo que la detección no encuentra sola (los propone el agente).
    """
    celdas, combinadas = _celdas(contenido, hoja)
    estructura = _estructura(celdas, fila_dias, columnas_hora)
    if estructura is None:
        raise ValueError("No encontré la fila con los días y la columna de las horas")
    r_dias, dias, horas = estructura
    if doce_horas is None and _por_franjas(celdas, r_dias, horas):
        return _leer_franjas(celdas, combinadas, r_dias, dias)
    return _leer_programas(celdas, combinadas, r_dias, dias, horas, doce_horas)


def _leer_franjas(celdas: list[list], combinadas: list[tuple], r_dias: int, dias: dict[int, dt.date]) -> pd.DataFrame:
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

    dueno = _duenos(combinadas)

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


def _lineas(v) -> list[str]:
    return [" ".join(linea.split()) for linea in str(v).splitlines() if linea.strip()] if v not in (None, "") else []


# "#12 Progresiones": es un capítulo, no un programa.
CAPITULO_SUELTO = re.compile(r"#\s*\d")


def _leer_programas(celdas, combinadas, r_dias, dias, horas, doce_horas: bool | None = None) -> pd.DataFrame:
    dueno = _duenos(combinadas)

    def celda(r, c):
        return celdas[r][c] if c < len(celdas[r]) else None

    def hora_en(r, c) -> dt.time | None:
        """La hora de la fila para la columna de día c; None si en esa fila no arranca nada para ese día."""
        t = max((h for h in horas if h < c), default=None)
        if t is None:
            return None
        r0, c0 = dueno.get((r, t), (r, t))
        if c0 < t:  # una combinada que viene de la izquierda tapa esta columna HORA: vale la de su izquierda
            return hora_en(r, c0)
        return _hora(celda(r, t)) if r0 == r else None

    def contenido(r, c) -> list[str]:
        r0, c0 = dueno.get((r, c), (r, c))
        return _lineas(celda(r0, c0)) if r0 == r else []  # lo combinado hacia abajo ya se leyó en su primera fila

    doce = doce_horas if doce_horas is not None else all(
        h.hour <= 12 for r in range(r_dias + 1, len(celdas)) for t in horas if (h := _hora(celda(r, t))))
    emisiones = []
    for c, dia in dias.items():
        arranques = [(r, h) for r in range(r_dias + 1, len(celdas)) if (h := hora_en(r, c))]
        programas, previo = [], None
        for i, (r, h) in enumerate(arranques):
            minutos = (h.hour % 12 if doce else h.hour) * 60 + h.minute
            while previo is not None and minutos < previo:  # 12:30 → 01:00 son las 13:00; 23:30 → 00:30, otro día
                minutos += 720 if doce else 1440
            previo = minutos
            fin = arranques[i + 1][0] if i + 1 < len(arranques) else len(celdas)
            lineas = [x for rr in range(r, fin) for x in contenido(rr, c)]
            programas.append({"minutos": minutos, "lineas": lineas})
        # La grilla a veces pone el título una fila arriba de su hora: queda como última línea del anterior.
        for antes, ahora in zip(programas, programas[1:]):
            if ahora["lineas"] and CAPITULO_SUELTO.match(ahora["lineas"][0]) and len(antes["lineas"]) > 1:
                ahora["lineas"].insert(0, antes["lineas"].pop())
        # Una hora sin programa no arranca nada, salvo la última del día: marca dónde termina el anterior.
        con_algo = [p for p in programas if p["lineas"]]
        if programas and not programas[-1]["lineas"]:
            con_algo.append(programas[-1])
        for p, siguiente in zip(con_algo, con_algo[1:] + [None]):
            if not p["lineas"]:
                continue
            emisiones.append({
                "Fecha": dt.datetime.combine(dia + dt.timedelta(days=p["minutos"] // 1440), dt.time()),
                "Hora": dt.time(p["minutos"] % 1440 // 60, p["minutos"] % 60),
                "Duracion": siguiente["minutos"] - p["minutos"] if siguiente else None,
                "Titulo": p["lineas"][0],
                "Detalle": " / ".join(p["lineas"][1:]) or None,
            })
    df = pd.DataFrame(emisiones, columns=["Fecha", "Hora", "Duracion", "Titulo", "Detalle"])
    return df.sort_values(["Fecha", "Hora"], kind="stable").reset_index(drop=True).astype(object)
