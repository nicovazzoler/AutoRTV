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
