import datetime as dt

import pandas as pd
import pytest

from app import web
from tests.unit.test_api import excel

RECETA = {"id": "web", "nombre": "Web", "entrada": {"tipo": "excel"}, "salida": {"columnas": []}, "tarjetas": []}


def test_semanal_sin_fechas_se_arma_desde_el_lunes_elegido(cliente):
    cliente.put("/api/senales/web", json=RECETA)
    grilla = excel(pd.DataFrame({"Dia": ["Lunes", "Lunes", "Miércoles"], "Hora": [dt.time(6), dt.time(7), dt.time(6)],
                                 "Programa": ["A", "B", "C"]}))
    r = cliente.post("/api/senales/web/abierta", files={"archivo": ("semanal.xlsx", grilla)}).json()
    assert r["aviso_fechas"]["tipo"] == "sin_fechas" and r["lectura_agente"] is None
    r = cliente.post("/api/senales/web/abierta/fechar", json={"lunes": "2026-11-09"}).json()
    assert (r["resumen"]["desde"], r["resumen"]["hasta"]) == ("2026-11-09", "2026-11-11")
    from app import tablas
    tablas.olvidar_cache()  # otra réplica: el lunes elegido queda guardado con la grilla
    assert cliente.get("/api/senales/web/abierta").json()["resumen"]["hasta"] == "2026-11-11"


def test_fechas_viejas_se_corren_a_la_semana_elegida(cliente):
    cliente.put("/api/senales/web", json=RECETA)
    grilla = excel(pd.DataFrame({"Fecha": [dt.datetime(2019, 5, 6), dt.datetime(2019, 5, 8)], "Hora": [dt.time(6)] * 2,
                                 "Programa": ["A", "B"]}))
    r = cliente.post("/api/senales/web/abierta", files={"archivo": ("vieja.xlsx", grilla)}).json()
    assert r["aviso_fechas"]["tipo"] == "viejas" and r["aviso_fechas"]["desde"] == "2019-05-06"
    r = cliente.post("/api/senales/web/abierta/fechar", json={"lunes": "2026-11-09"}).json()
    assert (r["resumen"]["desde"], r["resumen"]["hasta"]) == ("2026-11-09", "2026-11-11")


def test_el_link_no_puede_apuntar_a_la_red_interna():
    for url in ["http://127.0.0.1:8000/", "http://localhost/", "http://169.254.169.254/latest", "ftp://x.com/"]:
        with pytest.raises(web.NoSePudo):
            web.bajar(url)


def test_subir_por_link_guarda_el_link_en_la_senal(cliente, monkeypatch):
    from tests.unit.test_epg_crudo import _own
    html = _own()
    monkeypatch.setattr(web, "bajar", lambda url: html)
    cliente.put("/api/senales/web", json={**RECETA, "entrada": {"tipo": "html"}})
    r = cliente.post("/api/senales/web/abierta/url", json={"url": "https://canal.example/grilla"})
    assert r.status_code == 200, r.text
    assert cliente.get("/api/senales/web").json()["entrada"]["url"] == "https://canal.example/grilla"
