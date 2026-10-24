"""Tarjetas que transforman el texto de cada celda."""
import re
from collections.abc import Callable

import pandas as pd

from app.engine import model as m
from app.engine.util import celdas_texto, columnas_de, rellenar_plantilla

# Corte entre programa y episodio pegados: termina en minúscula/signo/paréntesis y sigue mayúscula.
# Los dígitos no cortan para no romper casos como "Azpm News: Vote2026".
MIN_MAYUS = re.compile(r"^(.*?[a-z!?.)'])([A-Z].*)$")

PRESETS_EXTRAER = {
    "entre_parentesis": r"\(([^)]*)\)",
    "numero": r"(\d+)",
    "anio": r"\b((?:19|20)\d{2})\b",
}

PALABRAS_CHICAS_EN = {
    "a", "an", "and", "as", "at", "but", "by", "for", "from", "in", "into", "nor",
    "of", "on", "or", "the", "to", "vs", "vs.", "with",
}


def _transformar(df: pd.DataFrame, columnas, mascara: pd.Series, fn: Callable[[str], str]) -> pd.DataFrame:
    for col in columnas_de(df, columnas):
        filas = mascara & celdas_texto(df[col])
        df.loc[filas, col] = df.loc[filas, col].map(fn)
    return df


def limpiar_espacios(df, t: m.LimpiarEspacios, mascara):
    return _transformar(df, t.columnas, mascara, lambda s: re.sub(r"\s+", " ", s).strip())


def reemplazar(df, t: m.Reemplazar, mascara):
    if t.modo == "texto":
        fn = lambda s: s.replace(t.buscar, t.por)
    elif t.modo == "celda":
        fn = lambda s: t.por if s == t.buscar else s
    else:
        patron = re.compile(t.buscar)
        fn = lambda s: patron.sub(t.por, s)
    return _transformar(df, t.columnas, mascara, fn)


def quitar(df, t: m.Quitar, mascara):
    cuerpo = t.texto if t.regex else re.escape(t.texto)
    patron = re.compile({"todo": cuerpo, "inicio": f"^(?:{cuerpo})", "fin": f"(?:{cuerpo})$"}[t.donde])
    return _transformar(df, t.columnas, mascara, lambda s: patron.sub("", s))


def mayus_minus(df, t: m.MayusMinus, mascara):
    fn = {
        "MAYUS": str.upper,
        "minus": str.lower,
        "Titulo": lambda s: " ".join(p[:1].upper() + p[1:].lower() for p in s.split(" ")),
        "Oracion": lambda s: s[:1].upper() + s[1:].lower(),
        "titulo_en": titulo_en,
    }[t.modo]
    return _transformar(df, t.columnas, mascara, fn)


def titulo_en(s: str) -> str:
    """Título en inglés: cada palabra con inicial mayúscula, palabras chicas en minúscula.

    Los guiones cuentan como corte ("Ellis-Bextor") pero el apóstrofe no ("O'neill"),
    igual que en los EPG terminados.
    """
    palabras = s.split(" ")
    salida = []
    for i, palabra in enumerate(palabras):
        despues_de_corte = i == 0 or palabras[i - 1] == "-" or palabras[i - 1].endswith(":")
        if not despues_de_corte and palabra.lower() in PALABRAS_CHICAS_EN:
            salida.append(palabra.lower())
        else:
            salida.append("-".join(_capitalizar(p) for p in palabra.split("-")))
    return " ".join(salida)


SIGLA_CON_PUNTOS = re.compile(r"^(?:[A-Za-z]\.)+$")


def _capitalizar(palabra: str) -> str:
    if SIGLA_CON_PUNTOS.match(palabra):  # "R.E.M.", "D.C."
        return palabra.upper()
    # Se saltean signos de apertura; si arranca con número ("00's") no hay inicial.
    i = 0
    while i < len(palabra) and palabra[i] in "([\"'¿¡":
        i += 1
    if i < len(palabra) and palabra[i].isalpha():
        return palabra[:i] + palabra[i].upper() + palabra[i + 1:].lower()
    return palabra.lower()


def asignar(df, t: m.Asignar, mascara):
    if t.columna not in df.columns:
        df[t.columna] = None
    df.loc[mascara, t.columna] = df[mascara].apply(lambda fila: rellenar_plantilla(t.valor, fila), axis=1)
    return df


def a_numero(df, t: m.ANumero, mascara):
    for col in columnas_de(df, t.columnas):
        df.loc[mascara, col] = df.loc[mascara, col].map(_a_numero)
    return df


def _a_numero(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        f = float(str(v).strip())
    except ValueError:
        return v  # se deja como venía; no es un número
    return int(f) if f.is_integer() else f


def separar(df, t: m.Separar, mascara):
    (col,) = columnas_de(df, [t.columna])
    a, b = t.destinos
    for destino in (a, b):
        if destino not in df.columns:
            df[destino] = None
    titulos = sorted(t.titulos, key=len, reverse=True)
    filas = mascara & celdas_texto(df[col])
    partes = df.loc[filas, col].map(lambda s: _separar_uno(s, t, titulos))
    df.loc[filas, a] = partes.map(lambda p: p[0])
    df.loc[filas, b] = partes.map(lambda p: p[1])
    return df


def _separar_uno(s: str, t: m.Separar, titulos: list[str]) -> tuple[str, str]:
    if t.modo == "separador":
        if t.valor and t.valor in s:
            izq, der = s.split(t.valor, 1)
            return izq.strip(), der.strip()
        return s, ""
    if t.modo == "regex":
        r = re.match(t.valor, s)
        return (r.group(1).strip(), r.group(2).strip()) if r else (s, "")
    if t.modo == "titulos_conocidos":
        for titulo in titulos:
            if s.startswith(titulo):
                return titulo, s[len(titulo):].lstrip(" -:").strip()
        if t.respaldo == "ninguno":
            return s, ""
    r = MIN_MAYUS.match(s)
    return (r.group(1).strip(), r.group(2).strip()) if r else (s, "")


def extraer(df, t: m.Extraer, mascara):
    (col,) = columnas_de(df, [t.columna])
    patron = re.compile(PRESETS_EXTRAER[t.preset] if t.preset else t.patron)
    if t.destino not in df.columns:
        df[t.destino] = None
    filas = mascara & celdas_texto(df[col])
    for i in df.index[filas]:
        s = df.at[i, col]
        r = patron.search(s)
        if not r:
            continue
        df.at[i, t.destino] = r.group(1) if r.groups() else r.group(0)
        if t.quitar_del_origen:
            df.at[i, col] = re.sub(r"\s+", " ", s[: r.start()] + s[r.end():]).strip()
    return df


def correcciones(df, t: m.Correcciones, mascara):
    return _transformar(df, t.columnas, mascara, lambda s: t.mapa.get(s, s))
