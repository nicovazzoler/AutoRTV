"""Concert Channel contra el EPG hecho a mano. Los archivos son del laburo y viven en privado/."""
import json
from pathlib import Path

import pandas as pd
import pytest

from app import pautas
from app.engine import model as m
from app.engine.comparar import diferencias
from app.engine.pipeline import correr
from app.inputs import excel
from app.validate.grilla import resumen, validar

DIR = Path(__file__).resolve().parents[2] / "privado" / "concert"
pytestmark = pytest.mark.skipif(not DIR.exists(), reason="sin datos privados de Concert Channel")


def test_concert_coincide_con_el_esperado():
    senal = m.Senal.model_validate(json.loads((DIR / "senal.json").read_text(encoding="utf-8")))
    salida, informes = correr(senal, excel.leer(DIR / "entrada.xlsx", senal.entrada))
    esperado = pd.read_excel(DIR / "esperado.xlsx", dtype=object)

    assert [i for i in informes if i.error] == []
    assert len(salida) == len(esperado)
    assert diferencias(salida, esperado) == []
    # Solo el 1/10 (arranca 06:00) y el 1/11 (termina 06:00) quedan como días parciales.
    assert resumen(validar(salida, senal.validaciones)) == {"error": 0, "aviso": 0, "info": 2}


def test_base_de_pautas_de_concert_reproduce_el_contenido():
    """Con una receta vacía y la base cargada del ejemplo, todo el contenido sale igual al EPG terminado."""
    receta = m.Senal.model_validate(json.loads((DIR / "senal.json").read_text(encoding="utf-8")))
    crudo = excel.leer(DIR / "entrada.xlsx", receta.entrada)
    esperado = pd.read_excel(DIR / "esperado.xlsx", dtype=object)
    esperado = esperado.astype(object).where(esperado.notna(), None)
    ejemplo, conflictos = pautas.desde_ejemplo(crudo, esperado)
    assert conflictos == 0
    base = {h: {"salida": p["salida"], "estado": "revisada"} for h, p in ejemplo.items()}

    salida, estados, _ = pautas.aplicar(crudo, crudo, base)
    contenido = pautas.columnas_de_contenido(list(esperado.columns))
    assert estados == ["conocida"] * 573
    assert diferencias(salida[contenido], esperado[contenido]) == []
