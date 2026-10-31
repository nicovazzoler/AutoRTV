import datetime as dt

import pandas as pd
import pytest

from app import armados
from tests.unit.test_api import _con_asistente, excel

GRILLA = pd.DataFrame({"Fecha": [dt.datetime(2026, 11, 2)] * 2, "Hora": [dt.time(6), dt.time(7)],
                       "Titulo": ["MEMORY LANE - OUTKAST (R)", "Juke Box - Uno"]})
EPG = pd.DataFrame({"FECHA": [dt.datetime(2026, 11, 2)] * 2, "HORA": [dt.time(6), dt.time(7)],
                    "TIT PROG": ["Memory lane", "Juke Box"], "TIT CAP": ["Outkast", "Uno"], "TT": ["(r)", None]})


@pytest.fixture(autouse=True)
def sin_hilo(monkeypatch):
    monkeypatch.setattr(armados, "EN_HILO", False)


def _crear(cliente, nombre="Canal Demo"):
    archivos = {"grilla_cruda": ("g.xlsx", excel(GRILLA)), "ejemplo": ("e.xlsx", excel(EPG))}
    return cliente.post("/api/senales/crear", files=archivos, data={"nombre": nombre})


def test_al_crear_la_senal_el_agente_arma_las_reglas_solo(cliente, monkeypatch):
    _con_asistente(monkeypatch, ["no es JSON"])  # el agente no sirve: quedan los criterios generales, que mejoran
    r = _crear(cliente)
    assert r.status_code == 200 and r.json()["armando_reglas"]
    estado = cliente.get("/api/senales/canal-demo/reglas/armado").json()
    assert estado["estado"] == "aplicado" and estado["despues"] > estado["antes"]
    receta = cliente.get("/api/senales/canal-demo").json()
    assert receta["tarjetas"][0]["tipo"] == "criterios"
    assert cliente.get("/api/asistente/limites").json()["usados_hoy"] == 0  # no gasta el tope de la persona


def test_sin_agente_no_arma_nada(cliente):
    assert _crear(cliente).json()["armando_reglas"] is False
    assert cliente.get("/api/senales/canal-demo/reglas/armado").json() is None
    assert cliente.post("/api/senales/canal-demo/reglas/armar").status_code == 503


def test_un_ejemplo_nuevo_arma_solo_si_la_senal_no_tiene_reglas(cliente, monkeypatch):
    _con_asistente(monkeypatch, ["no es JSON"])
    receta = {"id": "canal", "nombre": "Canal", "entrada": {"tipo": "excel"}, "salida": {"columnas": []}, "tarjetas": []}
    cliente.put("/api/senales/canal", json=receta)
    archivos = {"entrada": ("g.xlsx", excel(GRILLA)), "esperado": ("e.xlsx", excel(EPG))}
    assert cliente.post("/api/senales/canal/ejemplos", data={"nombre": "ej1"}, files=archivos).json()["armando_reglas"]
    assert cliente.post("/api/senales/canal/ejemplos", data={"nombre": "ej2"}, files=archivos).json()["armando_reglas"] is False


def test_el_boton_pide_ejemplos(cliente, monkeypatch):
    _con_asistente(monkeypatch, ["no es JSON"])
    cliente.put("/api/senales/canal", json={"id": "canal", "nombre": "Canal", "entrada": {"tipo": "excel"},
                                            "salida": {"columnas": []}, "tarjetas": []})
    assert cliente.post("/api/senales/canal/reglas/armar").status_code == 422


def test_subir_una_semana_a_una_senal_sin_reglas_las_arma(cliente, monkeypatch):
    _con_asistente(monkeypatch, ["no es JSON"])
    receta = {"id": "canal", "nombre": "Canal", "entrada": {"tipo": "excel"}, "salida": {"columnas": []}, "tarjetas": []}
    cliente.put("/api/senales/canal", json=receta)
    semana = {"archivo": ("g.xlsx", excel(GRILLA))}
    assert cliente.post("/api/senales/canal/abierta", files=semana).json()["armando_reglas"] is False  # sin ejemplos
    archivos = {"entrada": ("g.xlsx", excel(GRILLA)), "esperado": ("e.xlsx", excel(EPG))}
    with monkeypatch.context() as sin_armar:
        sin_armar.setattr(armados, "lanzar", lambda *a: False)
        cliente.post("/api/senales/canal/ejemplos", data={"nombre": "ej1"}, files=archivos)
    assert cliente.post("/api/senales/canal/abierta", files=semana).json()["armando_reglas"]
    assert cliente.get("/api/senales/canal").json()["tarjetas"][0]["tipo"] == "criterios"
