import datetime as dt
import io

import pandas as pd
from openpyxl import Workbook

from app import almacen
from app.agent import diagnostico
from tests.unit.test_api import excel
from tests.unit.test_banco import _esperar

PROGRAMAS = [("Noticias del día", 60), ("Cocina con Ana", 30), ("Cine: El Viaje", 120), ("Deportes en vivo", 90)]


def _grilla(corrimiento: int = 0) -> list[list]:
    filas = [["Fecha", "Hora", "Programa"]]
    for dia in range(2, 5):
        inicio = dt.datetime(2026, 11, dia, 6) + dt.timedelta(hours=corrimiento)
        for nombre, minutos in PROGRAMAS * 3:
            filas.append([dt.datetime.combine(inicio.date(), dt.time()), inicio.time(), nombre])
            inicio += dt.timedelta(minutes=minutos)
    return filas


def _libro(hojas: dict[str, list[list]]) -> bytes:
    wb = Workbook()
    for i, (nombre, filas) in enumerate(hojas.items()):
        ws = wb.active if i == 0 else wb.create_sheet()
        ws.title = nombre
        for fila in filas:
            ws.append(fila)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _ejemplo(con_sinopsis: bool = False) -> pd.DataFrame:
    t = pd.DataFrame(_grilla()[1:], columns=["FECHA", "HORA", "PROGRAMA"])
    if con_sinopsis:
        t["SINOPSIS"] = [f"Sinopsis completa de {p}." for p in t["PROGRAMA"]]
    return pd.read_excel(io.BytesIO(excel(t)), dtype=object)


DATOS = [["Título", "Sinopsis"]] + [[p.upper(), f"Sinopsis completa de {p}."] for p, _ in PROGRAMAS]


def test_una_grilla_que_ya_se_lee_bien_no_necesita_nada():
    d = diagnostico.diagnosticar(_libro({"Grilla": _grilla()}), _ejemplo())
    assert (d["principal"], d["necesita"], d["hallazgos"]) == ("lee_bien", "nada", [])


def test_dos_grillas_en_dos_zonas_y_una_hoja_de_datos_piden_opciones_del_lector():
    contenido = _libro({"Grilla ARG": _grilla(), "Grilla MEX": _grilla(-3), "Datos": DATOS})
    d = diagnostico.diagnosticar(contenido, _ejemplo(con_sinopsis=True))
    assert d["necesita"] == "opcion"
    tipos = {h["tipo"]: h for h in d["hallazgos"]}
    assert tipos["elegir_hoja"]["hoja"] == "Grilla ARG"
    assert (tipos["hoja_de_datos"]["hoja"], tipos["hoja_de_datos"]["columna"]) == ("Datos", "SINOPSIS")


def test_un_ejemplo_corrido_unas_horas_es_cosa_de_las_reglas():
    d = diagnostico.diagnosticar(_libro({"Grilla": _grilla(3)}), _ejemplo())
    (zona,) = d["hallazgos"]
    assert (d["necesita"], zona["tipo"], zona["horas"]) == ("reglas", "zona_horaria", 3)


def test_una_grilla_sin_horario_que_ninguna_lectura_entiende_necesita_un_lector_en_codigo():
    raro = [["PROGRAMACIÓN"], ["Noticias del día — a la mañana"], ["Cocina con Ana — al mediodía"], ["Cine — a la noche"]]
    d = diagnostico.diagnosticar(_libro({"Hoja": raro}), _ejemplo())
    assert (d["principal"], d["necesita"]) == ("no_lee", "codigo")


def test_un_dato_del_ejemplo_que_no_esta_en_el_archivo_sale_de_la_base():
    d = diagnostico.diagnosticar(_libro({"Grilla": _grilla()}), _ejemplo(con_sinopsis=True))
    (falta,) = d["hallazgos"]
    assert (d["necesita"], falta["tipo"], falta["columna"]) == ("base", "falta_en_el_archivo", "SINOPSIS")


def test_el_diagnostico_corre_en_el_banco_sin_agente_y_sin_gastar(cliente):
    receta = {"id": "canal", "nombre": "Canal", "entrada": {"tipo": "excel"}, "tarjetas": [], "salida": {"columnas": []}}
    cliente.put("/api/senales/canal", json=receta)
    contenido = _libro({"Grilla ARG": _grilla(), "Grilla MEX": _grilla(-3), "Datos": DATOS})
    almacen.guardar_ejemplo("canal", "ejemplo-1", contenido, excel(_ejemplo(con_sinopsis=True)))
    r = cliente.post("/api/admin/banco", json={"senales": ["canal"], "pasos": ["diagnostico"]})  # sin API key
    assert r.status_code == 200, r.text
    c = _esperar(cliente, r.json()["id"])
    assert c["estado"] == "terminada" and c["gastado"] == 0
    assert c["resultado"]["senales"][0]["diagnostico"]["necesita"] == "opcion"
    # La señal ya lee una sola hoja (la primera): lo que le falta es cruzar la de datos.
    assert c["resultado"]["resumen"]["diagnostico"] == {"senales": 1, "necesita": {"opcion": 1},
                                                         "principal": {"hoja_de_datos": 1}}
