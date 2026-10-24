"""Tarjetas que trabajan sobre la tabla entera: columnas, numeración, horarios."""
import datetime as dt

import pandas as pd

from app.engine import model as m
from app.engine.util import ErrorTarjeta, columnas_de

DIAS = {
    "es": ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"],
    "en": ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"],
}


def renombrar(df, t: m.Renombrar):
    columnas_de(df, list(t.mapa))
    return df.rename(columns=t.mapa)


def numerar(df, t: m.Numerar):
    df[t.columna] = [t.inicio + i * t.paso for i in range(len(df))]
    return df


def redondear_hora(df, t: m.RedondearHora):
    (col,) = columnas_de(df, [t.columna])
    paso = t.a_minutos * 60

    def redondear(v):
        h = a_hora(v)
        if h is None:
            return v
        seg = h.hour * 3600 + h.minute * 60 + h.second
        # Después de 23:59:30 redondearía a 24:00, que no existe sin cambiar la fecha:
        # se topea en el último paso del día.
        seg = min(round(seg / paso) * paso, 86400 - paso)
        return dt.time(seg // 3600, seg % 3600 // 60)

    df[col] = df[col].map(redondear)
    return df


def dia_semana(df, t: m.DiaSemana):
    (col,) = columnas_de(df, [t.columna])

    def nombre(v):
        f = a_fecha(v)
        if f is None:
            return None
        n = DIAS[t.idioma][f.weekday()]
        return n.upper() if t.mayusculas else n.capitalize()

    df[t.destino] = df[col].map(nombre)
    return df


def duracion(df, t: m.Duracion):
    columnas_de(df, [t.fecha, t.hora])
    inicios = [_inicio(f, h) for f, h in zip(df[t.fecha], df[t.hora])]
    minutos = []
    for i, ini in enumerate(inicios):
        sig = inicios[i + 1] if i + 1 < len(inicios) else _fin_de_grilla(ini, t.ultimo_hasta)
        minutos.append(None if ini is None or sig is None else int((sig - ini).total_seconds() // 60))
    df[t.destino] = minutos
    return df


def _inicio(fecha, hora) -> dt.datetime | None:
    f, h = a_fecha(fecha), a_hora(hora)
    return dt.datetime.combine(f, h) if f and h else None


def _fin_de_grilla(ini: dt.datetime | None, hasta: str | None) -> dt.datetime | None:
    if ini is None or not hasta:
        return None
    h = a_hora(hasta)
    if h is None:
        raise ErrorTarjeta(f"Hora inválida en 'ultimo_hasta': {hasta}")
    fin = dt.datetime.combine(ini.date(), h)
    return fin if fin > ini else fin + dt.timedelta(days=1)


def a_fecha(v) -> dt.date | None:
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    if isinstance(v, str) and v.strip():
        try:
            return pd.to_datetime(v.strip(), dayfirst=True).date()
        except (ValueError, TypeError):
            return None
    return None


def a_hora(v) -> dt.time | None:
    if isinstance(v, dt.datetime):
        return v.time()
    if isinstance(v, dt.time):
        return v
    if isinstance(v, str) and v.strip():
        for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M:%S %p"):
            try:
                return dt.datetime.strptime(v.strip(), fmt).time()
            except ValueError:
                pass
    return None


def clasificar_sinopsis(df, t: m.ClasificarSinopsis):
    """Misma sinopsis en casi todos los capítulos = argumento de programa; distintas = de capítulo.

    Los programas que quedan como "programa" pero tienen alguna sinopsis distinta se avisan:
    puede ser un argumento puntual de un capítulo o dos argumentos del mismo programa,
    y eso lo decide una persona.
    """
    columnas_de(df, [t.programa, t.capitulo, t.sinopsis])
    sinopsis = df[t.sinopsis].map(_texto_o_none)
    a_programa = sinopsis.copy()  # filas sin programa conservan su sinopsis
    a_capitulo = pd.Series(None, index=df.index, dtype=object)
    avisos = []
    for programa, grupo in df.groupby(df[t.programa].map(_texto_o_none), dropna=True, sort=False):
        textos = sinopsis[grupo.index].dropna()
        capitulos = grupo[t.capitulo].map(lambda v: _texto_o_none(v) or "").nunique()
        if capitulos >= 2 and textos.nunique() / capitulos > t.umbral:
            a_capitulo[grupo.index] = sinopsis[grupo.index]
            a_programa[grupo.index] = None
            continue
        if textos.nunique() > 1:
            mayoritaria = textos.mode()[0]
            filas = [str(i + 1) for i in textos.index if textos[i] != mayoritaria]
            avisos.append(f"{programa}: sinopsis distinta en fila(s) {', '.join(filas)}")
    df[t.destino_programa] = a_programa
    df[t.destino_capitulo] = a_capitulo
    return df, avisos


def _texto_o_none(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    return s or None
