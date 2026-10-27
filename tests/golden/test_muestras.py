"""Lectores contra grillas reales y su macro hecha. Los archivos son del laburo y viven en muestras/."""
from pathlib import Path

import pandas as pd
import pytest

from app import inputs, pautas
from app.engine import model as m

DIR = Path(__file__).resolve().parents[2] / "muestras" / "ejemplos"
pytestmark = pytest.mark.skipif(not DIR.exists(), reason="sin las muestras del laburo")

PDFS = [
    ("GRILLA TRECE SEMANA 43-OCTUBRE- A#U00d1O 2026 (19-10).pdf", "Ejemplo Trece (RPC).xlsx", "f", "h", None, 172),
    ("Grade TV NOVA 44.2026 - 26.10.2026 a 01.11.2026 (21-10).pdf", "Ejemplo TV Nova Nordeste.xlsx", "f", "HORA", [1], 212),
    # Televisión Mexiquense: 4 celdas traen dos programas con " / " y la macro las parte en dos filas.
    ("Programacion 34.1 semana 44 (24-10).pdf", "Ejemplo IG (24-10).xlsx", "FECHA", "HORA", None, 165),
]


def _esperado(nombre: str) -> pd.DataFrame:
    df = pd.read_excel(DIR / nombre, dtype=object)
    return df.astype(object).where(df.notna(), None)


@pytest.mark.parametrize("archivo,ejemplo,col_fecha,col_hora,paginas,iguales", PDFS)
def test_pdf_trae_los_mismos_horarios_que_la_macro(archivo, ejemplo, col_fecha, col_hora, paginas, iguales):
    df = inputs.leer((DIR / archivo).read_bytes(), m.EntradaPdf(tipo="pdf", paginas=paginas or []))
    leidos = {(f.date(), i.strftime("%H:%M")) for f, i in zip(df["Fecha"], df["Inicio"])}
    esperado = _esperado(ejemplo)
    claves = [(f.date(), h.strftime("%H:%M")) for f, h in zip(esperado[col_fecha], esperado[col_hora])]
    assert sum(c in leidos for c in claves) == iguales


@pytest.mark.parametrize("archivo,ejemplo,minimo", [
    ("Urban-Travel (13-10).xml", "Ejemplo Urban Travel.xlsx", 0.99),
    ("outerHTML OWN TV.txt", "Ejemplo OWN TV.xlsx", 0.85),
    ("HTML TBN.txt", "Ejemplo TBN.xlsx", 0.8),
])
def test_la_base_del_ejemplo_reconoce_la_grilla(archivo, ejemplo, minimo):
    contenido = (DIR / archivo).read_bytes()
    crudo = inputs.leer(contenido, inputs.detectar(contenido))
    ejemplo_pautas, _ = pautas.desde_ejemplo(crudo, _esperado(ejemplo))
    base = {h: {"salida": p["salida"], "estado": "revisada"} for h, p in ejemplo_pautas.items()}
    _, estados, _ = pautas.aplicar(crudo, crudo, base)
    assert estados.count("conocida") / len(estados) >= minimo
