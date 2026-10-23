import pandas as pd
import pytest

from app.engine import model as m
from app.engine.pipeline import aplicar
from app.engine.tarjetas.texto import titulo_en
from pydantic import TypeAdapter

tarjeta = TypeAdapter(m.Tarjeta).validate_python


def correr(filas: dict, *tarjetas: dict) -> pd.DataFrame:
    r = aplicar(pd.DataFrame(filas), [tarjeta(t) for t in tarjetas])
    assert [i.error for i in r.informes] == [None] * len(tarjetas)
    return r.tabla


def test_limpiar_espacios_incluye_nbsp_y_saltos():
    df = correr({"a": ["  N'Dubz, \xa0\nLee  Ryan "]}, {"id": "t", "tipo": "limpiar_espacios"})
    assert df["a"][0] == "N'Dubz, Lee Ryan"


def test_reemplazar_modos():
    filas = {"a": ["vs US", "x"]}
    assert correr(filas, {"id": "t", "tipo": "reemplazar", "columnas": ["a"], "buscar": "x", "por": "y", "modo": "celda"})["a"].tolist() == ["vs US", "y"]
    assert correr(filas, {"id": "t", "tipo": "reemplazar", "columnas": ["a"], "buscar": r"\bvs\b", "por": "vs.", "modo": "regex"})["a"][0] == "vs. US"


def test_quitar_al_final():
    df = correr({"a": ["Show (HD)", "(HD) Show"]}, {"id": "t", "tipo": "quitar", "columnas": ["a"], "texto": " (HD)", "donde": "fin"})
    assert df["a"].tolist() == ["Show", "(HD) Show"]


@pytest.mark.parametrize("entrada, programa, episodio", [
    ("Joseph PrinceGrace Revolution", "Joseph Prince", "Grace Revolution"),
    ("Azpm News: Vote2026 Special", "Azpm News: Vote2026 Special", ""),  # los dígitos no cortan
    ("Praise", "Praise", ""),
])
def test_separar_min_mayus(entrada, programa, episodio):
    df = correr({"a": [entrada]}, {"id": "t", "tipo": "separar", "columna": "a", "modo": "min_mayus", "destinos": ["p", "e"]})
    assert (df["p"][0], df["e"][0]) == (programa, episodio)


def test_separar_titulos_conocidos_gana_al_patron():
    t = {"id": "t", "tipo": "separar", "columna": "a", "modo": "titulos_conocidos", "titulos": ["MacGyver"],
         "respaldo": "min_mayus", "destinos": ["p", "e"]}
    df = correr({"a": ["MacGyverThe Gun", "Joseph PrinceGrace"]}, t)
    assert df["p"].tolist() == ["MacGyver", "Joseph Prince"]
    assert df["e"].tolist() == ["The Gun", "Grace"]


def test_separar_por_guion():
    df = correr({"a": ["Show - Ep 1", "Solo"]}, {"id": "t", "tipo": "separar", "columna": "a", "modo": "separador", "valor": " - ", "destinos": ["p", "e"]})
    assert df["p"].tolist() == ["Show", "Solo"] and df["e"].tolist() == ["Ep 1", ""]


@pytest.mark.parametrize("entrada, esperado", [
    ("Paloma Faith - Live In England 2024", "Paloma Faith - Live in England 2024"),
    ("OutKast", "Outkast"),
    ("Lisa O'Neill / Sophie Ellis-Bextor", "Lisa O'neill / Sophie Ellis-Bextor"),
    ("Top Of The Pops: The Collection", "Top of the Pops: The Collection"),
    ("R.E.M. - Live", "R.E.M. - Live"),
    ("00's Nostalgia", "00's Nostalgia"),
])
def test_titulo_en(entrada, esperado):
    assert titulo_en(entrada) == esperado


def test_extraer_anio_y_quitar():
    df = correr({"a": ["Concierto (2024) en vivo"]}, {"id": "t", "tipo": "extraer", "columna": "a", "preset": "anio", "destino": "y", "quitar_del_origen": True})
    assert df["y"][0] == "2024" and df["a"][0] == "Concierto () en vivo"


def test_asignar_con_condicion_y_plantilla():
    t = {"id": "t", "tipo": "asignar", "columna": "cap", "valor": "",
         "si": {"columna": "cap", "op": "igual", "valor": "{prog}"}}
    df = correr({"prog": ["A", "B"], "cap": ["A", "x"]}, t)
    assert df["cap"].tolist() == ["", "x"]


def test_a_numero():
    df = correr({"a": ["01", 23.0, None, "S1"]}, {"id": "t", "tipo": "a_numero", "columnas": ["a"]})
    assert df["a"].tolist() == [1, 23, None, "S1"]
