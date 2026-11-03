from tests.unit.test_api import excel
from tests.unit.test_conversaciones import _ana
from tests.unit.test_semana import SEPARAR, _grilla


def _canal(cliente):
    receta = {"id": "canal", "nombre": "Canal", "entrada": {"tipo": "excel"}, "tarjetas": [SEPARAR], "salida": {"columnas": []}}
    cliente.put("/api/senales/canal", json=receta)
    grilla = excel(_grilla(["Memory Lane - OutKast", "Ruta Sonora - Live"]))
    return cliente.post("/api/senales/canal/abierta", files={"archivo": ("g.xlsx", grilla)}).json()


def test_cada_carga_junta_lo_que_se_corrigio_acepto_y_confirmo(cliente):
    semana = _canal(cliente)
    ana = _ana(cliente)
    ana.post("/api/senales/canal/abierta/celda", json={"fila": 0, "columna": "Capitulo", "valor": "Outkast"})
    ana.post("/api/senales/canal/abierta/aceptar", json={"hashes": [semana["revisar"][1]["hash"]]})
    cliente.post("/api/senales/canal/abierta/confirmar")

    (carga,) = cliente.get("/api/historial").json()
    assert carga["senal_id"] == "canal" and carga["desde"] == "2026-11-02" and carga["confirmada"]
    assert carga["cuenta"] == {"corregida": 1, "aceptada": 1, "confirmada": 1} and set(carga["usuarios"]) == {"ana", "admin"}
    assert ana.get("/api/historial").json()[0]["cuenta"] == {"corregida": 1, "aceptada": 1}  # solo lo suyo

    detalle = cliente.get(f"/api/historial/canal?carga={carga['carga']}").json()
    corregida = next(d for d in detalle if d["tipo"] == "corregida")
    assert (corregida["usuario"], corregida["columna"], corregida["antes"], corregida["despues"]) == (
        "ana", "Capitulo", "OutKast", "Outkast")
    assert len(ana.get(f"/api/historial/canal?carga={carga['carga']}").json()) == 2


def test_las_reglas_y_la_base_tambien_quedan(cliente):
    _canal(cliente)
    cliente.post("/api/senales/canal/abierta/confirmar")
    cliente.put("/api/senales/canal", json={"id": "canal", "nombre": "Canal", "entrada": {"tipo": "excel"}, "tarjetas": [],
                                            "salida": {"columnas": []}})
    cliente.post("/api/senales/canal/pautas/editar-varias", json={"filtro": {"Programa": "Memory Lane"},
                                                                  "columna": "Capitulo", "valor": "Outkast"})
    cuenta = cliente.get("/api/historial").json()[0]["cuenta"]
    assert cuenta["reglas"] == 1 and cuenta["base"] == 1
