import json

import pandas as pd
from pydantic import TypeAdapter

from app.engine import model as m
from app.engine.pipeline import aplicar, correr
from app.engine.titulos import aprender
from app.validate.grilla import validar

tarjeta = TypeAdapter(m.Tarjeta).validate_python
SEPARAR = {"id": "s", "tipo": "separar", "columna": "titulo", "modo": "titulos_conocidos",
           "respaldo": "min_mayus", "destinos": ["Programa", "Capitulo"]}


def test_aprender_cuenta_y_limpia():
    a = pd.DataFrame({"Programa": ["MacGyver", " MacGyver ", "Praise", None, 2024, "  "]})
    b = pd.DataFrame({"TIT ING": ["Praise", "Joseph  Prince"]})
    conteo, columna = aprender([a, b])
    assert conteo == {"MacGyver": 2, "Praise": 2, "Joseph Prince": 1}
    assert columna == "Programa"


def test_aprender_con_columna_elegida():
    conteo, columna = aprender([pd.DataFrame({"Show": ["A"], "Programa": ["B"]})], "Show")
    assert dict(conteo) == {"A": 1} and columna == "Show"


def test_separar_usa_los_titulos_de_la_senal():
    tabla = pd.DataFrame({"titulo": ["MacGyverThe Gun", "Joseph PrinceGrace"]})
    con = aplicar(tabla, [tarjeta(SEPARAR)], titulos=["MacGyver"]).tabla
    sin = aplicar(tabla, [tarjeta(SEPARAR)]).tabla
    assert con["Programa"].tolist() == ["MacGyver", "Joseph Prince"]
    assert sin["Programa"][0] == "Mac"  # el patrón solo corta mal: por eso hace falta la lista


def test_correr_pasa_los_titulos_de_la_receta():
    senal = m.Senal(id="x", nombre="x", entrada={"tipo": "excel"}, tarjetas=[SEPARAR], salida={"columnas": []},
                    titulos_conocidos=["MacGyver"])
    salida, _ = correr(senal, pd.DataFrame({"titulo": ["MacGyverThe Gun"]}))
    assert (salida["Programa"][0], salida["Capitulo"][0]) == ("MacGyver", "The Gun")


def test_aviso_de_titulo_nuevo():
    salida = pd.DataFrame({"Programa": ["Praise", "Joseph PrinceGrace", "Joseph PrinceGrace"]})
    v = m.Validaciones(avisar_titulos_nuevos=True, dia_minutos=None)
    nuevos = [a for a in validar(salida, v, ["Praise", "Joseph Prince"]) if a.regla == "titulo_nuevo"]
    assert [(a.nivel, a.fila, a.mensaje) for a in nuevos] == [("info", 2, "Título nuevo: Joseph PrinceGrace (2 veces)")]
    assert not [a for a in validar(salida, m.Validaciones(dia_minutos=None)) if a.regla == "titulo_nuevo"]
