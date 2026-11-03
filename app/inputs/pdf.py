"""Grillas semanales en PDF: una tabla con las horas en una columna y un día por columna."""
import datetime as dt
import re
import unicodedata
from typing import BinaryIO

import pandas as pd

from app.engine import model as m

DIAS = {
    "lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3, "viernes": 4, "sabado": 5, "domingo": 6,
    "segunda": 0, "terca": 1, "quarta": 2, "quinta": 3, "sexta": 4,
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
}
MESES = {"ene": 1, "jan": 1, "feb": 2, "fev": 2, "mar": 3, "abr": 4, "apr": 4, "may": 5, "mai": 5, "jun": 6,
         "jul": 7, "ago": 8, "aug": 8, "sep": 9, "set": 9, "oct": 10, "out": 10, "nov": 11, "dic": 12, "dez": 12,
         "dec": 12}
# "06:00", "6.00", "06:00h" o un rango ("06:00- 06:10", "12:30 13:00"): vale la hora de inicio.
HORA = re.compile(r"^(\d{1,2})[:.h](\d{2})(?:\s*-?\s*(?:\d{1,2}[:.h]\d{2})?)?$")
GROSOR_LINEA = 2.5
OSCURO = 0.5


def _plano(texto: str) -> str:
    return unicodedata.normalize("NFD", texto).encode("ascii", "ignore").decode().lower()


def _luminancia(color) -> float:
    if color is None:
        return 1.0
    if isinstance(color, (int, float)):
        return float(color)
    c = list(color)
    if len(c) == 1:
        return float(c[0])
    if len(c) == 3:
        return 0.3 * c[0] + 0.59 * c[1] + 0.11 * c[2]
    if len(c) == 4:  # CMYK
        return 1 - min(1.0, c[3] + 0.3 * c[0] + 0.59 * c[1] + 0.11 * c[2])
    return 1.0


def _bordes(pagina) -> dict:
    """Solo las líneas oscuras: los fondos blancos o de color también son rectángulos y partirían las celdas."""
    finos = [r for r in pagina.rects if min(r["bottom"] - r["top"], r["x1"] - r["x0"]) < GROSOR_LINEA
             and _luminancia(r.get("non_stroking_color")) < OSCURO]
    lineas = [ln for ln in pagina.lines if _luminancia(ln.get("stroking_color")) < OSCURO]
    objetos = finos + lineas
    return {
        "vertical_strategy": "explicit", "horizontal_strategy": "explicit",
        "explicit_vertical_lines": [o for o in objetos if o["x1"] - o["x0"] < GROSOR_LINEA],
        "explicit_horizontal_lines": [o for o in objetos if o["bottom"] - o["top"] < GROSOR_LINEA],
        "snap_tolerance": 2, "join_tolerance": 2, "intersection_tolerance": 2,
    }


def _hora(texto) -> dt.time | None:
    g = HORA.match(" ".join((texto or "").split()))
    if not g or int(g[1]) > 24 or int(g[2]) > 59:
        return None
    return dt.time(int(g[1]) % 24, int(g[2]))


def dia_de(texto) -> int | None:
    palabras = re.findall(r"[a-z]+", _plano(texto or ""))
    return next((DIAS[p] for p in palabras if p in DIAS), None)


def fecha_de(texto, anio: int | None) -> dt.date | None:
    """La fecha escrita en el texto, o None si no hay o no existe ("31 NOVIEMBRE")."""
    t = _plano(texto or "")
    try:
        if g := re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", t):
            return dt.date(int(g[3]), int(g[2]), int(g[1]))
        if anio and (g := re.search(r"\b(\d{1,2})/(\d{1,2})\b", t)):
            return dt.date(anio, int(g[2]), int(g[1]))
        if anio and (g := re.search(r"(\d{1,2})\s*[-/ de]*\s*([a-z]{3})", t)) and g[2] in MESES:
            return dt.date(anio, MESES[g[2]], int(g[1]))
    except ValueError:
        return None
    return None


def dia_siguiente(anterior: dt.date, dia_semana: int | None) -> dt.date:
    """Para una fecha que no se pudo leer: el día que sigue a `anterior` o, si se sabe qué día de la semana es, el
    primero con ese nombre desde `anterior` (puede ser el mismo: la hoja nueva arranca el día que terminó la anterior)."""
    if dia_semana is None:
        return anterior + dt.timedelta(days=1)
    return anterior + dt.timedelta(days=(dia_semana - anterior.weekday()) % 7)


def _lunes_de_semana(texto: str) -> dt.date | None:
    """"Semana 43 - Año 2026" en el título: el lunes de esa semana ISO."""
    t = _plano(texto)
    semana, anio = re.search(r"semana\s*(\d{1,2})", t), re.search(r"\b(20\d{2})\b", t)
    if semana and anio:
        return dt.date.fromisocalendar(int(anio[1]), int(semana[1]), 1)
    return None


def _encabezado(datos: list[list]) -> tuple[int, dict[int, int], dict[int, str]]:
    """Fila de los días, columna → día de la semana y columna → texto de encabezado (para la fecha)."""
    for i, fila in enumerate(datos[:6]):
        dias = {j: d for j, x in enumerate(fila) if (d := dia_de(x)) is not None}
        if len(dias) >= 2:
            textos = {j: " ".join(str(datos[k][j] or "") for k in range(i + 1)) for j in dias}
            return i, dias, textos
    return -1, {}, {}


def _columna_hora(datos: list[list], desde: int) -> int | None:
    cuentas = {}
    for fila in datos[desde:]:
        for j, x in enumerate(fila):
            if _hora(x):
                cuentas[j] = cuentas.get(j, 0) + 1
    return min((j for j, n in cuentas.items() if n >= 3), default=None)


def _centro(caja, eje: int) -> float:
    return (caja[eje] + caja[eje + 2]) / 2


def leer(origen: BinaryIO, entrada: m.EntradaPdf) -> pd.DataFrame:
    import pdfplumber  # pesado: solo se carga cuando llega un PDF

    filas, dias_prev, anio = [], None, None
    with pdfplumber.open(origen) as pdf:
        texto_total = " ".join((p.extract_text() or "") for p in pdf.pages[:2])
        anios = re.findall(r"\b(20\d{2})\b", texto_total)
        anio = int(anios[0]) if anios else None
        lunes = (dt.date.fromisoformat(entrada.fecha_inicio) if entrada.fecha_inicio
                 else _lunes_de_semana(texto_total))
        for n, pagina in enumerate(pdf.pages, start=1):
            if entrada.paginas and n not in entrada.paginas:
                continue
            tablas = pagina.find_tables(_bordes(pagina)) or pagina.find_tables()
            if not tablas:
                continue
            tabla = max(tablas, key=lambda t: len(t.rows))
            datos, celdas = tabla.extract(), [r.cells for r in tabla.rows]
            i_enc, dias, textos = _encabezado(datos)
            if not dias and dias_prev:  # página sin encabezado: sigue con las columnas de la anterior
                dias, textos = dias_prev
            if not dias:
                continue
            dias_prev = (dias, textos)
            col_hora = _columna_hora(datos, i_enc + 1)
            if col_hora is None:
                continue
            fechas = {j: fecha_de(textos[j], anio) or (lunes + dt.timedelta(days=d) if lunes else None)
                      for j, d in dias.items()}
            horas = [(i, _hora(datos[i][col_hora]), celdas[i][col_hora]) for i in range(i_enc + 1, len(datos))]
            horas = [(i, h, c) for i, h, c in horas if h is not None and c is not None]
            x_dias = {j: _centro(celdas[i_enc][j], 0) for j in dias if celdas[i_enc][j]} if i_enc >= 0 else {}
            if not x_dias and dias_prev:
                x_dias = {j: _centro(c, 0) for j in dias for c in [celdas[horas[0][0]][j]] if c} if horas else {}
            filas += _programas(datos, celdas, horas, x_dias, dias, fechas, n)
    df = pd.DataFrame(filas, columns=["Pagina", "Dia", "Fecha", "Inicio", "Fin", "Programa"])
    df = _pasar_medianoche(df)
    orden = df.assign(_f=df["Fecha"].map(lambda f: f or dt.datetime.min))
    df = df.loc[orden.sort_values(["_f", "Dia", "Inicio"], kind="stable").index].reset_index(drop=True)
    return df.drop(columns="Pagina").astype(object)


def _programas(datos, celdas, horas, x_dias, dias, fechas, pagina) -> list[list]:
    """Cada celda con texto es un programa: los días que cubre a lo ancho y las horas que cubre a lo alto."""
    salida = []
    for pos, (i, inicio, _) in enumerate(horas):
        for j in dias:
            caja = celdas[i][j]
            texto = " ".join((datos[i][j] or "").split())
            if caja is None or not texto:
                continue
            cubiertos = [k for k in dias if k in x_dias and caja[0] <= x_dias[k] <= caja[2]] or [j]
            ultima = max((p for p, (_, _, c) in enumerate(horas) if caja[1] <= _centro(c, 1) <= caja[3]), default=pos)
            fin = horas[ultima + 1][1] if ultima + 1 < len(horas) else None
            for k in cubiertos:
                fecha = fechas.get(k)
                salida.append([pagina, dias[k], dt.datetime.combine(fecha, dt.time(0)) if fecha else None,
                               inicio, fin, texto])
    return salida


def _pasar_medianoche(df: pd.DataFrame) -> pd.DataFrame:
    """Grillas de 05:00 a 04:59: lo que viene después de medianoche en una columna es del día siguiente."""
    df = df.copy()
    for (pagina, dia), grupo in df.groupby(["Pagina", "Dia"], sort=False):
        previo, pasado = None, False
        for idx in grupo.index:
            inicio = df.at[idx, "Inicio"]
            if previo is not None and inicio < previo:
                pasado = True
            if pasado and df.at[idx, "Fecha"] is not None:
                df.at[idx, "Fecha"] = df.at[idx, "Fecha"] + dt.timedelta(days=1)
            previo = inicio
    return df
