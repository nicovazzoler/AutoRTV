import datetime as dt

import pandas as pd
import pytest

from app.agent import asistente, cliente
from app.engine import model as m
from app.engine.pipeline import aplicar
from app.engine.tarjetas.criterios import Lectura, configurar, leer
from tests.unit.test_api import _con_asistente, excel

TARJETA = m.Criterios(id="c", tipo="criterios", columna="Titulo", detalle="Detalle", titulos=["Noches de Jazz"])


@pytest.mark.parametrize("titulo, detalle, esperada", [
    ("DIOS ES AMOR (REPRISSE )", "", Lectura("Dios es amor", tt="(r)")),
    ("¿ Y tu que vas a hacer?  T1", "#1 León y Jalpa de Cánovas", Lectura("¿Y tu que vas a hacer?", "León y Jalpa de Cánovas", 1, 1)),
    # Con el capítulo aparte, el " - " del título es parte del programa.
    ("Tiempo para Aprender - Matematicas T2", "#12 Progresiones", Lectura("Tiempo para Aprender - Matematicas", "Progresiones", 2, 12)),
    ("Noches de Jazz Trío Sur", "", Lectura("Noches de Jazz", "Trío Sur")),
    ("Friends S02E05 The One (2004) (HD)", "", Lectura("Friends", "The One", 2, 5, 2004)),
    ("Canal 13 Noticias", "", Lectura("Canal 13 Noticias")),
    ("Los cuentos de Chaski R T1", "", Lectura("Los cuentos de Chaski", temporada=1, tt="(r)")),
    ("Mundo matemático 2", "", Lectura("Mundo matemático", numero=2)),
    ("Live at Wembley - Queen", "", Lectura("Live at Wembley", "Queen")),
    ("Investigacion Cientifica T2026", "#7 Historia", Lectura("Investigacion Cientifica", "Historia", numero=7,
                                                              titulo_temporada="2026")),
    ("Fútbol en vivo", "", Lectura("Fútbol", tt="(v)")),
    ("Cine: Rocky II", "", Lectura("Rocky II")),
    ("La serie Capítulo 4", "", Lectura("La serie", numero=4)),
    ("Programa Pt. 2", "", Lectura("Programa", "Parte 2")),
    ("MEMORY LANE - OUTKAST", "", Lectura("Memory lane", "Outkast")),
    ("Serie 3/10", "", Lectura("Serie", numero=3)),
    ("Show 2x05 - Final", "", Lectura("Show", "Final", 2, 5)),
    ("Lo mismo - Lo mismo", "", Lectura("Lo mismo")),
])
def test_criterios_generales(titulo, detalle, esperada):
    assert leer(titulo, detalle, TARJETA) == esperada


def test_el_programa_conocido_se_queda_con_su_signo_final():
    t = TARJETA.model_copy(update={"titulos": ["¿Y tu que vas a hacer?"]})
    assert leer("¿ Y tu que vas a hacer? T1", "#2 Silao", t) == Lectura("¿Y tu que vas a hacer?", "Silao", 1, 2)


def test_mayusculas_en_ingles_y_respeta_lo_mezclado():
    en = TARJETA.model_copy(update={"idioma": "en"})
    assert leer("THE NIGHT OF THE LIVING DEAD", "", en).programa == "The Night of the Living Dead"
    assert leer("Chicos IPe Preescolar (LA HORA PEQUE)", "", TARJETA).programa == "Chicos IPe Preescolar (LA HORA PEQUE)"
    assert leer("CHICOS IPE (LA HORA PEQUE)", "", TARJETA).programa == "Chicos ipe (La hora peque)"


def test_la_tarjeta_escribe_en_sus_columnas_y_suma_los_programas_de_la_base():
    tabla = pd.DataFrame({"Titulo": ["Noches de Jazz Big Band (R)", "Otro - Uno"], "Detalle": [None, None]})
    t = TARJETA.model_copy(update={"titulos": [], "programa": "TIT PROG", "capitulo": "TIT CAP", "tt": "TT"})
    salida = aplicar(tabla, [t], ["Noches de Jazz"]).tabla
    assert salida[["TIT PROG", "TIT CAP", "TT"]].values.tolist() == [["Noches de Jazz", "Big Band", "(r)"], ["Otro", "Uno", None]]


def test_se_configura_sola_con_las_columnas_del_epg():
    tabla = pd.DataFrame({"Fecha": [dt.datetime(2026, 11, 2)], "Hora": [dt.time(6)], "Titulo": ["A - B"], "Detalle": ["#1 x"]})
    t = configurar(tabla, ["N", "DIA", "FECHA", "HORA", "DUR", "TIT ING", "NRO TEMP", "NRO CAP", "TIT CAP ING", "Año", "TT"], "TIT ING")
    assert (t.columna, t.detalle, t.programa, t.capitulo, t.temporada, t.numero, t.anio, t.tt, t.idioma) == \
        ("Titulo", "Detalle", "TIT ING", "TIT CAP ING", "NRO TEMP", "NRO CAP", "Año", "TT", "en")


def _ejemplo() -> asistente.Ejemplo:
    entrada = pd.DataFrame({"Fecha": [dt.datetime(2026, 11, 2)] * 2, "Hora": [dt.time(6), dt.time(7)],
                            "Titulo": ["MEMORY LANE - OUTKAST (R)", "Juke Box - Uno"]})
    esperado = pd.DataFrame({"TIT PROG": ["Memory lane", "Juke Box"], "TIT CAP": ["Outkast", "Uno"], "TT": ["(r)", None]})
    return asistente.Ejemplo("ej", entrada, esperado)


def test_armar_desde_cero_arranca_de_los_criterios_y_quedan_si_el_agente_no_mejora():
    ej = _ejemplo()
    receta = m.Senal(id="x", nombre="X", entrada={"tipo": "excel"}, tarjetas=[], salida=m.Salida(columnas=[]))
    proveedor = cliente.Grabado(["no es JSON"])
    p = asistente.pedir(receta, ej.entrada, "armá", proveedor, [ej], objetivo="ej")
    assert "criterios" in proveedor.pedidos[0][0]["content"]  # el agente los ve en la receta actual
    assert p.receta["tarjetas"][0]["tipo"] == "criterios" and p.despues.ejemplos["ej"] == 100.0


def test_boton_para_sumar_los_criterios_a_reglas_que_ya_existen(cliente):
    receta = {"id": "canal", "nombre": "Canal", "entrada": {"tipo": "excel"}, "salida": {"columnas": []},
              "tarjetas": [{"id": "l", "tipo": "limpiar_espacios"}]}
    cliente.put("/api/senales/canal", json=receta)
    ej = _ejemplo()
    cliente.post("/api/senales/canal/ejemplos", data={"nombre": "ej"},
                 files={"entrada": ("g.xlsx", excel(ej.entrada)), "esperado": ("e.xlsx", excel(ej.esperado))})
    r = cliente.post("/api/senales/canal/reglas/criterios")
    assert r.status_code == 200, r.text
    assert r.json()["aplicado"] and r.json()["despues"]["ej"] > r.json()["antes"]["ej"]
    assert [t["tipo"] for t in cliente.get("/api/senales/canal").json()["tarjetas"]] == ["criterios", "limpiar_espacios"]
    assert cliente.post("/api/senales/canal/reglas/criterios").status_code == 409
