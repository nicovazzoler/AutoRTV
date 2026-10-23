import datetime as dt
import io
import json
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import app

RECETA = json.loads((Path(__file__).resolve().parents[2] / "ejemplos" / "sintetica.json").read_text(encoding="utf-8"))


def excel(df: pd.DataFrame) -> bytes:
    # Con openpyxl directo: pandas guarda las horas como texto y las grillas reales traen horas de Excel.
    wb = Workbook()
    wb.active.append(list(df.columns))
    for fila in df.itertuples(index=False):
        wb.active.append(list(fila))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


GRILLA = excel(pd.DataFrame({"Fecha": [dt.datetime(2026, 10, 23)] * 2, "Hora": [dt.time(0), dt.time(1, 30)],
                             "Titulo": ["Joseph PrinceGrace", "Praise"]}))


def test_health_es_publico():
    assert TestClient(app).get("/health").json() == {"ok": True}


def test_sin_sesion_no_hay_api(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    c = TestClient(app)
    assert c.get("/api/senales").status_code == 401
    assert c.post("/api/login", json={"usuario": "nadie", "clave": "x"}).status_code == 401


def test_clave_mala_y_logout(cliente):
    assert cliente.post("/api/login", json={"usuario": "admin", "clave": "otra-clave"}).status_code == 401
    assert cliente.get("/api/yo").json()["usuario"] == "admin"
    cliente.post("/api/logout")
    assert cliente.get("/api/yo").status_code == 401


def test_usuarios_solo_admin(cliente):
    assert cliente.post("/api/usuarios", json={"usuario": "ana", "clave": "clave-de-ana"}).status_code == 200
    assert cliente.post("/api/usuarios", json={"usuario": "ana", "clave": "clave-de-ana"}).status_code == 422
    ana = TestClient(app)
    ana.post("/api/login", json={"usuario": "ana", "clave": "clave-de-ana"})
    assert ana.get("/api/senales").status_code == 200
    assert ana.get("/api/usuarios").status_code == 403


def test_guardar_receta_con_historial(cliente, tmp_path):
    assert cliente.put("/api/senales/sintetica", json={"id": "sintetica"}).status_code == 422
    assert cliente.put("/api/senales/otra", json=RECETA).status_code == 422
    assert cliente.put("/api/senales/sintetica", json=RECETA).status_code == 200
    cliente.put("/api/senales/sintetica", json=RECETA)
    assert cliente.get("/api/senales").json() == [{"id": "sintetica", "nombre": RECETA["nombre"]}]
    assert cliente.get("/api/senales/sintetica").json()["tarjetas"][1]["modo"] == "min_mayus"
    assert len(list((tmp_path / "senales" / "sintetica" / "historial").iterdir())) == 2


def test_ids_con_ruta_se_rechazan(cliente):
    assert cliente.get("/api/senales/..%2F..%2Fetc").status_code in (404, 422)
    r = cliente.post("/api/senales/sintetica/ejemplos", data={"nombre": "../x"},
                     files={"entrada": ("a.xlsx", GRILLA), "esperado": ("b.xlsx", GRILLA)})
    assert r.status_code == 422


def test_preview_y_export(cliente):
    tabla_id = cliente.post("/api/tablas", files={"archivo": ("g.xlsx", GRILLA)}).json()["tabla_id"]
    r = cliente.post("/api/preview", json={"tabla_id": tabla_id, "senal": RECETA})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    fila = dict(zip(cuerpo["columnas"], cuerpo["filas"][0]))
    assert fila == {"N": 1, "Dia": "VIERNES", "FechaEPG": "23/10/2026", "HoraEPG": "00:00", "Duracion": 90,
                    "Programa": "Joseph Prince", "Capitulo": "Grace"}
    assert all(t["error"] is None for t in cuerpo["tarjetas"])
    # El último programa dura hasta medianoche (1350 min): pasa el máximo de 720.
    assert [(v["regla"], v["fila"]) for v in cuerpo["validaciones"]] == [("duracion_larga", 2)]
    assert cuerpo["columnas_validadas"] == {"fecha": "FechaEPG", "hora": "HoraEPG", "duracion": "Duracion"}

    xlsx = cliente.post("/api/export", json={"tabla_id": tabla_id, "senal": RECETA, "formato": "xlsx"})
    assert xlsx.status_code == 200
    releido = pd.read_excel(io.BytesIO(xlsx.content))
    assert releido["Programa"].tolist() == ["Joseph Prince", "Praise"] and releido["Duracion"].tolist() == [90, 1350]
    csv = cliente.post("/api/export", json={"tabla_id": tabla_id, "senal": RECETA, "formato": "csv"})
    assert csv.content.decode("utf-8-sig").splitlines()[1].startswith("1,VIERNES,23/10/2026,00:00,90")


def test_preview_con_archivo_vencido(cliente):
    assert cliente.post("/api/preview", json={"tabla_id": "no-existe", "senal": RECETA}).status_code == 410


def test_ejemplos_puntuan_la_receta(cliente):
    tabla_id = cliente.post("/api/tablas", files={"archivo": ("g.xlsx", GRILLA)}).json()["tabla_id"]
    xlsx = cliente.post("/api/export", json={"tabla_id": tabla_id, "senal": RECETA}).content
    r = cliente.post("/api/senales/sintetica/ejemplos", data={"nombre": "semana-1"},
                     files={"entrada": ("a.xlsx", GRILLA), "esperado": ("b.xlsx", xlsx)})
    assert r.status_code == 200
    assert cliente.get("/api/senales/sintetica/ejemplos").json() == ["semana-1"]

    (bien,) = cliente.post("/api/senales/sintetica/ejemplos/evaluar", json=RECETA).json()
    assert bien["porcentaje"] == 100 and bien["total_diferencias"] == 0

    sin_separar = {**RECETA, "tarjetas": [t for t in RECETA["tarjetas"] if t["tipo"] != "separar"]}
    (mal,) = cliente.post("/api/senales/sintetica/ejemplos/evaluar", json=sin_separar).json()
    assert mal["porcentaje"] < 100
    assert {d["columna"] for d in mal["diferencias"]} == {"Programa", "Capitulo"}

    cliente.delete("/api/senales/sintetica/ejemplos/semana-1")
    assert cliente.get("/api/senales/sintetica/ejemplos").json() == []


def test_tipos_tarjeta_trae_todos(cliente):
    tipos = cliente.get("/api/tipos-tarjeta").json()
    assert len(tipos["schema"]["discriminator"]["mapping"]) == 15
    assert "numerar" in tipos["sin_condicion"] and "reemplazar" not in tipos["sin_condicion"]


def test_web_se_sirve():
    c = TestClient(app)
    assert "AutoRTV" in c.get("/").text and "form-login" in c.get("/login").text
    assert c.get("/web/app.js").status_code == 200
