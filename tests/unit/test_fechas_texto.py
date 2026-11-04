import datetime as dt

import pandas as pd
import pytest

from app.engine.tarjetas.estructura import a_fecha

NOVIEMBRE_2 = dt.date(2026, 11, 2)


@pytest.mark.parametrize("texto", ["2026-11-02", "2026-11-02 06:00", "2026-11-02T06:00:00", "2026-11-02T06:00:00Z",
                                   "02/11/2026", "2/11/26", "02-11-2026"])
def test_las_fechas_en_texto_no_invierten_dia_y_mes(texto):
    # pandas 3 con dayfirst=True leía "2026-11-02" como 11 de febrero: pasaba solo con los días del 1 al 12.
    assert a_fecha(texto) == NOVIEMBRE_2


def test_lo_que_no_es_una_fecha_queda_vacio():
    assert a_fecha("lunes") is None and a_fecha("2026-13-45") is None and a_fecha(pd.NaT) is None


def test_la_semana_con_fechas_iso_en_texto_tiene_sus_fechas(cliente):
    from tests.unit.test_api import excel
    grilla = pd.DataFrame({"Fecha": ["2026-11-02", "2026-11-03", "2026-11-08"], "Hora": ["06:00", "06:00", "06:00"],
                           "Programa": ["Noticias", "Cine", "Deportes"]})
    receta = {"id": "web", "nombre": "Web", "entrada": {"tipo": "excel"}, "salida": {"columnas": []}, "tarjetas": []}
    cliente.put("/api/senales/web", json=receta)
    d = cliente.post("/api/senales/web/abierta", files={"archivo": ("g.xlsx", excel(grilla))}).json()
    assert (d["resumen"]["desde"], d["resumen"]["hasta"]) == ("2026-11-02", "2026-11-08")
