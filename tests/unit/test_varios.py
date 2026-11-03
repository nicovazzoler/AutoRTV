import datetime as dt
import io
import zipfile

import pandas as pd
import pytest

from app import inputs
from app.inputs import varios
from tests.unit.test_api import excel

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _word(cuerpo: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", f"<w:document {W}><w:body>{cuerpo}</w:body></w:document>")
    return buf.getvalue()


def _celda(t: str) -> str:
    return f"<w:tc><w:p><w:r><w:t>{t}</w:t></w:r></w:p></w:tc>"


def _fila(*ts: str) -> str:
    return "<w:tr>" + "".join(_celda(t) for t in ts) + "</w:tr>"


def _parrafo(t: str) -> str:
    return f"<w:p><w:r><w:t>{t}</w:t></w:r></w:p>"


def _dia(fecha: dt.datetime, titulo: str) -> bytes:
    return excel(pd.DataFrame({"Fecha": [fecha, fecha], "Hora": [dt.time(6), dt.time(7)], "Titulo": [titulo, "Noticias"]}))


def test_word_con_tabla_o_con_texto():
    tabla = _word("<w:tbl>" + _fila("Fecha", "Hora", "Programa") + _fila("02/11/2026", "06:00", "Noticias") + "</w:tbl>")
    assert inputs.detectar(tabla).tipo == "word"
    assert inputs.leer(tabla, inputs.detectar(tabla)).to_dict("records") == [
        {"Fecha": "02/11/2026", "Hora": "06:00", "Programa": "Noticias"}]
    texto = _word(_parrafo("LUNES 2/11/2026") + _parrafo("06:00 Noticias") + _parrafo("07:00 Cine"))
    leida = inputs.leer(texto, inputs.detectar(texto))
    assert len(leida) == 2 and "Noticias" in leida.astype(str).to_string()


def test_varios_archivos_se_leen_como_una_semana_en_orden_de_nombre():
    contenido = varios.empaquetar([("martes.xlsx", _dia(dt.datetime(2026, 11, 3), "Martes")),
                                   ("lunes.xlsx", _dia(dt.datetime(2026, 11, 2), "Lunes"))])
    entrada = inputs.detectar(contenido)
    assert entrada.tipo == "varios"
    assert inputs.leer(contenido, entrada)["Titulo"].tolist() == ["Lunes", "Noticias", "Martes", "Noticias"]
    with pytest.raises(ValueError, match="zip"):
        inputs.detectar(b"Rar!\x1a\x07\x00 resto")


def test_subir_varios_archivos_a_la_semana(cliente):
    receta = {"id": "canal", "nombre": "Canal", "entrada": {"tipo": "excel"}, "salida": {"columnas": []}, "tarjetas": []}
    cliente.put("/api/senales/canal", json=receta)
    archivos = [("archivos", ("lunes.xlsx", _dia(dt.datetime(2026, 11, 2), "Lunes"))),
                ("archivos", ("martes.xlsx", _dia(dt.datetime(2026, 11, 3), "Martes")))]
    r = cliente.post("/api/senales/canal/abierta", files=archivos).json()
    assert r["resumen"]["filas"] == 4 and (r["resumen"]["desde"], r["resumen"]["hasta"]) == ("2026-11-02", "2026-11-03")
    assert r["semana"]["nombre"].startswith("2 archivos")
    assert cliente.get("/api/senales/canal").json()["entrada"]["tipo"] == "varios"


def test_crear_una_senal_sin_ejemplo_deja_la_semana_abierta(cliente):
    grilla = _dia(dt.datetime(2026, 11, 2), "Lunes")
    r = cliente.post("/api/senales/crear", files={"grilla_cruda": ("g.xlsx", grilla)}, data={"nombre": "Sin Ejemplo"}).json()
    assert r["sin_ejemplo"] and r["semana_abierta"] and r["ejemplo"] is None and r["pautas"] is None
    assert r["armando_reglas"] is False  # sin ejemplos no hay de dónde armar: pregunta el agente
    assert cliente.get("/api/senales/sin-ejemplo/abierta").json()["resumen"]["filas"] == 2
    assert cliente.get("/api/senales/sin-ejemplo/ejemplos").json() == []
    otra = cliente.post("/api/senales/crear", files={"grilla_cruda": ("g.xlsx", grilla)}, data={"agregar_a": "sin-ejemplo"})
    assert otra.status_code == 422


def test_un_archivo_de_sinopsis_se_cruza_con_la_grilla_por_titulo():
    grilla = excel(pd.DataFrame({"Fecha": [dt.datetime(2026, 11, 2)] * 4, "Hora": [dt.time(h) for h in (6, 7, 8, 9)],
                                 "Titulo": ["Noticias", "Cine Club", "Dibujos", "Noticias"]}))
    sinopsis = excel(pd.DataFrame({"Programa": ["NOTICIAS", "Cine club", "Dibujos", "Otro"],
                                   "Sinopsis": ["El día.", "Películas.", "Para chicos.", "No va."]}))
    contenido = varios.empaquetar([("grilla.xlsx", grilla), ("sinopsis.xlsx", sinopsis)])
    leida = inputs.leer(contenido, inputs.detectar(contenido))
    assert len(leida) == 4 and leida["Sinopsis"].tolist() == ["El día.", "Películas.", "Para chicos.", "El día."]
