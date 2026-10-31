import datetime as dt
import io
import re
from collections import Counter
from pathlib import Path
from typing import BinaryIO

import pandas as pd

from app.engine import model as m
from app.inputs.pdf import DIAS, _plano, fecha_de

ANIO = re.compile(r"\b(19|20)\d{2}\b")


def leer(origen: str | Path | BinaryIO, entrada: m.EntradaExcel) -> pd.DataFrame:
    """Lee la hoja tal cual: sin convertir tipos, para que las tarjetas vean lo que vino.

    Con `todas_las_hojas`, una tabla por hoja una abajo de la otra, en el orden del libro.
    """
    if isinstance(origen, (bytes, bytearray)):
        origen = io.BytesIO(origen)
    hojas = pd.read_excel(origen, sheet_name=None if entrada.todas_las_hojas else entrada.hoja,
                          header=entrada.fila_encabezado - 1, dtype=object)
    tablas = list(hojas.values()) if isinstance(hojas, dict) else [hojas]
    tablas = [_limpia(t) for t in _mismas_columnas(tablas)]
    if entrada.filas_de_fecha is not False:
        tablas = [_con_filas_de_fecha(t, forzar=entrada.filas_de_fecha is True) for t in tablas]
    df = pd.concat(tablas, ignore_index=True) if len(tablas) > 1 else tablas[0]
    return df.astype(object).where(df.notna(), None)


def _limpia(df: pd.DataFrame) -> pd.DataFrame:
    df = df.dropna(how="all").reset_index(drop=True)
    df.columns = [str(c).strip() for c in df.columns]
    return df.astype(object).where(df.notna(), None)


def _mismas_columnas(tablas: list[pd.DataFrame]) -> list[pd.DataFrame]:
    """Hojas del mismo ancho toman los nombres de columna que más se repiten: una hoja con "GSEPTIEMBRE" donde las demás
    dicen "Genero" no tiene que abrir otra columna."""
    if len(tablas) < 2:
        return tablas
    nombres, _ = Counter(tuple(str(c).strip() for c in t.columns) for t in tablas).most_common(1)[0]
    return [t.set_axis(list(nombres), axis=1) if len(t.columns) == len(nombres) else t for t in tablas]


def _es_hora(v) -> bool:
    return isinstance(v, dt.time) or (isinstance(v, (dt.datetime, pd.Timestamp)) and v.time() != dt.time(0))


def _es_fecha(v) -> bool:
    return isinstance(v, (dt.date, pd.Timestamp)) and not _es_hora(v)


def _columna_de_inicio(df: pd.DataFrame) -> str | None:
    """La primera columna con horas en la mayoría de sus celdas con valor: el inicio de cada programa."""
    for c in df.columns:
        valores = [v for v in df[c] if v is not None]
        if valores and sum(map(_es_hora, valores)) > len(valores) / 2:
            return c
    return None


def _texto_de(fila) -> str:
    return " ".join(str(v) for v in fila if v is not None)


def _con_filas_de_fecha(df: pd.DataFrame, forzar: bool = False) -> pd.DataFrame:
    """Agrega la Fecha de cada programa desde las filas sueltas que la dicen, y saca las filas que no son programas
    (sin hora de inicio, como "Intermedio", o sin ningún texto). Si la tabla ya trae fecha o no hay filas de fecha,
    queda como vino."""
    inicio = _columna_de_inicio(df)
    con_fecha = any(sum(map(_es_fecha, (v for v in df[c] if v is not None))) > len(df) / 2 for c in df.columns)
    if inicio is None or (con_fecha and not forzar):
        return df
    fechas, filas, fecha, anterior, anio = [], [], None, None, None
    for i, fila in enumerate(df.itertuples(index=False)):
        valores = list(fila)
        if valores[df.columns.get_loc(inicio)] is None:
            texto = _texto_de(valores)
            anio = int(x[0]) if (x := ANIO.search(texto)) else anio
            # Con varios días nombrados es un encabezado de cuadrícula ("LUNES 2 · MARTES 3"), no la fecha de abajo.
            if sum(p in DIAS for p in re.findall(r"[a-z]+", _plano(texto))) > 1:
                continue
            nueva = next((v.date() if isinstance(v, (dt.datetime, pd.Timestamp)) else v
                          for v in valores if _es_fecha(v)), None) or fecha_de(texto, anio or dt.date.today().year)
            if nueva:
                fecha, anterior = nueva, None
            continue
        if not any(isinstance(v, str) and re.search(r"[^\W\d_]", v) for v in valores):
            continue  # la fila que cierra el día: solo horas
        hora = valores[df.columns.get_loc(inicio)]
        hora = hora.time() if isinstance(hora, (dt.datetime, pd.Timestamp)) else hora
        if fecha and anterior and hora < anterior:  # pasó la medianoche sin fila de fecha
            fecha += dt.timedelta(days=1)
        anterior = hora
        fechas.append(dt.datetime.combine(fecha, dt.time()) if fecha else None)
        filas.append(i)
    if not any(fechas):
        return df
    salida = df.iloc[filas].reset_index(drop=True)
    salida.insert(0, "Fecha", fechas)
    return salida


def hojas_iguales(contenido: bytes, fila_encabezado: int) -> bool:
    """Si el libro trae varias hojas con el mismo encabezado: una por día o por semana."""
    libro = pd.ExcelFile(io.BytesIO(contenido))
    if len(libro.sheet_names) < 2:
        return False
    encabezados = [tuple(str(c).strip().lower() for c in pd.read_excel(libro, sheet_name=h, header=fila_encabezado - 1, nrows=0).columns)
                   for h in libro.sheet_names]
    _, veces = Counter(len(e) for e in encabezados).most_common(1)[0]
    primero = set(encabezados[0])
    parecidas = sum(len(primero & set(e)) >= len(primero) * 0.7 for e in encabezados)
    return parecidas >= max(2, len(encabezados) * 0.6) and veces >= 2


def detectar_fila_encabezado(origen: BinaryIO, hoja: int | str = 0, buscar: int = 10) -> int:
    """Fila (1 = primera) donde están los nombres de columna.

    Algunos exports traen un título arriba ("Schedule Data Export…"): se toma la primera fila
    que tiene texto en casi todas las columnas usadas.
    """
    crudo = pd.read_excel(origen, sheet_name=hoja, header=None, nrows=buscar, dtype=object)
    ancho = int(crudo.notna().sum(axis=1).max() or 0)
    for i, fila in crudo.iterrows():
        textos = sum(isinstance(v, str) and v.strip() != "" for v in fila)
        if ancho and textos >= max(2, ancho * 0.8):
            return int(i) + 1
    return 1
