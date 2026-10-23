import datetime as dt

import pandas as pd

from app.engine import model as m
from app.validate.grilla import detectar_columnas, resumen, validar

V = m.Validaciones()
D = dt.datetime(2026, 10, 2)


def grilla(*programas, columnas=("FECHA", "HORA", "DUR")):
    """programas = (día, 'HH:MM', minutos); día 0 = 2/10."""
    filas = [(D + dt.timedelta(days=d), dt.datetime.strptime(h, "%H:%M").time(), m_) for d, h, m_ in programas]
    return pd.DataFrame(filas, columns=list(columnas))


def reglas(avisos, nivel=None):
    return [(a.regla, a.fila) for a in avisos if nivel is None or a.nivel == nivel]


PERFECTA = [(0, "06:00", 600), (0, "16:00", 480), (1, "00:00", 720), (1, "12:00", 720), (2, "00:00", 360)]


def test_grilla_perfecta_solo_informa_dias_parciales():
    avisos = validar(grilla(*PERFECTA), V)
    assert resumen(avisos) == {"error": 0, "aviso": 0, "info": 2}
    assert reglas(avisos) == [("dia_parcial", 1), ("dia_parcial", 5)]


def test_hueco_de_10_minutos():
    g = [(0, "06:00", 600), (0, "16:10", 470), (1, "00:00", 720), (1, "12:00", 720), (2, "00:00", 360)]
    avisos = validar(grilla(*g), V)
    assert ("hueco", 2) in reglas(avisos, "aviso")
    assert "10 min" in next(a.mensaje for a in avisos if a.regla == "hueco")


def test_hueco_dentro_de_la_tolerancia_no_avisa():
    g = [(0, "06:00", 600), (0, "16:02", 478), (1, "00:00", 720), (1, "12:00", 720), (2, "00:00", 360)]
    v = m.Validaciones(tolerancia_min=5, dia_minutos=None)
    assert reglas(validar(grilla(*g), v)) == []


def test_superposicion():
    g = [(0, "06:00", 620), (0, "16:00", 480), (1, "00:00", 720), (1, "12:00", 720)]
    avisos = validar(grilla(*g), V)
    assert ("superposicion", 2) in reglas(avisos, "error")


def test_desorden():
    g = [(0, "10:00", 60), (0, "09:00", 60)]
    assert ("orden", 2) in reglas(validar(grilla(*g), V), "error")


def test_dia_del_medio_corto():
    g = [(0, "06:00", 600), (0, "16:00", 480), (1, "00:00", 720), (1, "12:00", 710), (2, "00:00", 360)]
    avisos = validar(grilla(*g), V)
    assert ("dia_minutos", 3) in reglas(avisos, "error")
    assert ("hueco", 5) in reglas(avisos, "aviso")


def test_duracion_larga_y_negativa():
    avisos = validar(grilla((0, "00:00", 800), (0, "13:20", 0)), m.Validaciones(dia_minutos=None))
    assert reglas(avisos, "error") == [("duracion_larga", 1), ("duracion", 2)]


def test_hora_ilegible():
    g = grilla((0, "00:00", 60), (0, "01:00", 60))
    g.loc[1, "HORA"] = "mañana"
    assert ("ilegible", 2) in reglas(validar(g, V), "error")


def test_detecta_columnas_por_nombre_o_usa_las_elegidas():
    assert detectar_columnas(["FECHA", "HORA", "DUR"], V) == {"fecha": "FECHA", "hora": "HORA", "duracion": "DUR"}
    propias = m.Validaciones(fecha="Dia de emision", hora="Inicio", duracion="Minutos")
    assert detectar_columnas(["x"], propias)["hora"] == "Inicio"


def test_sin_columnas_avisa_cual_falta():
    avisos = validar(pd.DataFrame({"FECHA": [D], "Inicio": ["06:00"]}), V)
    assert len(avisos) == 1 and avisos[0].regla == "config"
    assert "hora, duracion" in avisos[0].mensaje


def test_filas_esperadas_y_obligatorias():
    g = grilla((0, "00:00", 720))
    g["TIT"] = [" "]
    avisos = validar(g, m.Validaciones(filas_esperadas=2, obligatorias=["TIT", "NO_ESTA"], dia_minutos=None))
    assert reglas(avisos, "aviso") == [("filas", None), ("obligatorias", 1), ("obligatorias", None)]


def test_tope_de_avisos_por_regla():
    g = grilla(*[(0, "00:00", 0)] * 205)
    avisos = validar(g, m.Validaciones(dia_minutos=None))
    assert sum(a.regla == "duracion" for a in avisos) == 201  # 200 + el que dice cuántos faltan
