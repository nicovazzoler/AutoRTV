import datetime as dt
import io

import pandas as pd
from openpyxl import Workbook

from app import inputs, pautas
from app.agent import asistente


def _libro() -> bytes:
    """Una hoja por día de 13:00 a 13:00, con la fecha en filas sueltas y un "Intermedio" sin hora entre programas."""
    wb = Workbook()
    for n, (dia, fecha, siguiente) in enumerate([("MIERCOLES", "30 SEPTIEMBRE", "JUEVES 01 OCTUBRE"),
                                                 ("JUEVES", "1 OCTUBRE", "VIERNES 02 OCTUBRE"),
                                                 ("VIERNES", "2 OCTUBRE", "SABADO 03 OCTUBRE")]):
        ws = wb.active if n == 0 else wb.create_sheet()
        ws.title = f"Día {n + 1}"
        ws.append([None, "0:00:18", 2])
        ws.append([None])
        ws.append(["Inicio Aprox", "Inicio Real", "Nombre (English)", "Nombre (Español)", "Genero" if n else "GSEPT"])
        ws.append([None, None, dia, fecha, 2026])
        ws.append([dt.time(13), dt.datetime(2009, 9, 20, 13, 0), "GONE IN 60 SECONDS", "60 SEGUNDOS", "ACCION"])
        ws.append([None, None, "Intermedio", None, None])
        ws.append([dt.time(23, 15), dt.datetime(2009, 9, 20, 23, 19, 1), "THE NEW GUY", "EL CHICO NUEVO", "COMEDIA"])
        ws.append([None, None, *siguiente.split(" ", 1), 2026])
        ws.append([dt.time(1), dt.time(0, 58, 29), "PLAYING GOD", "JUGANDO CON LA VIDA", "DRAMA"])
        ws.append([dt.time(12, 59), dt.time(12, 59)])  # cierra el día: solo horas
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_todas_las_hojas_con_la_fecha_de_las_filas_sueltas():
    contenido = _libro()
    entrada = inputs.detectar(contenido)
    assert entrada.todas_las_hojas and entrada.fila_encabezado == 3
    tabla = inputs.leer(contenido, entrada)
    assert list(tabla.columns)[:5] == ["Fecha", "Inicio Aprox", "Inicio Real", "Nombre (English)", "Nombre (Español)"]
    assert "Genero" in tabla.columns and "GSEPT" not in tabla.columns  # la hoja con otro nombre se alinea por posición
    assert tabla["Nombre (English)"].tolist() == ["GONE IN 60 SECONDS", "THE NEW GUY", "PLAYING GOD"] * 3
    assert [f.date() for f in tabla["Fecha"]][:6] == [dt.date(2026, 9, 30)] * 2 + [dt.date(2026, 10, 1)] * 3 + [dt.date(2026, 10, 2)]


def test_la_base_empareja_con_la_hora_que_usa_el_ejemplo_y_un_minuto_de_margen():
    tabla = inputs.leer(_libro(), inputs.detectar(_libro()))
    ejemplo = pd.DataFrame({"FECHA": [dt.datetime(2026, 9, 30), dt.datetime(2026, 9, 30), dt.datetime(2026, 10, 1)],
                            "HORA": [dt.time(13), dt.time(23, 19), dt.time(0, 59)],  # 00:58:29 redondeado
                            "TIT ING": ["Gone in 60 Seconds", "The New Guy", "Playing God"],
                            "TIT PRIN": ["60 segundos", "El chico nuevo", "Jugando con la vida"]})
    base, _ = pautas.desde_ejemplo(tabla, ejemplo)
    assert sorted(p["salida"]["TIT ING"] for p in base.values()) == ["Gone in 60 Seconds", "Playing God", "The New Guy"]


def test_cada_titulo_en_su_columna_lleva_su_tarjeta_de_criterios():
    tabla = inputs.leer(_libro(), inputs.detectar(_libro()))
    ejemplo = pd.DataFrame({"FECHA": tabla["Fecha"], "HORA": [a.strftime("%H:%M") if isinstance(a, dt.time) else a
                                                               for a in tabla["Inicio Aprox"]],
                            "TIT ING": ["Gone in 60 Seconds", "The New Guy", "Playing God"] * 3,
                            "TIT PRIN": ["60 segundos", "El chico nuevo", "Jugando con la vida"] * 3})
    receta = asistente.m.Senal(id="x", nombre="X", entrada=inputs.detectar(_libro()), tarjetas=[],
                               salida=asistente.m.Salida(columnas=[]))
    sembrada = asistente.con_criterios(receta, tabla, [asistente.Ejemplo("ej", tabla, ejemplo)], "ej")
    leidas = {(t.columna, t.programa, t.idioma) for t in sembrada.tarjetas}
    assert leidas == {("Nombre (English)", "TIT ING", "en"), ("Nombre (Español)", "TIT PRIN", "es")}


def _con_portada(contenido: bytes) -> bytes:
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(contenido))
    portada = wb.create_sheet("Portada", 0)
    portada.append(["XT · Programación de octubre"])
    portada.append([None])
    portada.append(["Contacto", "Teléfono"])
    portada.append(["Ana", "1234"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_una_portada_no_suma_filas():
    contenido = _con_portada(_libro())
    entrada = inputs.detectar(contenido)
    tabla = inputs.leer(contenido, entrada)
    assert tabla.attrs["hojas"] == 3 and len(tabla) == 9


def test_una_senal_que_leia_una_hoja_pasa_a_leerlas_todas(cliente):
    receta = {"id": "xt", "nombre": "XT", "entrada": {"tipo": "excel", "fila_encabezado": 3},
              "salida": {"columnas": []}, "tarjetas": []}
    cliente.put("/api/senales/xt", json=receta)
    d = cliente.post("/api/senales/xt/abierta", files={"archivo": ("XT.xlsx", _libro())}).json()
    assert d["lectura"]["hojas"] == 3 and d["resumen"]["filas"] == 9
    assert (d["resumen"]["desde"], d["resumen"]["hasta"]) == ("2026-09-30", "2026-10-03")
    assert cliente.get("/api/senales/xt").json()["entrada"]["todas_las_hojas"]


def test_el_ejemplo_de_varias_hojas_carga_la_base_de_todas():
    entrada = asistente.m.EntradaExcel(tipo="excel", fila_encabezado=3)
    assert len(inputs.leer_ejemplo(_libro(), entrada)) == 9


def _con_fecha_imposible_y_hoja_rota() -> bytes:
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(_libro()))
    wb.worksheets[2]["D4"] = "31 SEPTIEMBRE"  # no existe: es el viernes 2/10
    rota = wb.copy_worksheet(wb.worksheets[0])
    rota.title = "Rota"
    rota["A7"] = "a confirmar"  # una hora que es texto: la hoja no se puede leer
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_una_fecha_que_no_existe_es_el_dia_siguiente_y_una_hoja_rota_se_saltea():
    contenido = _con_fecha_imposible_y_hoja_rota()
    tabla = inputs.leer(contenido, inputs.detectar(contenido))
    assert tabla.attrs["hojas"] == 3 and tabla.attrs["salteadas"][0].startswith("Rota")
    assert [f.date() for f in tabla["Fecha"]][6:] == [dt.date(2026, 10, 2)] * 2 + [dt.date(2026, 10, 3)]


def test_el_agente_puede_elegir_o_saltear_hojas():
    contenido = _libro()
    solo_una = inputs.leer(contenido, inputs.m.EntradaExcel(tipo="excel", fila_encabezado=3, hojas=["Día 2"]))
    assert len(solo_una) == 3 and solo_una["Fecha"].iloc[0].date() == dt.date(2026, 10, 1)
    sin_una = inputs.leer(contenido, inputs.m.EntradaExcel(tipo="excel", fila_encabezado=3, todas_las_hojas=True,
                                                           saltear_hojas=["Día 1"]))
    assert len(sin_una) == 6


def test_texto_con_dias_sin_fecha_trae_la_columna_dia():
    from app.engine import model as m
    tabla = inputs.leer("LUNES\n06:00 Noticias\nMARTES\n06:00 Cine".encode(), m.EntradaTexto(tipo="texto"))
    assert tabla["Dia"].tolist() == ["LUNES", "MARTES"] and tabla["Fecha"].isna().all()


def _morbido() -> bytes:
    """Como MÓRBIDO TV: una portada y la misma grilla en dos hojas, una con la hora de México y otra con la de Argentina."""
    wb = Workbook()
    wb.active.title = "Programación A"
    wb.active.append(["GRILLA SEMANAL"])
    wb.active.append(["Lunes", "Martes", "Miércoles"])
    for hoja, corrimiento in (("METADATA MEX", -3), ("METADATA ARG", 0)):
        ws = wb.create_sheet(hoja)
        ws.append(["Fecha", "Hora", "Título", "Sinopsis"])
        for dia in (2, 3, 4):
            inicio = dt.datetime(2026, 11, dia, 6) + dt.timedelta(hours=corrimiento)
            for titulo in ("Noche de Terror", "Cine Bizarro", "Dragula", "Tokyo Fist") * 2:
                ws.append([dt.datetime.combine(inicio.date(), dt.time()), inicio.time(), titulo, f"Sinopsis de {titulo}"])
                inicio += dt.timedelta(hours=1, minutes=30)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _epg_de(contenido: bytes, hoja: str) -> bytes:
    from tests.unit.test_api import excel
    t = inputs.leer(contenido, inputs.m.EntradaExcel(tipo="excel", hoja=hoja))
    return excel(t.rename(columns={"Título": "TIT PROG"}))


def test_la_misma_grilla_en_dos_zonas_no_se_lee_dos_veces():
    contenido = _morbido()
    assert inputs.excel.alternativas(contenido) == ["METADATA MEX", "METADATA ARG"]
    detectada = inputs.detectar(contenido)
    assert not detectada.todas_las_hojas and len(inputs.leer(contenido, detectada)) == 24


def test_una_hoja_por_dia_con_la_misma_programacion_todos_los_dias_se_lee_entera():
    # _libro() repite las mismas películas cada día: son días distintos, no la misma grilla.
    assert inputs.excel.alternativas(_libro()) is None
    assert inputs.detectar(_libro()).todas_las_hojas


def test_el_ejemplo_de_la_misma_grilla_en_dos_zonas_se_lee_con_la_hoja_de_su_hora():
    contenido = _morbido()
    todas = inputs.m.EntradaExcel(tipo="excel", todas_las_hojas=True)
    tabla = inputs.leer_ejemplo(contenido, todas, _epg_de(contenido, "METADATA ARG"))
    assert len(tabla) == 24 and tabla["Hora"].iloc[0] == dt.time(6)


def test_al_subir_la_grilla_se_queda_con_la_zona_del_ejemplo_de_la_senal(cliente):
    from app import almacen
    contenido = _morbido()
    receta = {"id": "morbido", "nombre": "Mórbido", "entrada": {"tipo": "excel", "todas_las_hojas": True},
              "tarjetas": [], "salida": {"columnas": []}}
    cliente.put("/api/senales/morbido", json=receta)
    almacen.guardar_ejemplo("morbido", "ejemplo-1", contenido, _epg_de(contenido, "METADATA ARG"))
    d = cliente.post("/api/senales/morbido/abierta", files={"archivo": ("g.xlsx", contenido)}).json()
    assert d["resumen"]["filas"] == 24  # no 48: antes leía México y Argentina juntas
    assert cliente.get("/api/senales/morbido").json()["entrada"]["hoja"] == "METADATA ARG"


def test_una_hoja_elegida_por_nombre_se_respeta_aunque_el_libro_tenga_varias():
    contenido = _morbido()
    elegida = inputs.m.EntradaExcel(tipo="excel", hoja="METADATA ARG")
    assert inputs.con_alternativa(contenido, elegida, None) is elegida
    assert inputs.con_todas_las_hojas(elegida, inputs.m.EntradaExcel(tipo="excel", todas_las_hojas=True)) is elegida


def _sin_encabezado(hora) -> bytes:
    wb = Workbook()
    for i in range(6):
        wb.active.append([dt.datetime(2026, 11, 2), hora(6 + i), f"Programa {i}"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_sin_nombres_de_columna_no_se_pierde_la_primera_fila_y_la_hora_en_texto_cuenta():
    for hora in (dt.time, lambda h: f"{h:02d}:00"):
        contenido = _sin_encabezado(hora)
        entrada = inputs.detectar(contenido)
        assert entrada.fila_encabezado == 0
        tabla = inputs.leer(contenido, entrada)
        assert list(tabla.columns) == ["A", "B", "C"] and tabla["C"].tolist()[0] == "Programa 0" and len(tabla) == 6
        assert pautas.tiene_horario(tabla)
