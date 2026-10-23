"""Concert Channel contra el EPG hecho a mano. Los archivos son del laburo y viven en privado/."""
import json
from pathlib import Path

import pandas as pd
import pytest

from app.engine import model as m
from app.engine.comparar import diferencias
from app.engine.pipeline import correr
from app.inputs import excel

DIR = Path(__file__).resolve().parents[2] / "privado" / "concert"
pytestmark = pytest.mark.skipif(not DIR.exists(), reason="sin datos privados de Concert Channel")


def test_concert_coincide_con_el_esperado():
    senal = m.Senal.model_validate(json.loads((DIR / "senal.json").read_text(encoding="utf-8")))
    salida, informes = correr(senal, excel.leer(DIR / "entrada.xlsx", senal.entrada))
    esperado = pd.read_excel(DIR / "esperado.xlsx", dtype=object)

    assert [i for i in informes if i.error] == []
    assert len(salida) == len(esperado)
    assert diferencias(salida, esperado) == []
