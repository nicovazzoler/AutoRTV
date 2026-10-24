import datetime as dt

import pandas as pd
from pydantic import TypeAdapter

from app.engine import model as m
from app.engine.pipeline import aplicar

tarjeta = TypeAdapter(m.Tarjeta).validate_python
D = dt.datetime(2026, 10, 31)


def test_redondear_y_duracion_hasta_siguiente():
    df = pd.DataFrame({"f": [D, D, D + dt.timedelta(days=1)],
                       "h": [dt.time(19, 30), dt.time(20, 26, 47), dt.time(4, 0)]})
    r = aplicar(df, [
        tarjeta({"id": "a", "tipo": "redondear_hora", "columna": "h"}),
        tarjeta({"id": "b", "tipo": "duracion", "modo": "hasta_siguiente", "fecha": "f", "hora": "h", "ultimo_hasta": "06:00"}),
    ])
    assert r.tabla["h"].tolist()[1] == dt.time(20, 27)
    assert r.tabla["Duracion"].tolist() == [57, 453, 120]


def test_redondeo_no_pasa_de_medianoche():
    r = aplicar(pd.DataFrame({"h": [dt.time(23, 59, 50)]}), [tarjeta({"id": "a", "tipo": "redondear_hora", "columna": "h"})])
    assert r.tabla["h"][0] == dt.time(23, 59)


def test_dia_semana_con_tilde():
    r = aplicar(pd.DataFrame({"f": [D]}), [tarjeta({"id": "a", "tipo": "dia_semana", "columna": "f"})])
    assert r.tabla["Dia"][0] == "SÁBADO"


def test_numerar_con_paso():
    r = aplicar(pd.DataFrame({"x": [1, 2, 3]}), [tarjeta({"id": "a", "tipo": "numerar", "paso": 5})])
    assert r.tabla["N"].tolist() == [1, 6, 11]


def test_columna_inexistente_avisa_y_sigue():
    r = aplicar(pd.DataFrame({"a": [" x "]}), [
        tarjeta({"id": "mal", "tipo": "renombrar", "mapa": {"no_existe": "y"}}),
        tarjeta({"id": "bien", "tipo": "limpiar_espacios"}),
    ])
    assert r.informes[0].error == "No existe la columna: no_existe"
    assert r.informes[1].celdas_cambiadas == 1 and r.tabla["a"][0] == "x"


def test_estructural_rechaza_condicion():
    t = tarjeta({"id": "a", "tipo": "numerar", "si": {"columna": "x", "op": "vacio"}})
    r = aplicar(pd.DataFrame({"x": [1]}), [t])
    assert "no admite condición" in r.informes[0].error


def test_tarjeta_inactiva_no_corre():
    r = aplicar(pd.DataFrame({"a": [" x "]}), [tarjeta({"id": "a", "tipo": "limpiar_espacios", "activa": False})])
    assert r.tabla["a"][0] == " x "
