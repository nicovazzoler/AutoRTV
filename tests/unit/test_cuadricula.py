import datetime as dt
import io
import re
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import Workbook

from app import inputs
from app.inputs import cuadricula

MUESTRA = Path(__file__).resolve().parents[2] / "muestras" / "ejemplos" / "Nuestra Tele cuadricula (31-10).xls"
LUNES = dt.date(2026, 11, 2)
# Seis franjas de 1 hora desde las 06:00; columnas: lunes, martes, miércoles.
CELDAS = {
    (1, 1): "NOTICIAS", (1, 2): "NOTICIAS", (1, 3): "NOTICIAS",
    (3, 1): "CINE", (3, 3): "DEPORTES",
    (5, 1): "MAGAZINE", (5, 2): "MAGAZINE", (5, 3): "SUELTO",
    (6, 3): "CIERRE",
}
# (fila desde, fila hasta, col desde, col hasta), sin incluir el hasta: noticias lun-mié de 6 a 8,
# cine lun-mar de 8 a 10, deportes mié de 8 a 10, magazine lun-mar de 10 a 12.
COMBINADAS = [(1, 3, 1, 4), (3, 5, 1, 3), (3, 5, 3, 4), (5, 7, 1, 3)]
ESPERADAS = [
    (LUNES, "06:00", 120, "NOTICIAS"), (LUNES, "08:00", 120, "CINE"), (LUNES, "10:00", 120, "MAGAZINE"),
    (LUNES + dt.timedelta(1), "06:00", 120, "NOTICIAS"), (LUNES + dt.timedelta(1), "08:00", 120, "CINE"),
    (LUNES + dt.timedelta(1), "10:00", 120, "MAGAZINE"),
    (LUNES + dt.timedelta(2), "06:00", 120, "NOTICIAS"), (LUNES + dt.timedelta(2), "08:00", 120, "DEPORTES"),
    (LUNES + dt.timedelta(2), "10:00", 60, "SUELTO"), (LUNES + dt.timedelta(2), "11:00", 60, "CIERRE"),
]


def _xlsx(primera_hora: int = 6) -> bytes:
    wb = Workbook()
    h = wb.active
    h.cell(1, 1, "Hora")
    for c in range(3):
        h.cell(1, c + 2, dt.datetime.combine(LUNES + dt.timedelta(c), dt.time()))
    for r in range(6):
        h.cell(r + 2, 1, dt.time((primera_hora + r) % 24))
    for (r, c), v in CELDAS.items():
        h.cell(r + 1, c + 1, v)
    for r0, r1, c0, c1 in COMBINADAS:
        h.merge_cells(start_row=r0 + 1, end_row=r1, start_column=c0 + 1, end_column=c1)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _xls() -> bytes:
    xlwt = pytest.importorskip("xlwt")
    libro = xlwt.Workbook()
    h = libro.add_sheet("Grilla")
    fecha, hora = xlwt.easyxf(num_format_str="DD/MM/YYYY"), xlwt.easyxf(num_format_str="HH:MM")
    for c in range(3):
        h.write(0, c + 1, dt.datetime.combine(LUNES + dt.timedelta(c), dt.time()), fecha)
    for r in range(6):
        h.write(r + 1, 0, dt.time(6 + r), hora)
    combinadas = {(r0, c0): (r1, c1) for r0, r1, c0, c1 in COMBINADAS}
    tapadas = {(r, c) for r0, r1, c0, c1 in COMBINADAS for r in range(r0, r1) for c in range(c0, c1)}
    for (r, c), v in CELDAS.items():
        if (r, c) in combinadas:
            r1, c1 = combinadas[(r, c)]
            h.write_merge(r, r1 - 1, c, c1 - 1, v)
        elif (r, c) not in tapadas:
            h.write(r, c, v)
    buf = io.BytesIO()
    libro.save(buf)
    return buf.getvalue()


def _filas(df) -> list[tuple]:
    return [(f.date(), h.strftime("%H:%M"), d, t) for f, h, d, t in df[["Fecha", "Hora", "Duracion", "Titulo"]].itertuples(index=False)]


@pytest.mark.parametrize("armar", [_xlsx, _xls], ids=["xlsx", "xls"])
def test_lee_bloques_combinados_en_las_dos_direcciones(armar):
    contenido = armar()
    entrada = inputs.detectar(contenido)
    assert entrada.tipo == "excel" and entrada.cuadricula
    assert _filas(inputs.leer(contenido, entrada)) == ESPERADAS


def test_despues_de_medianoche_es_el_dia_siguiente():
    tabla = cuadricula.leer(_xlsx(primera_hora=21))  # franjas de 21:00 a 02:00
    lunes = [f for f in _filas(tabla) if f[3] == "MAGAZINE"]
    assert lunes[0][:2] == (LUNES + dt.timedelta(1), "01:00")  # el magazine del lunes cae el martes a la 1


def test_un_excel_comun_no_es_cuadricula():
    wb = Workbook()
    wb.active.append(["Fecha", "Hora", "Titulo"])
    for i in range(5):
        wb.active.append([dt.datetime(2026, 11, 2), dt.time(6 + i), f"Programa {i}"])
    buf = io.BytesIO()
    wb.save(buf)
    assert not inputs.detectar(buf.getvalue()).cuadricula


def test_una_senal_de_excel_comun_pasa_a_cuadricula_al_subirla(cliente):
    receta = {"id": "canal", "nombre": "Canal", "entrada": {"tipo": "excel"}, "tarjetas": [], "salida": {"columnas": []}}
    cliente.put("/api/senales/canal", json=receta)
    r = cliente.post("/api/senales/canal/abierta", files={"archivo": ("grilla.xls", _xls())})
    assert r.status_code == 200, r.text
    assert cliente.get("/api/senales/canal").json()["entrada"]["cuadricula"] is True
    assert r.json()["resumen"]["filas"] == len(ESPERADAS)


@pytest.mark.skipif(not MUESTRA.exists(), reason="la grilla real no está en el repo")
def test_grilla_real_de_nuestra_tele():
    contenido = MUESTRA.read_bytes()
    tabla = inputs.leer(contenido, inputs.detectar(contenido))
    assert len(tabla) == 214
    assert set(tabla.groupby("Fecha")["Duracion"].sum()) == {1440}


AGAPE = MUESTRA.parent / "AGAPE cuadricula (26-10).xlsx"
AGAPE_EJEMPLO = MUESTRA.parent / "AGAPE ejemplo (26-10).xlsx"


def _por_programa() -> bytes:
    """Título arriba, días como texto, una columna HORA para lunes y martes y otra para el miércoles, horas de 12 h."""
    wb = Workbook()
    h = wb.active
    h.append(["CARTA DE PROGRAMACIÓN DEL 2 DE NOV AL 8 NOV 2026"])
    h.append([None, "LUNES 2", "MARTES 3", "HORA", "MIÉRCOLES 4"])
    h.append([dt.time(11), "NOTICIAS", None, dt.time(11), "CINE\nLa película"])
    h.append([None, "#1 Uno", "#2 Dos"])
    h.append([dt.time(12), "MISA", None, dt.time(1), "DEPORTES"])
    h.append([dt.time(1), "TARDE", "TARDE"])
    h.append([dt.time(2), None, None, dt.time(2)])
    h.append([dt.time(3), "CIERRE"])
    h.append([dt.time(4), None, None, dt.time(4)])
    for rango in ("B3:C3", "B5:C5", "B8:E8"):  # la última cruza la columna HORA del miércoles
        h.merge_cells(rango)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _con_detalle(df) -> list[tuple]:
    return [(f.date(), h.strftime("%H:%M"), d, t, None if pd.isna(x) else x)
            for f, h, d, t, x in df[["Fecha", "Hora", "Duracion", "Titulo", "Detalle"]].itertuples(index=False)]


def test_cuadricula_por_programa_con_horas_de_12_y_detalle_abajo():
    contenido = _por_programa()
    assert inputs.detectar(contenido).cuadricula
    lunes, martes, miercoles = LUNES, LUNES + dt.timedelta(1), LUNES + dt.timedelta(2)
    assert _con_detalle(cuadricula.leer(contenido)) == [
        (lunes, "11:00", 60, "NOTICIAS", "#1 Uno"), (lunes, "12:00", 60, "MISA", None),
        (lunes, "13:00", 120, "TARDE", None), (lunes, "15:00", 60, "CIERRE", None),
        (martes, "11:00", 60, "NOTICIAS", "#2 Dos"), (martes, "12:00", 60, "MISA", None),
        (martes, "13:00", 120, "TARDE", None), (martes, "15:00", 60, "CIERRE", None),
        (miercoles, "11:00", 120, "CINE", "La película"), (miercoles, "13:00", 120, "DEPORTES", None),
        (miercoles, "15:00", 60, "CIERRE", None),
    ]


def test_cuadricula_por_programa_de_24_horas_cruza_la_medianoche():
    wb = Workbook()
    h = wb.active
    h.append(["Semana del 2 de noviembre de 2026"])
    h.append([None, "Lun 2", "Mar 3", "Mie 4"])
    h.append([dt.time(22), "NOTICIAS"])
    h.append([None, "#5 Final"])
    h.append([dt.time(23, 30), "CINE"])
    h.append([dt.time(0, 30), "MADRUGADA"])
    h.append([dt.time(1)])
    for fila in range(3, 7):
        h.merge_cells(f"B{fila}:D{fila}")
    buf = io.BytesIO()
    wb.save(buf)
    filas = _con_detalle(cuadricula.leer(buf.getvalue()))
    assert filas[:3] == [(LUNES, "22:00", 90, "NOTICIAS", "#5 Final"), (LUNES, "23:30", 60, "CINE", None),
                         (LUNES + dt.timedelta(1), "00:30", 30, "MADRUGADA", None)]
    assert len(filas) == 9


@pytest.mark.skipif(not AGAPE.exists(), reason="la grilla real no está en el repo")
def test_grilla_real_de_agape_contra_su_ejemplo():
    tabla = cuadricula.leer(AGAPE.read_bytes())
    ejemplo = pd.read_excel(AGAPE_EJEMPLO)
    leido = {(f.date(), h.strftime("%H:%M")): t.lower() for f, h, t in tabla[["Fecha", "Hora", "Titulo"]].itertuples(index=False)}
    iguales = sum(str(p).lower()[:8] in leido.get((f.date(), h.strftime("%H:%M")), "")
                  for f, h, p in ejemplo[["FECHA", "HORA", "TIT PROG"]].itertuples(index=False))
    assert iguales / len(ejemplo) > 0.85  # lo que falta lo cambió una persona: "Fin de transmisión", programas partidos


@pytest.mark.skipif(not AGAPE.exists(), reason="la grilla real no está en el repo")
def test_crear_agape_con_su_ejemplo_saca_casi_todo_de_la_base(cliente):
    archivos = {"grilla_cruda": ("AGAPE.xlsx", AGAPE.read_bytes()), "ejemplo": ("IG.xlsx", AGAPE_EJEMPLO.read_bytes())}
    r = cliente.post("/api/senales/crear", files=archivos, data={"nombre": "Agape"})
    assert r.status_code == 200, r.text
    assert r.json()["aviso"] is None and r.json()["pautas"]["agregadas"] > 50  # se repiten mucho: el Angelus, la misa
    resumen = cliente.post("/api/senales/agape/abierta", files={"archivo": ("AGAPE.xlsx", AGAPE.read_bytes())}).json()["resumen"]
    assert resumen["base"] / resumen["filas"] > 0.85


def _semana_siguiente_de_agape() -> bytes:
    """La grilla de AGAPE corrida una semana, con otros capítulos: lo que llega de verdad la semana que viene."""
    import openpyxl
    wb = openpyxl.load_workbook(AGAPE)
    ws = wb.active
    ws["A1"] = "O.R.T. 200 CARTA DE PROGRAMACIÓN DEL 02 DE NOV AL 08 NOV 2026 VERSIÓN 1"
    for col, dia in zip("BCDEFHJ", ["LUNES 02", "MARTES 03", "MIÉRCOLES 04", "JUEVES 05", "VIERNES 06", "SÁBADO 07",
                                    "DOMINGO 08"]):
        ws[f"{col}2"] = dia
    for fila in ws.iter_rows(min_row=3):
        for celda in fila:
            if isinstance(celda.value, str) and (x := re.match(r"\s*#\s*(\d+)", celda.value)):
                celda.value = f"#{int(x[1]) + 1} Capítulo nuevo {celda.coordinate}"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# Las columnas del EPG se reconocen por lo que tienen: con nombres que no dicen nada tiene que salir igual.
RAROS = {"TIT PROG": "Show", "TIT CAP": "Sub", "NRO TEMP": "S", "NRO CAP": "E", "TIT TEMP": "Ciclo", "TT": "Marca"}


@pytest.mark.skipif(not AGAPE.exists(), reason="la grilla real no está en el repo")
@pytest.mark.parametrize("nombres", [{}, RAROS])
def test_la_semana_siguiente_de_agape_sale_con_los_programas_de_la_base(cliente, nombres):
    from app import almacen
    from app.agent import asistente
    from tests.unit.test_api import excel
    esperado = pd.read_excel(AGAPE_EJEMPLO, dtype=object).rename(columns=nombres)
    archivos = {"grilla_cruda": ("AGAPE.xlsx", AGAPE.read_bytes()), "ejemplo": ("IG.xlsx", excel(esperado))}
    assert cliente.post("/api/senales/crear", files=archivos, data={"nombre": "Agape"}).status_code == 200
    receta = almacen.leer("agape")
    tabla = cuadricula.leer(AGAPE.read_bytes())
    ejemplos = [asistente.Ejemplo("ej", tabla, pd.read_excel(io.BytesIO(excel(esperado)), dtype=object))]
    almacen.guardar(asistente.con_criterios(receta, tabla, ejemplos, "ej"), "admin")  # lo mínimo que arma el agente

    d = cliente.post("/api/senales/agape/abierta", files={"archivo": ("AGAPE 02-11.xlsx", _semana_siguiente_de_agape())}).json()
    prog, temp, cap = (nombres.get(c, c) for c in ("TIT PROG", "NRO TEMP", "TIT CAP"))
    assert d["programa"] == prog
    assert d["resumen"]["revisar"] <= 3 < d["resumen"]["nueva_lista"]  # los capítulos nuevos de programas conocidos
    nuevas = {p["salida"][prog]: p["salida"] for p in d["nuevas"]}
    assert nuevas["¿Y tu que vas a hacer?"][temp] == 1 and "Capítulo nuevo" in nuevas["¿Y tu que vas a hacer?"][cap]


def test_crear_una_senal_con_una_grilla_sin_fecha_ni_hora_avisa(cliente):
    wb = Workbook()
    wb.active.append(["Programa", "Capitulo"])
    wb.active.append(["Noticias", "Uno"])
    buf = io.BytesIO()
    wb.save(buf)
    archivos = {"grilla_cruda": ("rara.xlsx", buf.getvalue()), "ejemplo": ("ej.xlsx", _xlsx())}
    r = cliente.post("/api/senales/crear", files=archivos, data={"nombre": "Rara"})
    assert r.status_code == 200, r.text
    assert "No encontré la fecha y la hora" in r.json()["aviso"]
