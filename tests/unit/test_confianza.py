import datetime as dt

import pandas as pd

from tests.unit.test_api import excel

CRITERIOS = {"id": "criterios", "tipo": "criterios", "columna": "Titulo", "programa": "Programa", "capitulo": "Capitulo"}
RECETA = {"id": "canal", "nombre": "Canal", "entrada": {"tipo": "excel"}, "tarjetas": [CRITERIOS], "salida": {"columnas": []}}


def _semana(cliente, dia: int, titulos: list[str]):
    grilla = excel(pd.DataFrame({"Fecha": [dt.datetime(2026, 11, dia)] * len(titulos),
                                 "Hora": [dt.time(6 + i) for i in range(len(titulos))], "Titulo": titulos}))
    return cliente.post("/api/senales/canal/abierta", files={"archivo": (f"s{dia}.xlsx", grilla)}).json()


def test_los_criterios_ganan_confianza_semana_a_semana_y_la_pierden_si_se_corrigen(cliente):
    cliente.put("/api/senales/canal", json=RECETA)
    assert _semana(cliente, 2, ["Jazz - Uno"])["criterios_en_prueba"]
    cliente.post("/api/senales/canal/abierta/confirmar")
    assert cliente.get("/api/senales/canal/reglas/confianza").json()["semanas"] == {"criterios": 1}
    _semana(cliente, 9, ["Jazz - Dos"])
    cliente.post("/api/senales/canal/abierta/confirmar")
    assert cliente.get("/api/senales/canal/abierta").json()["criterios_en_prueba"] is False  # 2 semanas: ya es confiable
    _semana(cliente, 16, ["Jazz - Tres"])
    cliente.post("/api/senales/canal/abierta/celda", json={"fila": 0, "columna": "Capitulo", "valor": "Tres (en vivo)"})
    cliente.post("/api/senales/canal/abierta/confirmar")
    assert cliente.get("/api/senales/canal/reglas/confianza").json()["semanas"] == {"criterios": 0}


def test_una_correccion_repetida_propone_una_regla_y_se_puede_dejar(cliente):
    cliente.put("/api/senales/canal", json=RECETA)
    _semana(cliente, 2, ["JAZZ - Uno", "JAZZ - Dos", "JAZZ - Tres"])
    for fila in range(3):
        cliente.post("/api/senales/canal/abierta/celda", json={"fila": fila, "columna": "Programa", "valor": "Jazz Club"})
    r = cliente.post("/api/senales/canal/abierta/confirmar").json()
    assert r["propuestas_reglas"] == 1
    (p,) = cliente.get("/api/senales/canal/reglas/propuestas").json()
    assert (p["tipo"], p["columna"], p["antes"], p["despues"], p["veces"]) == ("crear", "Programa", "Jazz", "Jazz Club", 3)
    assert "3 veces" in p["pedido"]
    cliente.post("/api/senales/canal/reglas/propuestas/descartar", json={"clave": p["clave"]})
    assert cliente.get("/api/senales/canal/reglas/propuestas").json() == []
