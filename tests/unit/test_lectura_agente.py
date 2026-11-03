import datetime as dt
import json

import pandas as pd
import pytest

from app.agent import cliente, controles, lectura
from app.agent import cliente as cliente_mod
from app.inputs import cuadricula
from tests.unit.test_cuadricula import LUNES, _con_detalle, _por_programa

CUADRICULA = {"tipo": "excel", "cuadricula": True, "fila_dias": 2, "columnas_hora": ["A", "D"], "doce_horas": True}


def _respuesta(entrada: dict | str) -> dict:
    return {"explicacion": "Cuadrícula con dos columnas de hora.",
            "entrada_json": entrada if isinstance(entrada, str) else json.dumps(entrada)}


def _ejemplo() -> pd.DataFrame:
    filas = cuadricula.leer(_por_programa())
    return pd.DataFrame({"FECHA": filas["Fecha"], "HORA": filas["Hora"], "TIT PROG": filas["Titulo"]})


def test_la_vista_muestra_celdas_con_coordenadas_y_combinadas():
    vista = lectura.vista_cruda(_por_programa())
    assert "Fila 2: B=LUNES 2 | C=MARTES 3 | D=HORA | E=MIÉRCOLES 4" in vista
    assert "B3:C3" in vista and "B8:E8" in vista


def test_la_cuadricula_respeta_lo_que_dice_el_agente():
    contenido = _por_programa()
    forzada = cuadricula.leer(contenido, fila_dias=2, columnas_hora=["A", "D"], doce_horas=True)
    assert _con_detalle(forzada) == _con_detalle(cuadricula.leer(contenido))
    en_24 = cuadricula.leer(contenido, doce_horas=False)
    assert (LUNES, "13:00") not in [(f.date(), h.strftime("%H:%M")) for f, h in en_24[["Fecha", "Hora"]].itertuples(index=False)]


def test_propuesta_invalida_se_corrige_en_la_segunda_vuelta():
    proveedor = cliente.Grabado([_respuesta('{"tipo": "planilla"}'), _respuesta(CUADRICULA)])
    p = lectura.proponer(_por_programa(), proveedor, "claude-haiku-5-5", _ejemplo())
    assert p.logrado and p.vueltas == 2
    assert p.medida == {"filas": 11, "con_horario": 1.0, "empareja": 1.0}
    assert "no es válida" in proveedor.pedidos[1][-1]["content"]
    assert proveedor.modelos == ["claude-haiku-5-5", "claude-haiku-5-5"]


def test_lectura_que_no_trae_horario_vuelve_con_el_problema_y_lo_que_salio():
    como_tabla_comun = {"tipo": "excel", "fila_encabezado": 2}
    proveedor = cliente.Grabado([_respuesta(como_tabla_comun)])
    p = lectura.proponer(_por_programa(), proveedor, "claude-haiku-5-5", _ejemplo())
    assert not p.logrado and p.vueltas == lectura.MAX_VUELTAS
    assert any("fecha y hora" in x for x in p.problemas)
    assert "Así salieron las primeras filas" in proveedor.pedidos[1][-1]["content"]  # ve lo que leyó, no solo el %


def test_el_control_tolera_la_zona_horaria_y_cuenta_solo_los_dias_de_la_grilla():
    leida = pd.DataFrame({"Fecha": [dt.datetime(2026, 11, 2)] * 3, "Hora": [dt.time(6), dt.time(7), dt.time(8, 1)]})
    ejemplo = pd.DataFrame({"FECHA": [dt.datetime(2026, 11, 2)] * 3 + [dt.datetime(2026, 11, 20)],
                            "HORA": [dt.time(9), dt.time(10), dt.time(11), dt.time(9)]})  # 3 h corrido, y otro día
    assert controles.lectura(leida, ejemplo) == {"filas": 3, "con_horario": 1.0, "empareja": 1.0}
    sin_hora = pd.DataFrame({"Titulo": ["A", "B"]})
    medida = controles.lectura(sin_hora, ejemplo)
    assert medida["con_horario"] == 0 and controles.problemas_de_lectura(medida)


def test_una_columna_con_fecha_y_hora_juntas_cuenta_como_horario():
    leida = pd.DataFrame({"start": ["2026-11-02T06:00:00", "2026-11-02T07:30:00"], "title": ["A", "B"]})
    assert controles.lectura(leida)["con_horario"] == 1.0


def test_html_con_scope_lee_el_atributo_del_bloque_mismo():
    from app import inputs
    pagina = ('<table><tr class="fila" data-inicio="2026-11-02T06:00"><td class="t">Uno</td></tr>'
              '<tr class="fila" data-inicio="2026-11-02T07:00"><td class="t">Dos</td></tr></table>').encode()
    entrada = lectura.ENTRADA.validate_python({"tipo": "html", "bloque": "tr.fila", "campos": {
        "Inicio": {"css": ":scope", "attr": "data-inicio"}, "Titulo": {"css": ".t"}}})
    assert inputs.leer(pagina, entrada)["Inicio"].tolist() == ["2026-11-02T06:00", "2026-11-02T07:00"]


def _cuadricula_escondida() -> bytes:
    """Una cuadrícula con los días en la fila 12: la detección del código mira solo las primeras 10."""
    import io
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws["A1"] = "PROGRAMACIÓN"
    for fila in range(2, 12):
        ws.cell(fila, 5, "nota")
    ws.append([None, "LUNES 2", "MARTES 3", "MIÉRCOLES 4"])
    for hora, titulo in [(6, "Noticias"), (7, "Cocina"), (8, "Cine"), (9, None)]:
        ws.append([dt.time(hora), titulo, titulo, titulo])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


ESCONDIDA = {"tipo": "excel", "cuadricula": True, "fila_dias": 12, "columnas_hora": ["A"]}


@pytest.fixture(autouse=True)
def sin_hilo(monkeypatch):
    from app import armados
    monkeypatch.setattr(armados, "EN_HILO", False)


def _senal(cliente_):
    receta = {"id": "canal", "nombre": "Canal", "entrada": {"tipo": "excel"}, "salida": {"columnas": []}, "tarjetas": []}
    cliente_.put("/api/senales/canal", json=receta)


def test_si_el_codigo_no_encuentra_fecha_y_hora_las_busca_el_agente(cliente, monkeypatch):
    from tests.unit.test_api import _con_asistente
    proveedor = _con_asistente(monkeypatch, [_respuesta(ESCONDIDA)])
    _senal(cliente)
    d = cliente.post("/api/senales/canal/abierta", files={"archivo": ("g.xlsx", _cuadricula_escondida())}).json()
    assert d["lectura_agente"]["logrado"] and d["resumen"]["desde"] and d["resumen"]["filas"] == 9
    assert cliente.get("/api/senales/canal").json()["entrada"]["fila_dias"] == 12  # queda para las próximas semanas
    assert cliente.get("/api/asistente/uso").json()["usuarios"][0]["pedidos"] == 1
    assert cliente.get("/api/asistente/limites").json()["usados_hoy"] == 0
    otra = cliente.post("/api/senales/canal/abierta", files={"archivo": ("g.xlsx", _cuadricula_escondida())}).json()
    assert otra["lectura_agente"] is None and len(proveedor.modelos) == 1


def test_el_aviso_queda_solo_si_el_agente_tampoco_las_encuentra(cliente, monkeypatch):
    from tests.unit.test_api import _con_asistente
    proveedor = _con_asistente(monkeypatch, [_respuesta({"tipo": "excel"})])
    _senal(cliente)
    d = cliente.post("/api/senales/canal/abierta", files={"archivo": ("g.xlsx", _cuadricula_escondida())}).json()
    assert not d["lectura_agente"]["logrado"] and "fecha y hora" in " ".join(d["lectura_agente"]["problemas"])
    assert proveedor.modelos == [cliente_mod.MODELO] * 3 + [cliente_mod.MODELO_FUERTE] * 3  # Haiku y después Sonnet


def test_al_crear_la_senal_el_agente_lee_la_grilla_antes_de_cargar_la_base(cliente, monkeypatch):
    from app.inputs import leer
    from app.engine import model as m
    from tests.unit.test_api import _con_asistente, excel
    _con_asistente(monkeypatch, [_respuesta(ESCONDIDA)])
    tabla = leer(_cuadricula_escondida(), m.EntradaExcel(**ESCONDIDA))
    epg = excel(tabla.rename(columns={"Titulo": "Programa"}))
    r = cliente.post("/api/senales/crear", files={"grilla_cruda": ("g.xlsx", _cuadricula_escondida()), "ejemplo": ("e.xlsx", epg)},
                     data={"nombre": "Canal"}).json()
    assert r["aviso"] is None and r["lectura_agente"]["logrado"] and r["pautas"]["agregadas"] == 3


def test_sin_agente_el_aviso_lo_dice(cliente):
    from tests.unit.test_api import excel
    tabla = pd.DataFrame({"Programa": ["Noticias", "Cine"]})
    r = cliente.post("/api/senales/crear", files={"grilla_cruda": ("g.xlsx", excel(tabla)), "ejemplo": ("e.xlsx", excel(tabla))},
                     data={"nombre": "Canal"}).json()
    assert "el agente tampoco" in r["aviso"] and "no está configurado" in r["aviso"]


def _libro_con_la_grilla_al_final() -> bytes:
    """8 hojas: 7 de notas y la grilla en la última, que la detección del código encuentra."""
    import io
    from openpyxl import Workbook
    wb = Workbook()
    wb.active.title = "Portada"
    wb.active["A1"] = "Canal Ágape"
    for i in range(1, 7):
        wb.create_sheet(f"Notas {i}")["A1"] = f"nota {i}"
    ws = wb.create_sheet("Grilla")
    ws.append(["Fecha", "Hora", "Programa"])
    for hora, titulo in [(6, "Noticias"), (7, "Cocina"), (8, "Cine")]:
        ws.append([dt.datetime(2026, 11, 2), dt.time(hora), titulo])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_el_mapa_lista_todas_las_hojas_y_muestra_completa_la_de_la_grilla():
    vista = lectura.vista_cruda(_libro_con_la_grilla_al_final())
    assert "Excel con 8 hojas" in vista
    assert all(f"[{i}] " in vista for i in range(8)) and "Fila 1: A=nota 6" in vista
    assert "La hoja [7] Grilla parece la grilla" in vista and "Fila 4: A=2026-11-02 | B=08:00 | C=Cine" in vista


def test_el_agente_pide_una_hoja_y_despues_propone_leerla():
    contenido = _libro_con_la_grilla_al_final()
    proveedor = cliente.Grabado([{"explicacion": "Quiero ver la hoja 7.", "entrada_json": "", "ver_hoja": "7"},
                                 _respuesta({"tipo": "excel", "hoja": 7, "fila_encabezado": 1})])
    p = lectura.proponer(contenido, proveedor, "claude-haiku-5-5")
    assert p.logrado and p.vueltas == 2 and p.entrada["hoja"] == 7
    assert "Hoja [7] Grilla (4 filas)" in proveedor.pedidos[1][-1]["content"]


def test_una_hoja_que_no_existe_vuelve_con_la_lista():
    assert "Las hojas son: [0] Portada" in lectura._hoja_pedida(_libro_con_la_grilla_al_final(), "Semana")


def test_el_agente_ve_lo_que_leyo_el_codigo_y_puede_aceptarlo():
    from app import inputs
    contenido = _libro_con_la_grilla_al_final()
    codigo = inputs.detectar(contenido)
    proveedor = cliente.Grabado([{"explicacion": "Está bien.", "entrada_json": "", "aceptar": True}])
    p = lectura.proponer(contenido, proveedor, "claude-haiku-5-5", codigo=codigo, motivo="es una señal nueva")
    assert p.logrado and p.acepto and p.entrada["hoja"] == 7 and p.vueltas == 1
    pedido = proveedor.pedidos[0][0]["content"]
    assert "Lo que leyó el código" in pedido and "es una señal nueva" in pedido and "Salieron 3 filas" in pedido


def test_aceptar_una_lectura_que_no_pasa_los_controles_vuelve_con_el_problema():
    from app.engine import model as m
    contenido = _libro_con_la_grilla_al_final()
    proveedor = cliente.Grabado([{"explicacion": "", "entrada_json": "", "aceptar": True},
                                 _respuesta({"tipo": "excel", "hoja": 7})])
    p = lectura.proponer(contenido, proveedor, "claude-haiku-5-5", codigo=m.EntradaExcel(tipo="excel"))
    assert p.logrado and not p.acepto and p.vueltas == 2
    assert "Aceptaste la lectura del código, pero no pasa los controles" in proveedor.pedidos[1][-1]["content"]


def test_cuando_la_lectura_se_ve_rara_se_la_pasa_al_agente():
    from app.api import rutas
    from app.engine import model as m
    from tests.unit.test_excel_hojas import _libro
    contenido = _libro()
    una_hoja = m.Senal(id="x", nombre="X", entrada=m.EntradaExcel(tipo="excel", fila_encabezado=3, hojas=["Día 1"]),
                       tarjetas=[], salida=m.Salida(columnas=[]))
    assert rutas._motivo_para_revisar(una_hoja, contenido, None) == "leyó 1 de las 3 hojas que parecen programación"
    todas = una_hoja.model_copy(update={"entrada": m.EntradaExcel(tipo="excel", fila_encabezado=3, todas_las_hojas=True)})
    assert rutas._motivo_para_revisar(todas, contenido, None) is None
    comun = una_hoja.model_copy(update={"entrada": m.EntradaExcel(tipo="excel")})
    assert rutas._motivo_para_revisar(comun, _libro_de(24), anterior=_libro_de(30)) is None
    assert rutas._motivo_para_revisar(comun, _libro_de(3), anterior=_libro_de(24)) == \
        "salieron 3 filas y la semana anterior tenía 24"


def _libro_de(filas: int) -> bytes:
    import io
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["Fecha", "Hora", "Programa"])
    for hora in range(filas):
        ws.append([dt.datetime(2026, 11, 2 + hora // 24), dt.time(hora % 24), f"Programa {hora}"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_al_crear_una_senal_el_agente_revisa_la_lectura_y_la_deja(cliente, monkeypatch):
    from tests.unit.test_api import _con_asistente
    _con_asistente(monkeypatch, [])
    r = cliente.post("/api/senales/crear", files={"grilla_cruda": ("g.xlsx", _libro_con_la_grilla_al_final())},
                     data={"nombre": "Agape"}).json()
    assert r["lectura_agente"]["acepto"] and r["lectura_agente"]["motivo"] == "es una señal nueva"
    assert cliente.get("/api/senales/agape").json()["entrada"]["hoja"] == 7
    assert cliente.get("/api/asistente/uso").json()["usuarios"][0]["pedidos"] == 1
