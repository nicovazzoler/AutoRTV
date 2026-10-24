import json

import pandas as pd

from app.agent.asistente import Ejemplo, cambios, pedir
from app.agent.cliente import Grabado
from app.engine import model as m

TABLA = pd.DataFrame({"Titulo": ["  joseph prince ", "praise"], "Cap": ["Grace Ep 1", "Live Ep 2"]})
RECETA = m.Senal(id="x", nombre="x", entrada={"tipo": "excel"}, salida={"columnas": []},
                 tarjetas=[{"id": "t1", "tipo": "limpiar_espacios"}])
LIMPIAR = {"id": "t1", "tipo": "limpiar_espacios", "columnas": "*"}
QUITAR_EP = {"id": "t2", "tipo": "quitar", "columnas": ["Cap"], "texto": r" Ep \d+", "regex": True, "donde": "fin"}


def respuesta(*tarjetas, explicacion="ok", columnas=None):
    return {"explicacion": explicacion, "tarjetas_json": json.dumps(list(tarjetas)), "columnas_salida": columnas}


def test_propuesta_valida_al_primer_intento():
    p = pedir(RECETA, TABLA, "sacá el Ep del capítulo", Grabado([respuesta(LIMPIAR, QUITAR_EP, explicacion="Saqué el Ep")]))
    assert p.logrado and p.vueltas == 1 and p.explicacion == "Saqué el Ep"
    assert [c["tipo"] for c in p.cambios] == ["agregada"]
    assert p.receta["tarjetas"][1]["id"] == "t2"


def test_tarjeta_invalida_reintenta_con_el_error():
    mala = {"id": "t2", "tipo": "quitar", "columnas": ["Cap"]}  # le falta "texto"
    proveedor = Grabado([respuesta(LIMPIAR, mala), respuesta(LIMPIAR, QUITAR_EP)])
    p = pedir(RECETA, TABLA, "sacá el Ep", proveedor)
    assert p.logrado and p.vueltas == 2
    devolucion = proveedor.pedidos[1][-1]["content"]
    assert "no cumple el schema" in devolucion and "texto" in devolucion


def test_respuesta_que_no_es_json():
    p = pedir(RECETA, TABLA, "x", Grabado(["no entendí", respuesta(LIMPIAR)]))
    assert p.logrado and p.vueltas == 2


def test_tres_vueltas_fallidas_devuelve_el_ultimo_intento():
    con_error = {"id": "t2", "tipo": "renombrar", "mapa": {"NoExiste": "Y"}}
    p = pedir(RECETA, TABLA, "renombrá", Grabado([respuesta(LIMPIAR, con_error)]))
    assert not p.logrado and p.vueltas == 3
    assert p.problemas == ["tarjeta t2: No existe la columna: NoExiste"]
    assert p.receta is not None  # igual se puede ver qué intentó


def test_ejemplo_que_empeora_vuelve_con_las_diferencias():
    esperado = pd.DataFrame({"Titulo": ["joseph prince", "praise"], "Cap": ["Grace", "Live"]})
    receta = RECETA.model_copy(update={"tarjetas": [m.LimpiarEspacios(**LIMPIAR), m.Quitar(**QUITAR_EP)]})
    rompe = {"id": "t3", "tipo": "mayus_minus", "columnas": ["Titulo"], "modo": "MAYUS"}
    proveedor = Grabado([respuesta(LIMPIAR, QUITAR_EP, rompe), respuesta(LIMPIAR, QUITAR_EP)])
    p = pedir(receta, TABLA, "algo", proveedor, [Ejemplo("semana", TABLA, esperado)])
    assert p.logrado and p.vueltas == 2
    assert p.antes.ejemplos == {"semana": 100.0} and p.despues.ejemplos == {"semana": 100.0}
    devolucion = proveedor.pedidos[1][-1]["content"]
    assert "El ejemplo semana da 50.0 % (antes daba 100.0 %)" in devolucion
    assert 'quedó "JOSEPH PRINCE" y tenía que quedar "joseph prince"' in devolucion


def test_armar_desde_ejemplo_exige_100():
    esperado = pd.DataFrame({"Titulo": ["joseph prince", "praise"], "Cap": ["Grace", "Live"]})
    proveedor = Grabado([respuesta(LIMPIAR), respuesta(LIMPIAR, QUITAR_EP)])
    p = pedir(RECETA, TABLA, "armá la receta", proveedor, [Ejemplo("s", TABLA, esperado)], objetivo="s")
    assert p.logrado and p.vueltas == 2 and p.antes.ejemplos["s"] == 50.0
    assert "tiene que llegar al 100 %" in proveedor.pedidos[1][-1]["content"]


def test_rechazo_del_modelo():
    class Rechaza:
        def pedir(self, *_):
            from app.agent.cliente import Respuesta
            return Respuesta("", rechazo="política")
    p = pedir(RECETA, TABLA, "x", Rechaza())
    assert not p.logrado and "no quiso responder" in p.problemas[0]


def test_datos_de_la_grilla_van_como_datos_y_solo_15_filas():
    tabla = pd.DataFrame({"Titulo": [f"p{i}" for i in range(40)]})
    proveedor = Grabado([respuesta(LIMPIAR)])
    pedir(RECETA, tabla, "x", proveedor)
    contexto = proveedor.pedidos[0][0]["content"]
    assert '"p14"' in contexto and '"p15"' not in contexto
    assert contexto.rstrip().endswith("## Pedido\n\nx")


def test_lista_de_cambios():
    antes = RECETA.model_copy(update={"tarjetas": [m.LimpiarEspacios(**LIMPIAR), m.Quitar(**QUITAR_EP)]})
    despues = antes.model_copy(update={
        "tarjetas": [m.Quitar(**{**QUITAR_EP, "donde": "todo"}), m.Numerar(id="t9", tipo="numerar")],
        "salida": m.Salida(columnas=["N"])})
    assert [(c["tipo"], c["id"], c.get("campos")) for c in cambios(antes, despues)] == [
        ("modificada", "t2", ["donde"]), ("agregada", "t9", None), ("borrada", "t1", None), ("salida", "", None)]
