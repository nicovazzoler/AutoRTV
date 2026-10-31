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


def test_lectura_que_no_trae_horario_vuelve_con_el_problema():
    como_tabla_comun = {"tipo": "excel", "fila_encabezado": 2}
    proveedor = cliente.Grabado([_respuesta(como_tabla_comun)])
    p = lectura.proponer(_por_programa(), proveedor, "claude-haiku-5-5", _ejemplo())
    assert not p.logrado and p.vueltas == lectura.MAX_VUELTAS
    assert any("fecha y hora" in x for x in p.problemas)


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
    assert proveedor.modelos == [cliente_mod.MODELO] * 2 + [cliente_mod.MODELO_FUERTE] * 2  # Haiku y después Sonnet


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
