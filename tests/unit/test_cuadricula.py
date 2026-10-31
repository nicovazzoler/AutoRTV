import datetime as dt
import io
from pathlib import Path

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
