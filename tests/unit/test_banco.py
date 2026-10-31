import datetime as dt
import io
import json
import time

import pandas as pd

from app import almacen, corridas
from app.agent import asistente, banco, cliente, controles
from app.engine import model as m
from app.engine.comparar import diferencias, porcentaje_igual
from app.inputs import cuadricula
from tests.unit.test_api import _con_asistente, excel
from tests.unit.test_cuadricula import _xlsx

LECTURA = {"explicacion": "Cuadrícula.", "entrada_json": json.dumps({"tipo": "excel", "cuadricula": True})}
REGLAS = {"explicacion": "Renombro el título.", "columnas_salida": None, "correcciones_base_json": "[]",
          "acciones_admin_json": "[]",
          "tarjetas_json": json.dumps([{"id": "r1", "tipo": "renombrar", "mapa": {"Titulo": "Programa"}}])}


def _ejemplo_de_la_cuadricula(sobra: bool = False) -> bytes:
    """El EPG terminado de la cuadrícula de prueba: lo mismo con "Programa"; `sobra` agrega una fila que puso alguien."""
    t = cuadricula.leer(_xlsx()).rename(columns={"Titulo": "Programa"})
    if sobra:
        extra = pd.DataFrame([{"Fecha": dt.datetime(2026, 11, 2), "Hora": dt.time(5), "Duracion": 60, "Programa": "CIERRE"}])
        t = pd.concat([extra, t], ignore_index=True)
    return excel(t)


def test_con_otra_cantidad_de_filas_se_compara_emparejando_por_fecha_y_hora():
    grilla = cuadricula.leer(_xlsx())
    esperado = pd.read_excel(io.BytesIO(_ejemplo_de_la_cuadricula(sobra=True)), dtype=object)
    salida = grilla.rename(columns={"Titulo": "Programa"})
    pares = controles.pares_con_ejemplo(grilla, esperado)
    assert len(pares) == len(grilla) and pares[0] == (1, 0)  # la fila 0 del ejemplo es la que agregó alguien
    assert porcentaje_igual(salida, esperado, pares) == 100.0
    assert porcentaje_igual(salida, esperado) < 50  # fila por fila, todo queda corrido una fila
    assert controles.pares_con_ejemplo(grilla, grilla) is None  # misma cantidad: fila por fila, como siempre
    salida.loc[3, "Programa"] = "OTRO"
    assert diferencias(salida, esperado, pares) == [{"fila": 4, "columna": "Programa", "obtenido": "OTRO",
                                                     "esperado": esperado.loc[4, "Programa"]}]


def test_el_agente_recibe_las_diferencias_de_las_filas_emparejadas():
    grilla = cuadricula.leer(_xlsx())
    esperado = pd.read_excel(io.BytesIO(_ejemplo_de_la_cuadricula(sobra=True)), dtype=object)
    receta = m.Senal(id="x", nombre="X", entrada={"tipo": "excel", "cuadricula": True}, tarjetas=[],
                     salida=m.Salida(columnas=[]))
    ej = asistente.Ejemplo("ej", grilla, esperado)
    metricas, detalle = asistente.medir(receta, grilla, [ej])
    assert {d["columna"] for d in detalle["diferencias"]["ej"]} == {"Programa"}  # Fecha, Hora y Duración ya coinciden
    assert metricas.ejemplos["ej"] == 75.0


def test_el_banco_prueba_lectura_y_reglas_con_haiku_y_sonnet():
    proveedor = cliente.Grabado([LECTURA, LECTURA, REGLAS])
    par = banco.Par("Canal", _xlsx(), _ejemplo_de_la_cuadricula())
    cobros = []
    caja = banco.Caja(5, lambda *a: cobros.append(a))
    resultados, corte = banco.correr_banco([par], proveedor, caja)
    assert corte is None
    r = resultados[0]
    assert r["lectura"]["haiku"]["logrado"] and r["lectura"]["sonnet"]["logrado"] and r["lectura"]["escalera"] is None
    assert r["reglas"]["haiku"]["despues"] == 100.0 and r["reglas"]["escalera"] is None
    assert r["reglas"]["haiku"]["peores"][0][1] == 100.0
    assert banco.resumen(resultados)["reglas"] == {"senales": 1, "haiku": 1, "sonnet": 1, "escalera": 0}
    assert len(cobros) == 4 and proveedor.modelos == [banco.HAIKU, banco.SONNET]


class Caro(cliente.Grabado):
    def _siguiente(self, cola, mensajes):
        r = super()._siguiente(cola, mensajes)
        r.tokens_entrada = 10_000_000
        return r


def test_el_banco_corta_al_pasar_el_tope():
    pares = [banco.Par(f"Canal {i}", _xlsx(), _ejemplo_de_la_cuadricula()) for i in range(3)]
    resultados, corte = banco.correr_banco(pares, Caro([LECTURA]), banco.Caja(1.5), ["lectura"])
    assert "tope de US$ 1.5" in corte and len(resultados) == 0  # Haiku 1 US$, Sonnet 20: corta en la primera señal


def _esperar(cliente_, corrida_id: int) -> dict:
    for _ in range(100):
        c = cliente_.get(f"/api/admin/banco/{corrida_id}").json()
        if c["estado"] != "corriendo":
            return c
        time.sleep(0.05)
    raise AssertionError("La corrida no terminó")


def test_corrida_desde_la_api_con_progreso_y_uso_registrado(cliente, monkeypatch):
    _con_asistente(monkeypatch, [LECTURA, LECTURA, REGLAS])
    receta = {"id": "canal", "nombre": "Canal", "entrada": {"tipo": "excel", "cuadricula": True}, "tarjetas": [],
              "salida": {"columnas": []}}
    cliente.put("/api/senales/canal", json=receta)
    almacen.guardar_ejemplo("canal", "ejemplo-1", _xlsx(), _ejemplo_de_la_cuadricula())
    assert cliente.get("/api/admin/banco/senales").json()[0]["id"] == "canal"

    r = cliente.post("/api/admin/banco", json={"senales": ["canal"], "tope": 2})
    assert r.status_code == 200, r.text
    c = _esperar(cliente, r.json()["id"])
    assert c["estado"] == "terminada" and c["progreso"] == "Listo"
    assert c["resultado"]["senales"][0]["reglas"]["sonnet"]["despues"] == 100.0
    assert c["resultado"]["resumen"]["lectura"]["haiku"] == 1
    assert cliente.get("/api/admin/banco").json()[0]["id"] == r.json()["id"]
    assert cliente.get("/api/asistente/uso").json()["usuarios"][0]["pedidos"] == 4


def test_no_se_lanzan_dos_corridas_a_la_vez_y_solo_el_admin(cliente, monkeypatch):
    _con_asistente(monkeypatch, [LECTURA])
    assert corridas._candado.acquire(blocking=False)
    try:
        assert cliente.post("/api/admin/banco", json={"senales": ["canal"]}).status_code == 409
    finally:
        corridas._candado.release()
    assert cliente.post("/api/admin/banco", json={"senales": []}).status_code == 422
    from app import auth
    auth.crear_usuario("ana", "clave-segura")
    assert cliente.post("/api/login", json={"usuario": "ana", "clave": "clave-segura"}).status_code == 200
    assert cliente.post("/api/admin/banco", json={"senales": ["canal"]}).status_code == 403


def test_al_arrancar_se_cortan_las_corridas_que_quedaron_colgadas(cliente):
    from app import db
    with db.transaccion() as con:
        con.execute(db.banco_corridas.insert().values(usuario="admin", inicio=dt.datetime.now(), estado="corriendo",
                                                      parametros={}, gastado=0.0))
    corridas.cortar_colgadas()
    assert corridas.listar()[0]["estado"] == "cortada"
