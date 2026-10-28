import datetime as dt
import io

import pandas as pd
from fastapi.testclient import TestClient

from app import pautas, semanas
from app.api.rutas import senales_parecidas
from app.main import app
from tests.unit.test_api import excel
from tests.unit.test_semana import SEPARAR


def _dias(desde: dt.date, titulos: list[str]) -> bytes:
    """Una grilla con un programa por día, a las 06:00, desde esa fecha."""
    return excel(pd.DataFrame({
        "Fecha": [dt.datetime.combine(desde + dt.timedelta(days=i), dt.time(0)) for i in range(len(titulos))],
        "Hora": [dt.time(6)] * len(titulos),
        "Titulo": titulos,
    }, dtype=object))


def _receta(cliente):
    cliente.put("/api/senales/canal", json={"id": "canal", "nombre": "Canal", "entrada": {"tipo": "excel"},
                                            "tarjetas": [SEPARAR], "salida": {"columnas": []}})


def test_es_version_segun_los_dias_en_comun():
    abierta = {"resumen": {"desde": "2026-11-02", "hasta": "2026-11-08"}}
    assert semanas.es_version("2026-11-02", "2026-11-08", abierta)
    assert semanas.es_version("2026-11-05", "2026-11-11", abierta)  # 4 días en común
    assert not semanas.es_version("2026-11-06", "2026-11-12", abierta)  # 3 días
    assert not semanas.es_version("2026-11-09", "2026-11-15", abierta)
    assert not semanas.es_version("2026-11-02", "2026-11-08", None)
    assert not semanas.es_version(None, None, abierta)


def test_comparar_versiones_emision_por_emision():
    antes = pd.DataFrame({"Fecha": ["02/11/2026", "02/11/2026", "03/11/2026"], "Hora": ["06:00", "07:00", "06:00"],
                          "Programa": ["Memory Lane", "Koko Pop", "Juke Box"], "Dur": [60, 60, 60]})
    ahora = pd.DataFrame({"Fecha": ["02/11/2026", "02/11/2026", "04/11/2026"], "Hora": ["06:00", "07:00", "06:00"],
                          "Programa": ["Memory Lane", "Ruta Sonora", "Juke Box"], "Dur": [60, 60, 30]})
    cambios = semanas.comparar(antes, ahora, "Fecha", "Hora", ["Programa", "Dur"])
    assert cambios == [
        {"fecha": "2026-11-02", "hora": "07:00", "tipo": "cambiado", "campos": ["Programa"],
         "antes": {"Programa": "Koko Pop"}, "ahora": {"Programa": "Ruta Sonora"}},
        {"fecha": "2026-11-03", "hora": "06:00", "tipo": "sacado",
         "antes": {"Programa": "Juke Box", "Dur": "60"}},
        {"fecha": "2026-11-04", "hora": "06:00", "tipo": "agregado",
         "ahora": {"Programa": "Juke Box", "Dur": "30"}},
    ]
    assert semanas.comparar(antes, antes, "Fecha", "Hora", ["Programa"]) == []


def test_otra_version_de_la_misma_semana_muestra_que_cambio(cliente):
    _receta(cliente)
    lunes = dt.date(2026, 11, 2)
    titulos = ["Memory Lane - Outkast", "Koko Pop - Ep 1", "Juke Box - Ep 2", "Memory Lane - Prince", "Koko Pop - Ep 2"]
    r = cliente.post("/api/senales/canal/abierta", files={"archivo": ("v1.xlsx", _dias(lunes, titulos))}).json()
    assert r["semana"]["version"] == 1 and r["cambios"] is None
    cliente.post("/api/senales/canal/abierta/confirmar")

    corregida = titulos[:2] + ["Ruta Sonora - Live"] + titulos[3:]
    r = cliente.post("/api/senales/canal/abierta", files={"archivo": ("v2.xlsx", _dias(lunes, corregida))}).json()
    assert r["semana"]["version"] == 2 and r["semana"]["anterior_nombre"] == "v1.xlsx"
    assert r["semana"]["confirmada_por"] is None
    # Lo confirmado en la v1 ya está en la base: solo el programa que cambió queda para revisar.
    assert r["resumen"]["revisar"] == 1 and r["resumen"]["cambios"] == 1
    (cambio,) = r["cambios"]
    assert cambio["tipo"] == "cambiado" and cambio["fecha"] == "2026-11-04"
    assert cambio["antes"]["Programa"] == "Juke Box" and cambio["ahora"]["Programa"] == "Ruta Sonora"

    # La semana siguiente ya no es una versión: vuelve a la v1, sin comparar.
    r = cliente.post("/api/senales/canal/abierta", files={"archivo": ("otra.xlsx", _dias(lunes + dt.timedelta(7), titulos))}).json()
    assert r["semana"]["version"] == 1 and r["cambios"] is None


def test_exportar_entre_fechas_y_horas(cliente):
    _receta(cliente)
    titulos = ["Memory Lane - A", "Koko Pop - B", "Juke Box - C", "Ruta Sonora - D"]
    cliente.post("/api/senales/canal/abierta", files={"archivo": ("g.xlsx", _dias(dt.date(2026, 11, 2), titulos))})

    def programas(**params):
        r = cliente.get("/api/senales/canal/abierta/export", params={"formato": "xlsx", **params})
        assert r.status_code == 200, r.text
        return pd.read_excel(io.BytesIO(r.content))["Programa"].tolist()

    assert programas(desde="2026-11-03", hasta="2026-11-04") == ["Koko Pop", "Juke Box"]
    assert programas(desde="2026-11-04T06:00") == ["Juke Box", "Ruta Sonora"]
    assert programas(hasta="2026-11-02T05:59") == []
    assert cliente.get("/api/senales/canal/abierta/export", params={"desde": "ayer"}).status_code == 422


def test_parecidas_por_comienzo_o_contenido():
    senales = [{"id": "concert", "nombre": "Concert Channel EPG OCTUBRE 2026 (28-09)"},
               {"id": "canal-13", "nombre": "Canal 13"}, {"id": "tv", "nombre": "TV"}]
    assert [s["id"] for s in senales_parecidas("Concert Chanel", senales)] == ["concert"]
    assert [s["id"] for s in senales_parecidas("Concert Channel", senales)] == ["concert"]
    assert senales_parecidas("Canal 9", senales) == []
    assert senales_parecidas("TV Pública", senales) == []  # "tv" es muy corto para contar


def test_parecidas_en_vivo(cliente):
    _receta(cliente)
    assert cliente.get("/api/senales-parecidas", params={"nombre": "canal!"}).json() == [{"id": "canal", "nombre": "Canal"}]
    assert cliente.get("/api/senales-parecidas", params={"nombre": " "}).json() == []


def test_borrar_senal_solo_admin_y_con_todo(cliente):
    from app import auth

    _receta(cliente)
    cliente.post("/api/senales/canal/abierta", files={"archivo": ("g.xlsx", _dias(dt.date(2026, 11, 2), ["A - 1"]))})
    cliente.post("/api/senales/canal/abierta/confirmar")
    auth.crear_usuario("ana", "clave-de-ana")
    ana = TestClient(app)
    ana.post("/api/login", json={"usuario": "ana", "clave": "clave-de-ana"})
    assert ana.delete("/api/senales/canal").status_code == 403

    assert cliente.delete("/api/senales/canal").status_code == 200
    assert cliente.get("/api/senales/canal").status_code == 404
    assert pautas.base("canal") == {} and semanas.leer("canal") is None
    assert cliente.delete("/api/senales/canal").status_code == 404


def test_horas_con_am_pm_no_son_contenido():
    crudo = pd.DataFrame({"Programa": ["A", "B", "C"], "Inicio": ["8:00", "9:00", "10:00"], "Turno": ["AM", "AM", "PM"]})
    assert "Turno" in pautas.columnas_de_horario(crudo)
    salida = pd.DataFrame({"TIT ING": ["A", "B", "C"], "Horario": ["08:00 PM", "09:00 PM", "10:00 PM"],
                           "AM/PM": ["PM", "PM", "PM"], "Sinopsis": ["1:30 de rock", "Rock", "Jazz"]})
    assert pautas.columnas_de_contenido(salida) == ["TIT ING", "Sinopsis"]


def test_limpiar_la_base_junta_las_pautas_que_separaba_la_hora(cliente):
    _receta(cliente)
    viejas = {f"h{i}": {"crudo": {"Programa": "Memory Lane", "Turno": turno},
                        "salida": {"TIT ING": "Memory Lane", "AM/PM": turno}} for i, turno in enumerate(["AM", "PM"])}
    pautas.guardar("canal", viejas, "revisada", "admin")
    pautas.guardar("canal", {"h1": {**viejas["h1"], "salida": {"TIT ING": "Memory Lane (editada)", "AM/PM": "PM"}}},
                   "editada", "admin", pisar=True)
    r = cliente.post("/api/senales/canal/pautas/limpiar").json()
    assert r == {"antes": 2, "despues": 1, "columnas": ["AM/PM", "Turno"]}
    (pauta,) = pautas.base("canal").values()
    assert pauta == {"salida": {"TIT ING": "Memory Lane (editada)"}, "estado": "editada"}


def test_ejemplo_pegado_en_una_senal_de_excel(cliente):
    _receta(cliente)
    texto = "".join(f"LUNES 2/11/2026\n0{6 + i}:00 Memory Lane - Ep {i}\n" for i in range(3)).encode()
    esperado = excel(pd.DataFrame({"Programa": ["Memory Lane"] * 3, "Capitulo": [f"Ep {i}" for i in range(3)]}))
    r = cliente.post("/api/senales/canal/ejemplos", files={"entrada": ("g.txt", texto), "esperado": ("e.xlsx", esperado)},
                     data={"nombre": "ejemplo-html"})
    assert r.status_code == 200, r.text
    (ev,) = cliente.post("/api/senales/canal/ejemplos/evaluar", json=cliente.get("/api/senales/canal").json()).json()
    assert "error" not in ev, ev


def test_crear_senal_con_la_semana_en_curso_la_deja_abierta(cliente):
    hoy = dt.date.today()
    grilla = _dias(hoy, ["Memory Lane - A", "Koko Pop - B"])
    hecho = excel(pd.DataFrame({"Fecha": [dt.datetime.combine(hoy, dt.time(0))] * 2, "Hora": [dt.time(6)] * 2,
                                "Programa": ["Memory Lane", "Koko Pop"]}, dtype=object))
    r = cliente.post("/api/senales/crear", files={"grilla_cruda": ("g.xlsx", grilla), "ejemplo": ("e.xlsx", hecho)},
                     data={"nombre": "Canal Hoy"}).json()
    assert r["semana_abierta"] and semanas.leer("canal-hoy")["nombre"] == "g.xlsx"

    vieja = cliente.post("/api/senales/crear", data={"nombre": "Canal Viejo"},
                         files={"grilla_cruda": ("g.xlsx", grilla), "ejemplo": ("e.xlsx", excel(pd.DataFrame(
                             {"Fecha": [dt.datetime(2020, 1, 1)], "Programa": ["X"]}, dtype=object)))}).json()
    assert not vieja["semana_abierta"] and semanas.leer("canal-viejo") is None
