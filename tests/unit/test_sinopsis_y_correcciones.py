import pandas as pd
from pydantic import TypeAdapter

from app.engine import model as m
from app.engine.comparar import sugerir_correcciones
from app.engine.pipeline import aplicar

tarjeta = TypeAdapter(m.Tarjeta).validate_python
CLASIFICAR = {"id": "s", "tipo": "clasificar_sinopsis", "programa": "prog", "capitulo": "cap", "sinopsis": "sin",
              "destino_programa": "arg_prog", "destino_capitulo": "arg_cap"}


def clasificar(prog, cap, sin):
    r = aplicar(pd.DataFrame({"prog": prog, "cap": cap, "sin": sin}), [tarjeta(CLASIFICAR)])
    assert r.informes[0].error is None
    return r.tabla, r.informes[0].avisos


def test_misma_sinopsis_en_todos_los_capitulos_es_de_programa():
    tabla, avisos = clasificar(["Memory Lane"] * 3, ["A", "B", "C"], ["Serie de recitales"] * 3)
    assert tabla["arg_prog"].tolist() == ["Serie de recitales"] * 3
    assert tabla["arg_cap"].isna().all() and avisos == []


def test_sinopsis_distintas_por_capitulo_son_de_capitulo():
    tabla, _ = clasificar(["Six Strings"] * 3, ["A", "B", "C"], ["a", "b", "c"])
    assert tabla["arg_cap"].tolist() == ["a", "b", "c"] and tabla["arg_prog"].isna().all()


def test_programa_de_un_solo_capitulo_es_de_programa():
    tabla, _ = clasificar(["Concierto", "Concierto"], [None, None], ["recital", "recital"])
    assert tabla["arg_prog"].tolist() == ["recital", "recital"]


def test_todos_iguales_salvo_uno_avisa_la_fila():
    caps = [f"c{i}" for i in range(10)]
    sinopsis = ["general"] * 9 + ["especial"]
    tabla, avisos = clasificar(["Show"] * 10, caps, sinopsis)
    assert tabla["arg_prog"].tolist() == sinopsis  # no decide sola: lo deja y avisa
    assert avisos == ["Show: sinopsis distinta en fila(s) 10"]


def test_correcciones_solo_celda_entera():
    t = tarjeta({"id": "c", "tipo": "correcciones", "columnas": ["a"], "mapa": {"Ac/dc - Live": "AC/DC - Live"}})
    r = aplicar(pd.DataFrame({"a": ["Ac/dc - Live", "Ac/dc - Live 2"]}), [t])
    assert r.tabla["a"].tolist() == ["AC/DC - Live", "Ac/dc - Live 2"]


def test_sugerir_correcciones_descarta_las_contradictorias():
    salida = pd.DataFrame({"a": ["Ac/dc", "Ep 1", "Ep 1", "ok"], "b": [1, 2, 3, 4]})
    esperado = pd.DataFrame({"a": ["AC/DC", "Ep. 1", "Episodio 1", "ok"], "b": [1, 2, 3, 5]})
    assert sugerir_correcciones(salida, esperado, ["a", "b"]) == {"a": {"Ac/dc": "AC/DC"}}
