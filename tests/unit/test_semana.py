import datetime as dt

import pandas as pd

from app import semana
from app.engine import model as m
from app.validate.grilla import Aviso
from tests.unit.test_api import excel

SEPARAR = {"id": "s1", "tipo": "separar", "columna": "Titulo", "modo": "separador", "valor": " - ",
           "destinos": ["Programa", "Capitulo"]}


def _grilla(titulos: list[str]) -> pd.DataFrame:
    return pd.DataFrame({
        "Fecha": [dt.datetime(2026, 11, 2)] * len(titulos),
        "Hora": [dt.time(6 + i) for i in range(len(titulos))],
        "Titulo": titulos,
    }, dtype=object)


def test_clasificar_separa_conocidas_nuevas_listas_y_para_revisar():
    salida = pd.DataFrame({"Programa": ["Memory Lane", "memory lane!", "Ruta Sonora", None, "Koko Pop"]})
    estados = ["conocida", "nueva", "nueva", "nueva", "nueva"]
    avisos = [Aviso("error", "catalogo", "Año: no es un año", 5, "Año"), Aviso("info", "dia_parcial", "x", 5)]
    grupos = semana.clasificar(salida, estados, avisos, [], ["Memory Lane", "Koko Pop"], "Programa")
    assert [g["grupo"] for g in grupos] == ["base", "nueva_lista", "revisar", "revisar", "revisar"]
    assert grupos[2]["motivos"] == ["Programa nuevo: Ruta Sonora"]
    assert grupos[3]["motivos"] == ["Programa vacío"]
    assert grupos[4]["motivos"] == ["Año: no es un año"]  # la nota informativa no frena


def test_una_regla_con_error_manda_a_revisar_todas_las_nuevas():
    salida = pd.DataFrame({"Programa": ["Memory Lane", "Memory Lane"]})
    informe = type("Informe", (), {"error": "No existe la columna: X"})()
    grupos = semana.clasificar(salida, ["conocida", "nueva"], [], [informe], ["Memory Lane"], "Programa")
    assert grupos[0]["grupo"] == "base"
    assert grupos[1] == {"grupo": "revisar", "motivos": ["Regla con error: No existe la columna: X"]}


def test_agrupar_junta_por_pauta():
    grupos = [{"grupo": "revisar", "motivos": ["Programa nuevo: A"]}, {"grupo": "base", "motivos": []},
              {"grupo": "revisar", "motivos": ["Programa nuevo: A", "Hueco de 5 min"]}]
    assert semana.agrupar(grupos, ["h1", "h2", "h1"], "revisar") == [
        {"hash": "h1", "filas": [0, 2], "motivos": ["Programa nuevo: A", "Hueco de 5 min"]}]


def test_columna_de_programa_por_nombre_o_catalogo():
    v = m.Validaciones()
    assert semana.columna_programa(["N", "TIT ING", "Tit orig"], v) == "TIT ING"
    assert semana.columna_programa(["N", "Tit orig"], v) == "Tit orig"
    assert semana.columna_programa(["N", "Show"], m.Validaciones(programa="Show")) == "Show"
    assert semana.columna_programa(["N"], v) is None


def _semana(cliente, titulos):
    tabla_id = cliente.post("/api/tablas", files={"archivo": ("s.xlsx", excel(_grilla(titulos)))}).json()["tabla_id"]
    receta = cliente.get("/api/senales/canal").json()
    return {"tabla_id": tabla_id, "senal": receta}


def test_semana_por_api(cliente):
    receta = {"id": "canal", "nombre": "Canal", "entrada": {"tipo": "excel"}, "tarjetas": [SEPARAR],
              "salida": {"columnas": []}}
    assert cliente.put("/api/senales/canal", json=receta).status_code == 200
    primera = _semana(cliente, ["Memory Lane - Outkast", "Koko Pop - Ep 1"])
    assert cliente.post("/api/senales/canal/semana/confirmar", json=primera).json() == {"guardadas": 2}

    # Capítulo nuevo de un programa conocido entra solo; el programa nuevo (dos veces) se revisa una vez.
    pedido = _semana(cliente, ["Memory Lane - Outkast", "Memory Lane - Prince", "Ruta Sonora - Live", "Ruta Sonora - Live"])
    r = cliente.post("/api/semana", json=pedido).json()
    assert r["resumen"] == {"filas": 4, "base": 1, "nueva_lista": 1, "revisar": 2, "pautas_revisar": 1}
    assert r["lectura"] == {"filas": 4, "columnas": ["Fecha", "Hora", "Titulo"]}
    assert r["revisar"][0]["motivos"] == ["Programa nuevo: Ruta Sonora"] and r["revisar"][0]["veces"] == 2
    assert r["revisar"][0]["salida"]["Capitulo"] == "Live"
    assert r["nuevas"][0]["salida"]["Capitulo"] == "Prince"
    preview = cliente.post("/api/preview", json=pedido).json()
    assert [g["grupo"] for g in preview["grupos"]] == ["base", "nueva_lista", "revisar", "revisar"]

    # "Está bien" sobre la pauta a revisar: queda en la base y la semana ya no la pide.
    aceptar = {**pedido, "hashes": [r["revisar"][0]["hash"]]}
    assert cliente.post("/api/senales/canal/pautas/aceptar", json=aceptar).json() == {"aceptadas": 1}
    r = cliente.post("/api/semana", json=pedido).json()
    assert r["resumen"]["revisar"] == 0 and r["resumen"]["nueva_lista"] == 1


def test_titulos_conocidos_salen_de_la_base(cliente):
    por_titulos = {**SEPARAR, "modo": "titulos_conocidos", "valor": ""}
    receta = {"id": "canal", "nombre": "Canal", "entrada": {"tipo": "excel"}, "tarjetas": [SEPARAR],
              "salida": {"columnas": []}}
    cliente.put("/api/senales/canal", json=receta)
    cliente.post("/api/senales/canal/semana/confirmar", json=_semana(cliente, ["Memory Lane - Outkast"]))
    cliente.put("/api/senales/canal", json={**receta, "tarjetas": [por_titulos]})
    preview = cliente.post("/api/preview", json=_semana(cliente, ["Memory Lane Prince"])).json()
    fila = dict(zip(preview["columnas"], preview["filas"][0]))
    assert (fila["Programa"], fila["Capitulo"]) == ("Memory Lane", "Prince")


def test_base_filtrada_por_columna_y_edicion_de_varias(cliente):
    receta = {"id": "canal", "nombre": "Canal", "entrada": {"tipo": "excel"}, "tarjetas": [SEPARAR],
              "salida": {"columnas": []}}
    cliente.put("/api/senales/canal", json=receta)
    semana_ = _semana(cliente, ["Memory Lane - Outkast", "Memory Lane - Prince", "Koko Pop - Ep 1"])
    cliente.post("/api/senales/canal/semana/confirmar", json=semana_)

    assert cliente.get("/api/senales/canal/pautas/valores", params={"columna": "Programa"}).json() == [
        {"valor": "Memory Lane", "pautas": 2}, {"valor": "Koko Pop", "pautas": 1}]
    filtradas = cliente.get("/api/senales/canal/pautas", params={"filtro": "Programa=memory lane"}).json()
    assert filtradas["total"] == 2
    assert cliente.get("/api/senales/canal/pautas", params={"filtro": "sin-igual"}).status_code == 422

    r = cliente.post("/api/senales/canal/pautas/editar-varias",
                     json={"filtro": {"Programa": "Memory Lane"}, "columna": "Genero", "valor": "Música"})
    assert r.json() == {"editadas": 2}
    lista = cliente.get("/api/senales/canal/pautas", params={"estado": "editada"}).json()
    assert {p["salida"]["Genero"] for p in lista["pautas"]} == {"Música"}
    # Sin elegir ni filtrar no se cambia toda la base de golpe.
    assert cliente.post("/api/senales/canal/pautas/editar-varias",
                        json={"columna": "Genero", "valor": "x"}).status_code == 422

    preview = cliente.post("/api/preview", json=semana_).json()
    genero = preview["columnas"].index("Genero")
    assert [f[genero] for f in preview["filas"]] == ["Música", "Música", None]

    h = filtradas["pautas"][0]["hash"]
    assert cliente.post("/api/senales/canal/pautas/olvidar-varias", json={"hashes": [h]}).json() == {"olvidadas": 1}


def test_historial_y_restaurar(cliente):
    receta = {"id": "canal", "nombre": "Canal", "entrada": {"tipo": "excel"}, "tarjetas": [SEPARAR],
              "salida": {"columnas": []}}
    cliente.put("/api/senales/canal", json=receta)
    cliente.put("/api/senales/canal", json={**receta, "tarjetas": []})

    historial = cliente.get("/api/senales/canal/historial").json()
    assert [h["cambios"] for h in historial][0][0]["tipo"] == "borrada"
    assert historial[1]["cambios"] == []
    r = cliente.post(f"/api/senales/canal/historial/{historial[1]['id']}/restaurar")
    assert r.status_code == 200 and r.json()["tarjetas"][0]["id"] == "s1"
    assert cliente.get("/api/senales/canal").json()["tarjetas"][0]["id"] == "s1"
    assert len(cliente.get("/api/senales/canal/historial").json()) == 3
    assert cliente.post("/api/senales/canal/historial/99999/restaurar").status_code == 404
