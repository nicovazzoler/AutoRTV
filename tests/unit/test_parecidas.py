from app import pautas
from app.parecidas import buscar
from tests.unit.test_api import _con_asistente, excel
from tests.unit.test_semana import SEPARAR, _grilla

FILAS = [("a", {"TIT": "Dr Dolittle 2", "P": "Dr"}), ("b", {"TIT": "Dr Dolittle", "P": "Dr"}),
         ("c", {"TIT": "GHOST WATCHER", "P": "G"}), ("d", {"TIT": "Dr Dolittle", "P": "Dr"})]


def test_mismo_valor_mismo_trozo_y_mayusculas():
    por_trozo = buscar(FILAS, "TIT", "Dr Dolittle", "Dr. Dolittle", "P", "b")
    assert [(p.clave, p.despues, p.motivo) for p in por_trozo] == [
        ("a", "Dr. Dolittle 2", "mismo_trozo"), ("d", "Dr. Dolittle", "mismo_valor")]
    por_mayusculas = buscar(FILAS, "TIT", "ANNIE HALL", "Annie hall", "P", "x")
    assert [(p.clave, p.despues) for p in por_mayusculas] == [("c", "Ghost watcher")]
    assert buscar(FILAS, "OTRA", "x", "y", "P", "b") == []


def _canal(cliente):
    receta = {"id": "canal", "nombre": "Canal", "entrada": {"tipo": "excel"}, "tarjetas": [SEPARAR],
              "salida": {"columnas": []}}
    cliente.put("/api/senales/canal", json=receta)
    grilla = excel(_grilla(["Memory Lane - OutKast", "Memory Lane - Prince", "Ruta Sonora - Live"]))
    return cliente.post("/api/senales/canal/abierta", files={"archivo": ("g.xlsx", grilla)}).json()


def test_en_la_semana_el_agente_marca_cuales_aplican_y_se_arreglan_juntas(cliente, monkeypatch):
    _canal(cliente)
    proveedor = _con_asistente(monkeypatch, [{"decisiones": [{"clave": "1", "aplica": False, "porque": "Otro programa"}]}])
    cliente.post("/api/senales/canal/abierta/celda", json={"fila": 0, "columna": "Programa", "valor": "Memory lane"})
    r = cliente.post("/api/senales/canal/abierta/parecidas",
                     json={"fila": 0, "columna": "Programa", "antes": "Memory Lane", "despues": "Memory lane"}).json()
    assert [(p["clave"], p["aplica"], p["porque"]) for p in r] == [("1", False, "Otro programa")]
    assert "Memory Lane" in proveedor.pedidos[-1][0]["content"]
    assert cliente.post("/api/senales/canal/abierta/aplicar",
                        json=[{"fila": 1, "columna": "Programa", "valor": "Memory lane"}]).json() == {"aplicadas": 1}
    grilla = cliente.get("/api/senales/canal/abierta/grilla").json()
    i = grilla["columnas"].index("Programa")
    assert [f[i] for f in grilla["filas"]][:2] == ["Memory lane", "Memory lane"]


def test_en_la_base_sin_agente_van_todas_marcadas(cliente):
    _canal(cliente)
    cliente.post("/api/senales/canal/abierta/confirmar")
    base = pautas.base("canal")
    hashes = {p["salida"]["Capitulo"]: h for h, p in base.items()}
    r = cliente.post(f"/api/senales/canal/pautas/{hashes['OutKast']}/parecidas",
                     json={"columna": "Programa", "antes": "Memory Lane", "despues": "Memory lane"}).json()
    assert [(p["clave"], p["aplica"]) for p in r] == [(hashes["Prince"], True)]
    assert cliente.post("/api/senales/canal/pautas/aplicar",
                        json=[{"hash": hashes["Prince"], "columna": "Programa", "valor": "Memory lane"}]).json() == {"aplicadas": 1}
    assert pautas.base("canal")[hashes["Prince"]]["salida"]["Programa"] == "Memory lane"
