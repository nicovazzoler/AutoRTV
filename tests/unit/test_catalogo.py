import io

import pandas as pd
from openpyxl import Workbook

from app import catalogo
from app.engine import model as m
from app.validate.grilla import validar

# Mismas formas que el Excel real del laburo, con datos inventados.
FILAS = [
    ("Columna", "Datos exclusivos o formato", "significado"),
    ("Fecha", "Fecha", None), ("Hora", "Hora", None), ("Duración", "INT 720 max", None),
    ("Tit orig", "99 caracteres como max", None), ("Tit princ", "99 caracteres como max", None),
    ("Nro cap", "INT", None), ("Dest", "A - M", None),
    ("TT", "(v) - (d) - (r) - (g)", "vivo - diferido - repetido - grabado"),
    ("Año", "INT si o si 4 caracteres numerales", None), ("Sinopsis corta", "maximo 244 caracteres", None),
    ("Doblado", 1, None), ("SAP", "X", None), ("Tit ing", "99 caracteres como max", None),
    ("tit port", "99 caracteres como max", None),
]


def excel() -> bytes:
    wb = Workbook()
    for f in FILAS:
        wb.active.append(list(f))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_interpreta_cada_regla():
    cols = {c.nombre: c for c in catalogo.desde_excel(excel())}
    assert list(cols)[:4] == ["N", "DIA", "Fecha", "Hora"]  # N y DIA van primero aunque no estén
    assert (cols["Duración"].tipo, cols["Duración"].maximo) == ("entero", 720)
    assert (cols["Tit orig"].tipo, cols["Tit orig"].maximo, cols["Tit orig"].obligatoria) == ("texto", 99, "si")
    assert cols["Nro cap"].tipo == "entero" and cols["Nro cap"].maximo is None
    assert cols["Dest"].valores == ["A", "M"]
    assert cols["TT"].valores == ["(v)", "(d)", "(r)", "(g)"] and cols["TT"].significado.startswith("vivo")
    assert (cols["Año"].tipo, cols["Año"].maximo) == ("anio", 4)
    assert cols["Sinopsis corta"].maximo == 244
    assert cols["Doblado"].valores == ["1"] and cols["SAP"].valores == ["X"]
    assert cols["Tit ing"].obligatoria == "ing" and cols["tit port"].obligatoria == "port"


def test_valida_celdas_segun_catalogo():
    cat = catalogo.desde_excel(excel())
    salida = pd.DataFrame({
        "FECHA": ["01/10/2026"] * 3, "HORA": ["06:00"] * 3, "DURACION": [60, 800, "x"],
        "TIT ORIG": ["Show", "S" * 100, None], "TIT PRINC": ["Show"] * 3,
        "DEST": ["A", "Z", None], "TT": ["(v)", "(x)", "(R)"], "AÑO": [2024, 24, "2024"], "SAP": ["X", "x", "si"],
    })
    v = m.Validaciones(dia_minutos=None, huecos=False, superposiciones=False, max_duracion_min=None)
    avisos = [(a.fila, a.columna, a.mensaje) for a in validar(salida, v, catalogo=cat) if a.regla == "catalogo"]
    assert (2, "DURACION", "DURACION: 800 pasa el máximo de 720") in avisos
    assert (3, "DURACION", 'DURACION: "x" no es un número entero') in avisos
    assert (2, "TIT ORIG", "TIT ORIG: tiene 100 caracteres (máximo 99)") in avisos
    assert (3, "TIT ORIG", "TIT ORIG vacía (es obligatoria)") in avisos
    assert (2, "DEST", 'DEST: "Z" no es un valor permitido (A, M)') in avisos
    assert (2, "TT", 'TT: "(x)" no es un valor permitido ((v), (d), (r), (g))') in avisos
    assert (2, "AÑO", 'AÑO: "24" no es un año de 4 dígitos') in avisos
    assert (3, "SAP", 'SAP: "si" no es un valor permitido (X)') in avisos
    # Sin errores: vacíos no obligatorios, mayúsculas distintas, año como texto.
    for fila, col in [(3, "DEST"), (3, "TT"), (3, "AÑO"), (2, "SAP")]:
        assert not [a for a in avisos if a[0] == fila and a[1] == col]


def test_obligatorias_segun_idiomas_de_la_senal():
    cat = catalogo.desde_excel(excel())
    salida = pd.DataFrame({"Fecha": ["x"], "Hora": ["x"], "Duración": [1], "Tit orig": ["a"], "Tit princ": ["a"]})
    v = m.Validaciones(dia_minutos=None)
    faltan = lambda idiomas: sorted(a.columna for a in validar(salida, v, catalogo=cat, idiomas=idiomas)
                                    if a.mensaje.startswith("Falta la columna"))
    assert faltan([]) == []  # señal full español
    assert faltan(["ing"]) == ["Tit ing"]
    assert faltan(["ing", "port"]) == ["Tit ing", "tit port"]


def test_ordenar_por_catalogo():
    cat = catalogo.desde_excel(excel())
    assert catalogo.ordenar(["Extra", "TIT PRINC", "fecha", "N"], cat) == ["N", "fecha", "TIT PRINC", "Extra"]
