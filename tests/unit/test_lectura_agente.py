import datetime as dt
import json

import pandas as pd

from app.agent import cliente, controles, lectura
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
