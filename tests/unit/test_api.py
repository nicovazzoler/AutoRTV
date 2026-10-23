import datetime as dt
import io
import json

import pandas as pd
from fastapi.testclient import TestClient

from app.main import app

cliente = TestClient(app)


def test_health():
    assert cliente.get("/health").json() == {"ok": True}


def test_preview_devuelve_tabla_e_informe():
    buf = io.BytesIO()
    pd.DataFrame({"Fecha": [dt.datetime(2026, 10, 23)] * 2, "Hora": [dt.time(0), dt.time(1, 30)],
                  "Titulo": ["Joseph PrinceGrace", "Praise"]}).to_excel(buf, index=False)
    senal = (json.loads(open("ejemplos/sintetica.json", encoding="utf-8").read()))
    r = cliente.post("/api/preview", files={"archivo": ("g.xlsx", buf.getvalue())}, data={"senal": json.dumps(senal)})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["total_filas"] == 2
    assert cuerpo["filas"][0]["TIT ING"] == "Joseph Prince" and cuerpo["filas"][0]["DUR"] == 90
    assert cuerpo["filas"][0]["HORA"] == "00:00:00" and cuerpo["filas"][1]["DIA"] == "VIERNES"
    assert all(t["error"] is None for t in cuerpo["tarjetas"])


def test_preview_receta_invalida():
    r = cliente.post("/api/preview", files={"archivo": ("g.xlsx", b"")}, data={"senal": "{}"})
    assert r.status_code == 422
