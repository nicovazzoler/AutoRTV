import datetime as dt
import io
import re
from collections import Counter
from pathlib import Path
from typing import BinaryIO

import pandas as pd

from app.engine import model as m
from app.inputs.pdf import DIAS, _plano, dia_de, dia_siguiente, fecha_de

ANIO = re.compile(r"\b(19|20)\d{2}\b")


def leer(origen: str | Path | BinaryIO, entrada: m.EntradaExcel) -> pd.DataFrame:
    """Lee la hoja tal cual: sin convertir tipos, para que las tarjetas vean lo que vino.

    Con `todas_las_hojas`, una tabla por hoja una abajo de la otra, en el orden del libro.
    """
    if isinstance(origen, (bytes, bytearray)):
        origen = io.BytesIO(origen)
    cuales = entrada.hojas or (None if entrada.todas_las_hojas else entrada.hoja)
    hojas = pd.read_excel(origen, sheet_name=cuales, header=entrada.fila_encabezado - 1, dtype=object)
    if isinstance(hojas, dict):
        saltear = {str(h).strip().lower() for h in entrada.saltear_hojas}
        hojas = {n: t for n, t in hojas.items() if str(n).strip().lower() not in saltear}
        tablas = _de_programacion(list(hojas.values()))
        nombres = [n for n, t in hojas.items() if any(t is x for x in tablas)]
    else:
        nombres, tablas = [entrada.hoja], [hojas]
    tablas = [_limpia(t) for t in _mismas_columnas(tablas)]
    salteadas = []
    if entrada.filas_de_fecha is not False:
        leidas, ultima = [], None
        for nombre, t in zip(nombres, tablas):
            # Una hoja que no se puede leer no tira abajo las demás: se saltea y queda anotada.
            try:
                t, ultima = _con_filas_de_fecha(t, forzar=entrada.filas_de_fecha is True, previa=ultima)
                leidas.append(t)
            except Exception as e:
                salteadas.append(f"{nombre} ({e})")
        tablas = leidas
    if not tablas:
        raise ValueError("No se pudo leer ninguna hoja: " + "; ".join(salteadas))
    df = pd.concat(tablas, ignore_index=True) if len(tablas) > 1 else tablas[0]
    df = df.astype(object).where(df.notna(), None)
    df.attrs["hojas"] = len(tablas)
    df.attrs["salteadas"] = salteadas
    return df


def _encabezado(t: pd.DataFrame) -> set[str]:
    return {str(c).strip().lower() for c in t.columns if not str(c).startswith("Unnamed")}


def _parecido(a: set[str], b: set[str]) -> bool:
    return bool(a) and len(a & b) >= len(a) * 0.7


def _de_programacion(tablas: list[pd.DataFrame]) -> list[pd.DataFrame]:
    """Solo las hojas con el encabezado de la mayoría: una portada o una hoja de notas no suman filas."""
    encabezados = [_encabezado(t) for t in tablas]
    modelo = max(encabezados, key=lambda e: sum(_parecido(e, otro) for otro in encabezados))
    return [t for t, e in zip(tablas, encabezados) if _parecido(modelo, e)]


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


def _con_filas_de_fecha(df: pd.DataFrame, forzar: bool = False, previa: dt.date | None = None
                        ) -> tuple[pd.DataFrame, dt.date | None]:
    """Agrega la Fecha de cada programa desde las filas sueltas que la dicen, y saca las filas que no son programas
    (sin hora de inicio, como "Intermedio", o sin ningún texto). Si la tabla ya trae fecha o no hay filas de fecha,
    queda como vino. `previa` es la última fecha de la hoja anterior; devuelve la última de esta."""
    inicio = _columna_de_inicio(df)
    con_fecha = any(sum(map(_es_fecha, (v for v in df[c] if v is not None))) > len(df) / 2 for c in df.columns)
    if inicio is None or (con_fecha and not forzar):
        return df, previa
    fechas, filas, fecha, anterior, anio = [], [], None, None, None
    ultima = previa
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
            dia = dia_de(texto)
            # "SÁBADO 31 NOVIEMBRE" no existe: es el día que sigue al anterior (el próximo sábado).
            if nueva is None and dia is not None and re.search(r"\d", texto) and (fecha or ultima):
                nueva = dia_siguiente(fecha or ultima, dia)
            if nueva:
                fecha, anterior, ultima = nueva, None, nueva
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
        return df, previa
    salida = df.iloc[filas].reset_index(drop=True)
    salida.insert(0, "Fecha", fechas)
    return salida, (fecha or ultima)


def hojas_de_programacion(contenido: bytes) -> tuple[int, int] | None:
    """(fila de encabezado, cuántas hojas) si el libro trae varias hojas con el mismo encabezado; None si no.

    El encabezado se busca en cada hoja: la primera puede ser una portada.
    """
    libro = pd.ExcelFile(io.BytesIO(contenido))
    if len(libro.sheet_names) < 2:
        return None
    filas = [detectar_fila_encabezado(libro, h) for h in libro.sheet_names]
    encabezados = [_encabezado(pd.read_excel(libro, sheet_name=h, header=f - 1, nrows=0))
                   for h, f in zip(libro.sheet_names, filas)]
    iguales = [[_parecido(e, otro) for otro in encabezados] for e in encabezados]
    mejor = max(range(len(encabezados)), key=lambda i: sum(iguales[i]))
    cuantas = sum(iguales[mejor])
    if cuantas < max(2, len(encabezados) * 0.6):
        return None
    return filas[mejor], cuantas


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
