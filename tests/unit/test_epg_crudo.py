import datetime as dt
from pathlib import Path

import pandas as pd
import pytest

from app import inputs, pautas
from app.engine import model as m
from app.inputs import epg
from tests.unit.test_api import excel

MUESTRAS = Path(__file__).resolve().parents[2] / "muestras" / "ejemplos"


def _own(imagen: str = "a.jpg") -> bytes:
    """HTML como el de OWN: los datos en atributos del bloque y en hijos con clase."""
    filas = [("2026-10-23 00:00:00", 120, "Something New", "", "Una película."),
             ("2026-10-23 02:00:00", 60, "Family or Fiance", "Grandmama Drama", "Omar y Laterrica."),
             ("2026-10-23 03:00:00", 60, "Family or Fiance", "Living in La La Land", "Shai y Troy."),
             ("2026-10-23 04:00:00", 60, "Home Videos", "Superheroes", "Diez finalistas."),
             ("2026-10-23 05:00:00", 60, "Home Videos", "Dog Park", "Otra vez.")]
    bloques = "".join(
        f'<div class="tve-schedule__timeslot" data-eastern="{e}" data-duration="{d}" data-image-url="{imagen}">'
        f'<span class="tve-schedule__show">{s}</span><span class="tve-schedule__episode">{ep}</span>'
        f'<p class="tve-schedule__description">{desc}</p><span class="tve-schedule__rating">TV-PG</span></div>'
        for e, d, s, ep, desc in filas)
    return f"<html><body><div>{bloques}</div></body></html>".encode()


def _tbn() -> bytes:
    """HTML como el de TBN: inicio y fin en UTC, el título en una celda y el id del programa aparte."""
    filas = "".join(
        f'<tr class="episode-row" data-program-id="{460000 + i}" data-timestamp-utc="2026-10-20T0{i}:00:00"'
        f' data-timestamp-end-utc="2026-10-20T0{i}:30:00" data-synopsis="Sinopsis {i}" data-timestamp="2026-10-19T2{i}:00:00">'
        f'<td class="time-column">9:00 PM</td><td class="title-column">Programa {i}</td></tr>'
        for i in range(6))
    return f"<table>{filas}</table>".encode()


def test_propone_y_arma_el_epg_crudo_de_own():
    tabla = inputs.leer(_own(), m.EntradaHtml(tipo="html"))
    mapa = epg.proponer(tabla)
    assert mapa == {"Fecha": "data-eastern", "Hora": "data-eastern", "Duración": "data-duration", "Título": "show",
                    "Episodio": "episode", "Sinopsis": "description"}
    crudo = epg.armar(tabla, mapa)
    assert list(crudo.columns) == epg.COLUMNAS
    primera = crudo.iloc[1].to_dict()
    assert primera["Fecha"] == dt.datetime(2026, 10, 23) and primera["Hora"] == dt.time(2)
    assert (primera["Duración"], primera["Título"], primera["Episodio"]) == (60, "Family or Fiance", "Grandmama Drama")
    assert "rating: TV-PG" in primera["Extras"] and "data-image-url: a.jpg" in primera["Extras"]


def test_tbn_toma_el_titulo_de_la_celda_y_la_duracion_del_fin():
    tabla = inputs.leer(_tbn(), m.EntradaHtml(tipo="html"))
    mapa = epg.proponer(tabla)
    assert mapa["Título"] == "title-column" and mapa["Fecha"] == "data-timestamp-utc"
    assert mapa["Duración"] == "data-timestamp-end-utc" and mapa["Sinopsis"] == "data-synopsis"
    crudo = epg.armar(tabla, mapa)
    assert crudo.iloc[0]["Duración"] == 30 and crudo.iloc[0]["Título"] == "Programa 0"


def test_el_hash_no_cambia_si_la_pagina_cambia_lo_que_va_a_extras():
    entrada = m.EntradaHtml(tipo="html", epg=epg.proponer(inputs.leer(_own(), m.EntradaHtml(tipo="html"))))
    hashes = lambda html: [pautas.hash_pauta(f) for f in pautas.crudas(inputs.leer(html, entrada))]
    assert hashes(_own("a.jpg")) == hashes(_own("otra-imagen.jpg"))
    assert "Extras" not in pautas.crudas(inputs.leer(_own(), entrada))[0]


def test_una_pagina_que_cambio_su_html_avisa():
    entrada = m.EntradaHtml(tipo="html", epg={"Fecha": "data-eastern", "Hora": "data-eastern", "Título": "programa"})
    with pytest.raises(ValueError, match="ya no trae programa"):
        inputs.leer(_own(), entrada)


def test_senal_web_nueva_arranca_con_epg_crudo(cliente):
    esperado = excel(pd.DataFrame({"TIT ING": ["Something New", "Family or Fiance", "Family or Fiance", "Home Videos", "Home Videos"]}))
    r = cliente.post("/api/senales/crear", data={"nombre": "OWN"}, files={"grilla_cruda": ("own.html", _own()),
                                                                         "ejemplo": ("e.xlsx", esperado)})
    assert r.status_code == 200, r.text
    receta = cliente.get("/api/senales/own").json()
    assert receta["entrada"]["epg"]["Título"] == "show"
    vista = cliente.get("/api/senales/own/epg-crudo").json()
    assert vista["activo"] and "Extras" not in vista["fijas"] and {"columna": "show", "ejemplo": "Something New"} in vista["origen"]


def test_pasar_una_senal_web_vieja_conserva_su_base(cliente):
    receta = {"id": "own", "nombre": "OWN", "entrada": {"tipo": "html"}, "tarjetas": [], "salida": {"columnas": []}}
    cliente.put("/api/senales/own", json=receta)
    cliente.post("/api/senales/own/abierta", files={"archivo": ("own.html", _own())})
    assert cliente.post("/api/senales/own/abierta/confirmar").json()["resumen"]["base"] == 5

    mapa = cliente.get("/api/senales/own/epg-crudo").json()["mapa"]
    assert cliente.post("/api/senales/own/epg-crudo", json={"mapa": {"Fecha": "data-eastern"}}).status_code == 422
    r = cliente.post("/api/senales/own/epg-crudo", json={"mapa": mapa}).json()
    assert r["pautas"] == {"antes": 5, "despues": 5, "columnas": []} and r["reglas_con_error"] == []
    # La misma página otra vez: todo sale de la base, ahora reconocido por el EPG crudo.
    semana = cliente.post("/api/senales/own/abierta", files={"archivo": ("own.html", _own("otra.jpg"))}).json()
    assert semana["resumen"]["base"] == 5 and semana["lectura"]["columnas"] == epg.COLUMNAS


@pytest.mark.skipif(not (MUESTRAS / "outerHTML OWN TV.txt").exists(), reason="las páginas reales no están en el repo")
def test_paginas_reales_de_own_y_tbn():
    for archivo, titulo in [("outerHTML OWN TV.txt", "show"), ("HTML TBN.txt", "title-column")]:
        contenido = (MUESTRAS / archivo).read_bytes()
        tabla = inputs.leer(contenido, inputs.detectar(contenido))
        mapa = epg.proponer(tabla)
        assert mapa["Título"] == titulo
        assert epg.armar(tabla, mapa)[["Fecha", "Hora", "Título"]].notna().all().all()
