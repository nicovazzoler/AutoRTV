import json

import pandas as pd
from fastapi.testclient import TestClient

from app.agent.asistente import Entorno, pedir
from app.agent.cliente import Grabado
from app.engine import model as m
from app.main import app
from tests.unit.test_api import _con_asistente
from tests.unit.test_semana import SEPARAR, _semana

TABLA = pd.DataFrame({"Titulo": ["joseph prince", "praise"]})
RECETA = m.Senal(id="x", nombre="x", entrada={"tipo": "excel"}, salida={"columnas": []}, tarjetas=[])
SIN_REGLAS = {"explicacion": "ok", "tarjetas_json": "", "columnas_salida": None,
              "correcciones_base_json": "[]", "acciones_admin_json": "[]"}
CREAR_ANA = json.dumps([{"tipo": "crear_usuario", "usuario": "ana"}])


def test_sin_tarjetas_no_cambia_las_reglas_y_trae_correcciones():
    correccion = [{"filtro": {"Programa": "Praise"}, "columna": "Genero", "valor": "Música"}]
    p = pedir(RECETA, TABLA, "género", Grabado([{**SIN_REGLAS, "correcciones_base_json": json.dumps(correccion)}]))
    assert p.logrado and p.cambios == [] and p.correcciones_base == correccion


def test_acciones_de_admin_solo_para_admin():
    respuesta = {**SIN_REGLAS, "acciones_admin_json": CREAR_ANA}
    comun = pedir(RECETA, TABLA, "creá a ana", Grabado([respuesta, SIN_REGLAS]))
    assert comun.logrado and comun.acciones_admin == [] and comun.vueltas == 2
    admin = pedir(RECETA, TABLA, "creá a ana", Grabado([respuesta]), entorno=Entorno(es_admin=True))
    assert admin.acciones_admin == [{"tipo": "crear_usuario", "usuario": "ana", "admin": False}]


def test_accion_invalida_vuelve_con_el_error():
    mala = {**SIN_REGLAS, "acciones_admin_json": json.dumps([{"tipo": "borrar_todo"}])}
    proveedor = Grabado([mala, SIN_REGLAS])
    p = pedir(RECETA, TABLA, "x", proveedor, entorno=Entorno(es_admin=True))
    assert p.logrado and "acciones_admin_json no cumple el formato" in proveedor.pedidos[1][-1]["content"]


def test_el_agente_ve_primero_las_filas_para_revisar():
    tabla = pd.DataFrame({"Titulo": [f"programa {i}" for i in range(40)]})
    proveedor = Grabado([SIN_REGLAS])
    pedir(RECETA, tabla, "x", proveedor, entorno=Entorno(foco=[30, 35]))
    contexto = proveedor.pedidos[0][0]["content"]
    assert "fila 31: " in contexto and "fila 36: " in contexto and "fila 20: " not in contexto
    assert "las que hay que revisar esta semana son: 31, 36" in contexto
    assert "No es admin" in contexto


def _receta(cliente):
    receta = {"id": "canal", "nombre": "Canal", "entrada": {"tipo": "excel"}, "tarjetas": [SEPARAR],
              "salida": {"columnas": []}}
    cliente.put("/api/senales/canal", json=receta)
    cliente.post("/api/senales/canal/semana/confirmar", json=_semana(cliente, ["Memory Lane - Outkast"]))


def test_propuesta_trae_efecto_y_pautas_afectadas(cliente, monkeypatch):
    _receta(cliente)
    pedido = _semana(cliente, ["Memory Lane - Outkast", "Ruta Sonora: Live"])
    dos_puntos = {**SEPARAR, "id": "s2", "valor": ": ", "si": {"columna": "Titulo", "op": "contiene", "valor": ": "}}
    arregla = {**SIN_REGLAS, "tarjetas_json": json.dumps([SEPARAR, dos_puntos]),
               "correcciones_base_json": json.dumps([{"filtro": {"Programa": "memory lane"},
                                                      "columna": "Genero", "valor": "Música"}])}
    _con_asistente(monkeypatch, [arregla])
    r = cliente.post("/api/asistente", json={**pedido, "pedido": "separá también con dos puntos"}).json()
    assert r["efecto"]["revisar_antes"] == 1 and r["efecto"]["celdas"] >= 1
    cambio = next(e for e in r["efecto"]["ejemplos"] if e["fila"] == 1 and e["columna"] == "Programa")
    assert cambio["despues"] == "Ruta Sonora"
    assert r["correcciones_base"][0]["pautas"] == 1
    assert r["correcciones_base"][0]["descripcion"] == "En las pautas con Programa = memory lane, poner Genero = Música"


def test_acciones_admin_por_api(cliente, monkeypatch):
    _con_asistente(monkeypatch, [{**SIN_REGLAS, "acciones_admin_json": CREAR_ANA}])
    r = cliente.post("/api/asistente", json={"senal": RECETA.model_dump(), "pedido": "creá el usuario ana"}).json()
    assert r["acciones_admin"][0]["descripcion"] == "Crear el usuario ana"

    hecho = cliente.post("/api/admin/acciones", json={"acciones": r["acciones_admin"] + [
        {"tipo": "cambiar_limite_diario", "valor": 7},
        {"tipo": "cambiar_regla_catalogo", "columna": "NoExiste", "regla": "X"}]}).json()
    assert [x["ok"] for x in hecho] == [True, True, False]
    clave = hecho[0]["clave"]
    assert len(clave) >= 8

    ana = TestClient(app)
    assert ana.post("/api/login", json={"usuario": "ana", "clave": clave}).status_code == 200
    assert ana.get("/api/asistente/limites").json() == {"limite_diario": 7, "usados_hoy": 0, "quedan": 7}
    assert ana.post("/api/admin/acciones", json={"acciones": [
        {"tipo": "cambiar_limite_diario", "valor": 999}]}).status_code == 403
    assert cliente.post("/api/admin/acciones", json={"acciones": [{"tipo": "borrar_todo"}]}).status_code == 422


def test_el_modelo_fuerte_solo_si_se_pide():
    proveedor = Grabado([SIN_REGLAS])
    pedir(RECETA, TABLA, "x", proveedor)
    pedir(RECETA, TABLA, "x", proveedor, fuerte=True)
    assert proveedor.fuertes == [False, True]
