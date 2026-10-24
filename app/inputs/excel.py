from pathlib import Path
from typing import BinaryIO

import pandas as pd

from app.engine import model as m


def leer(origen: str | Path | BinaryIO, entrada: m.EntradaExcel) -> pd.DataFrame:
    """Lee la hoja tal cual: sin convertir tipos, para que las tarjetas vean lo que vino."""
    df = pd.read_excel(origen, sheet_name=entrada.hoja, header=entrada.fila_encabezado - 1, dtype=object)
    df = df.dropna(how="all").reset_index(drop=True)
    df.columns = [str(c).strip() for c in df.columns]
    return df.astype(object).where(df.notna(), None)


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
