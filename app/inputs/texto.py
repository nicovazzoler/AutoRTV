"""Texto pegado de un mail o una web, o un .txt: columnas con separador, o líneas "06:00 Programa"."""
import csv
import datetime as dt
import io
import re

import pandas as pd

from app.engine import model as m
from app.inputs.pdf import dia_de, fecha_de

SEPARADORES = ["\t", ";", "|", ","]
LINEA_CON_HORA = re.compile(r"^\s*(\d{1,2})[:.h](\d{2})\s*(?:hs?\.?)?\s*[-–:]?\s*(.*)$")


def decodificar(contenido: bytes) -> str:
    for codificacion in ("utf-8-sig", "cp1252"):
        try:
            return contenido.decode(codificacion)
        except UnicodeDecodeError:
            continue
    return contenido.decode("latin-1")


def _separador(lineas: list[str]) -> str | None:
    """El que aparece la misma cantidad de veces en casi todas las líneas."""
    for sep in SEPARADORES:
        cuentas = [ln.count(sep) for ln in lineas]
        comun = max(set(cuentas), key=cuentas.count)
        if comun >= 1 and cuentas.count(comun) >= 0.6 * len(lineas):
            return sep
    return None


def leer(contenido: bytes, entrada: m.EntradaTexto) -> pd.DataFrame:
    texto = decodificar(contenido)
    lineas = [ln for ln in texto.splitlines() if ln.strip()]
    if not lineas:
        raise ValueError("El texto está vacío")
    sep = entrada.separador if entrada.separador is not None else _separador(lineas)
    if sep:
        return _con_separador(lineas, sep)
    return _por_lineas(lineas, entrada)


def _con_separador(lineas: list[str], sep: str) -> pd.DataFrame:
    filas = [[c.strip() or None for c in f] for f in csv.reader(io.StringIO("\n".join(lineas)), delimiter=sep)]
    ancho = max(map(len, filas))
    filas = [f + [None] * (ancho - len(f)) for f in filas]
    # Si la primera línea no trae horas, son los nombres de columna.
    if not any(LINEA_CON_HORA.match(c or "") for c in filas[0]):
        nombres = [c or f"Columna {i + 1}" for i, c in enumerate(filas[0])]
        filas = filas[1:]
    else:
        nombres = [f"Columna {i + 1}" for i in range(ancho)]
    return pd.DataFrame(filas, columns=nombres).astype(object)


def _por_lineas(lineas: list[str], entrada: m.EntradaTexto) -> pd.DataFrame:
    """Las líneas de día ("Lunes 2/11") ponen la fecha de las que siguen; las sueltas se suman al detalle."""
    inicio = dt.date.fromisoformat(entrada.fecha_inicio) if entrada.fecha_inicio else None
    anio = inicio.year if inicio else dt.date.today().year
    fecha, filas, previa, nombre_dia = inicio, [], None, None
    for linea in lineas:
        g = LINEA_CON_HORA.match(linea)
        if g:
            hora = dt.time(int(g[1]) % 24, int(g[2]))
            if previa is not None and fecha is not None and hora < previa:
                fecha += dt.timedelta(days=1)  # pasó la medianoche
            filas.append({"Fecha": dt.datetime.combine(fecha, dt.time(0)) if fecha else None,
                          "Dia": nombre_dia, "Hora": hora, "Programa": g[3].strip() or None, "Detalle": None})
            previa = hora
            continue
        nueva = fecha_de(linea, anio)
        dia = dia_de(linea)
        if nueva or (dia is not None and len(linea.split()) <= 4):
            if nueva:
                fecha = nueva
            elif inicio:
                fecha = inicio + dt.timedelta(days=(dia - inicio.weekday()) % 7)
            nombre_dia = linea.strip() if dia is not None else None
            previa = None
            continue
        if filas:
            anterior = filas[-1]["Detalle"]
            filas[-1]["Detalle"] = f"{anterior} {linea.strip()}" if anterior else linea.strip()
    if not filas:
        raise ValueError("No encontré líneas que empiecen con una hora (06:00 Programa)")
    tabla = pd.DataFrame(filas).astype(object)
    # Sin fechas, el nombre del día queda para armar la semana desde el lunes que se elija (app/fechar.py).
    if tabla["Fecha"].notna().any() or tabla["Dia"].isna().all():
        tabla = tabla.drop(columns="Dia")
    return tabla

