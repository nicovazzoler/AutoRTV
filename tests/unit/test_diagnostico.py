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


def test_dos_grillas_en_dos_zonas_se_lee_una_y_falta_cruzar_la_hoja_de_datos():
    # La misma grilla en dos zonas ya no se lee doble: queda la hoja de datos, que el lector todavía no cruza.
    contenido = _libro({"Grilla ARG": _grilla(), "Grilla MEX": _grilla(-3), "Datos": DATOS})
    d = diagnostico.diagnosticar(contenido, _ejemplo(con_sinopsis=True))
    (datos,) = d["hallazgos"]
    assert (d["principal"], d["necesita"]) == ("hoja_de_datos", "opcion")
    assert (datos["hoja"], datos["columna"]) == ("Datos", "SINOPSIS")


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
    assert c["resultado"]["resumen"]["diagnostico"] == {"senales": 1, "necesita": {"opcion": 1},
                                                         "principal": {"hoja_de_datos": 1}}


def test_una_lectura_guardada_vieja_que_se_corrige_sola_al_subir_no_frena():
    # Como X-TIME: la señal leía la primera hoja y el libro trae una por día.
    dias = {f"Día {n}": [r for r in _grilla() if r[0] == "Fecha" or r[0].day == 1 + n] for n in (1, 2, 3)}
    guardada = {"tipo": "excel", "fila_encabezado": 1}
    d = diagnostico.diagnosticar(_libro(dias), _ejemplo(), guardada)
    (vieja,) = d["hallazgos"]
    assert (d["principal"], d["necesita"], vieja["tipo"]) == ("lectura_guardada_vieja", "nada", "lectura_guardada_vieja")
    assert d["lecturas"]["al_subir"]["entrada"]["todas_las_hojas"]


def test_una_lectura_guardada_que_no_anda_y_no_se_corrige_sola_hay_que_actualizarla():
    guardada = {"tipo": "excel", "hojas": ["Semana vieja"]}  # una hoja de un archivo anterior que ya no viene
    d = diagnostico.diagnosticar(_libro({"Grilla": _grilla()}), _ejemplo(), guardada)
    assert (d["principal"], d["necesita"]) == ("lectura_guardada_mala", "actualizar")


def test_una_semanal_sin_fechas_se_lee_con_el_lunes_que_elige_la_persona():
    nombres = {2: "LUNES", 3: "MARTES", 4: "MIÉRCOLES"}
    semanal = [["Día", "Hora", "Programa"]] + [[nombres[r[0].day], r[1], r[2]] for r in _grilla()[1:]]
    d = diagnostico.diagnosticar(_libro({"Grilla": semanal}), _ejemplo())
    assert (d["principal"], d["necesita"]) == ("elige_el_lunes", "nada")


def test_varios_archivos_sin_fecha_con_la_fecha_en_el_nombre_piden_una_opcion():
    from app.inputs import varios
    por_dia = {dia: [["Hora", "Programa"]] + [[r[1], r[2]] for r in _grilla()[1:] if r[0].day == dia] for dia in (2, 3, 4)}
    zip_ = varios.empaquetar([(f"A3 CINE {dia:02d}-11.xlsx", _libro({"Grilla": filas})) for dia, filas in por_dia.items()])
    d = diagnostico.diagnosticar(zip_, _ejemplo())
    (hallazgo,) = [h for h in d["hallazgos"] if h["tipo"] != "falta_en_el_archivo"]
    assert (d["principal"], d["necesita"], hallazgo["archivos"]) == ("fecha_por_archivo", "opcion", 3)


def test_una_columna_nueva_de_numeros_acepta_texto_de_la_tarjeta_siguiente():
    # Como MÓRBIDO TV: la duración queda en números y una regla después escribe "50" en algunas filas.
    from app.engine import model as m
    from app.engine.pipeline import aplicar
    tabla = pd.DataFrame(_grilla()[1:], columns=["Fecha", "Hora", "Programa"])
    tarjetas = [m.Duracion(id="d", tipo="duracion", modo="hasta_siguiente", fecha="Fecha", hora="Hora", destino="DUR"),
                m.Asignar(id="a", tipo="asignar", columna="DUR", valor="50",
                          si=m.Condicion(columna="Programa", op="igual", valor="Cocina con Ana"))]
    r = aplicar(tabla, tarjetas)
    assert all(i.error is None for i in r.informes), [i.error for i in r.informes]
    assert set(r.tabla.loc[r.tabla["Programa"] == "Cocina con Ana", "DUR"]) == {"50"}


def test_varios_archivos_con_la_fecha_completa_en_el_nombre_se_leen_solos():
    from app.inputs import varios
    por_dia = {dia: [["Hora", "Programa"]] + [[r[1], r[2]] for r in _grilla()[1:] if r[0].day == dia] for dia in (2, 3, 4)}
    zip_ = varios.empaquetar([(f"202611{dia:02d}-A3Cine (29-10).xlsx", _libro({"Grilla": f})) for dia, f in por_dia.items()])
    d = diagnostico.diagnosticar(zip_, _ejemplo())
    assert (d["principal"], d["necesita"]) == ("lee_bien", "nada"), d["hallazgos"]
