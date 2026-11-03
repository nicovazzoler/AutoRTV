from app import arreglos
from app.catalogo import ColumnaCatalogo
from tests.unit.test_api import excel
from tests.unit.test_semana import SEPARAR, _grilla


def test_sugerencias_segun_la_regla_del_catalogo():
    assert arreglos.sugerencia("Estreno 20255", ColumnaCatalogo("Año", "anio", maximo=4)) is None
    assert arreglos.sugerencia("(2024)", ColumnaCatalogo("Año", "anio")) == 2024
    assert arreglos.sugerencia("90 min", ColumnaCatalogo("Duración", "entero", maximo=720)) == 90
    assert arreglos.sugerencia("rep", ColumnaCatalogo("TT", "valores", valores=["(v)", "(r)", "(d)"])) == "(r)"
    assert arreglos.sugerencia("Una sinopsis muy larga para el campo", ColumnaCatalogo("Sin", "texto", maximo=20)) == "Una sinopsis muy"


def test_pasar_la_sinopsis_al_argumento():
    filas = [("0", {"Programa": "Jazz", "SIN": "El ciclo de jazz.", "ARG": None})]
    cambios = arreglos.a_argumento(filas, "SIN", "ARG", "Programa")
    assert [(c.columna, c.despues) for c in cambios] == [("ARG", "El ciclo de jazz."), ("SIN", None)]


def test_completar_una_columna_vacia_desde_la_semana(cliente):
    receta = {"id": "canal", "nombre": "Canal", "entrada": {"tipo": "excel"}, "tarjetas": [SEPARAR], "salida": {"columnas": []}}
    cliente.put("/api/senales/canal", json=receta)
    semana = cliente.post("/api/senales/canal/abierta", files={"archivo": ("g.xlsx", excel(_grilla(["Memory Lane", "Ruta Sonora"])))}).json()
    hashes = [p["hash"] for p in semana["revisar"]]
    r = cliente.post("/api/senales/canal/abierta/arreglo", json={"codigo": "vacia:Capitulo", "hashes": hashes, "valor": "Especial"})
    assert [(c["columna"], c["despues"]) for c in r.json()] == [("Capitulo", "Especial"), ("Capitulo", "Especial")]
    assert cliente.post("/api/senales/canal/abierta/arreglo", json={"codigo": "vacia:Capitulo", "hashes": hashes}).status_code == 422
    assert cliente.post("/api/senales/canal/abierta/arreglo", json={"codigo": "otro", "hashes": hashes}).status_code == 422
