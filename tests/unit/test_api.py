import datetime as dt
import io
import json
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import app

RECETA = json.loads((Path(__file__).resolve().parents[2] / "ejemplos" / "sintetica.json").read_text(encoding="utf-8"))


def excel(df: pd.DataFrame) -> bytes:
    # Con openpyxl directo: pandas guarda las horas como texto y las grillas reales traen horas de Excel.
    wb = Workbook()
    wb.active.append(list(df.columns))
    for fila in df.itertuples(index=False):
        wb.active.append(list(fila))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


GRILLA = excel(pd.DataFrame({"Fecha": [dt.datetime(2026, 10, 23)] * 2, "Hora": [dt.time(0), dt.time(1, 30)],
                             "Titulo": ["Joseph PrinceGrace", "Praise"]}))


def test_health_es_publico():
    assert TestClient(app).get("/health").json() == {"ok": True}


def test_sin_sesion_no_hay_api(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    c = TestClient(app)
    assert c.get("/api/senales").status_code == 401
    assert c.post("/api/login", json={"usuario": "nadie", "clave": "x"}).status_code == 401


def test_clave_mala_y_logout(cliente):
    assert cliente.post("/api/login", json={"usuario": "admin", "clave": "otra-clave"}).status_code == 401
    assert cliente.get("/api/yo").json()["usuario"] == "admin"
    cliente.post("/api/logout")
    assert cliente.get("/api/yo").status_code == 401


def test_usuarios_solo_admin(cliente):
    assert cliente.post("/api/usuarios", json={"usuario": "ana", "clave": "clave-de-ana"}).status_code == 200
    assert cliente.post("/api/usuarios", json={"usuario": "ana", "clave": "clave-de-ana"}).status_code == 422
    ana = TestClient(app)
    ana.post("/api/login", json={"usuario": "ana", "clave": "clave-de-ana"})
    assert ana.get("/api/senales").status_code == 200
    assert ana.get("/api/usuarios").status_code == 403


def test_guardar_receta_con_historial(cliente, tmp_path):
    assert cliente.put("/api/senales/sintetica", json={"id": "sintetica"}).status_code == 422
    assert cliente.put("/api/senales/otra", json=RECETA).status_code == 422
    assert cliente.put("/api/senales/sintetica", json=RECETA).status_code == 200
    cliente.put("/api/senales/sintetica", json=RECETA)
    assert cliente.get("/api/senales").json() == [{"id": "sintetica", "nombre": RECETA["nombre"]}]
    assert cliente.get("/api/senales/sintetica").json()["tarjetas"][1]["modo"] == "min_mayus"
    from app import almacen
    assert [h["usuario"] for h in almacen.historial("sintetica")] == ["admin", "admin"]


def test_ids_con_ruta_se_rechazan(cliente):
    assert cliente.get("/api/senales/..%2F..%2Fetc").status_code in (404, 422)
    r = cliente.post("/api/senales/sintetica/ejemplos", data={"nombre": "../x"},
                     files={"entrada": ("a.xlsx", GRILLA), "esperado": ("b.xlsx", GRILLA)})
    assert r.status_code == 422


def test_preview_y_export(cliente):
    tabla_id = cliente.post("/api/tablas", files={"archivo": ("g.xlsx", GRILLA)}).json()["tabla_id"]
    r = cliente.post("/api/preview", json={"tabla_id": tabla_id, "senal": RECETA})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    fila = dict(zip(cuerpo["columnas"], cuerpo["filas"][0]))
    assert fila == {"N": 1, "Dia": "VIERNES", "FechaEPG": "23/10/2026", "HoraEPG": "00:00", "Duracion": 90,
                    "Programa": "Joseph Prince", "Capitulo": "Grace"}
    assert all(t["error"] is None for t in cuerpo["tarjetas"])
    # El último programa dura hasta medianoche (1350 min): pasa el máximo de 720.
    assert [(v["regla"], v["fila"]) for v in cuerpo["validaciones"]] == [("duracion_larga", 2)]
    assert cuerpo["columnas_validadas"] == {"fecha": "FechaEPG", "hora": "HoraEPG", "duracion": "Duracion"}

    xlsx = cliente.post("/api/export", json={"tabla_id": tabla_id, "senal": RECETA, "formato": "xlsx"})
    assert xlsx.status_code == 200
    releido = pd.read_excel(io.BytesIO(xlsx.content))
    assert releido["Programa"].tolist() == ["Joseph Prince", "Praise"] and releido["Duracion"].tolist() == [90, 1350]
    csv = cliente.post("/api/export", json={"tabla_id": tabla_id, "senal": RECETA, "formato": "csv"})
    assert csv.content.decode("utf-8-sig").splitlines()[1].startswith("1,VIERNES,23/10/2026,00:00,90")


def test_preview_con_archivo_vencido(cliente):
    assert cliente.post("/api/preview", json={"tabla_id": "no-existe", "senal": RECETA}).status_code == 410


def test_ejemplos_puntuan_la_receta(cliente):
    tabla_id = cliente.post("/api/tablas", files={"archivo": ("g.xlsx", GRILLA)}).json()["tabla_id"]
    xlsx = cliente.post("/api/export", json={"tabla_id": tabla_id, "senal": RECETA}).content
    r = cliente.post("/api/senales/sintetica/ejemplos", data={"nombre": "semana-1"},
                     files={"entrada": ("a.xlsx", GRILLA), "esperado": ("b.xlsx", xlsx)})
    assert r.status_code == 200
    assert cliente.get("/api/senales/sintetica/ejemplos").json() == ["semana-1"]

    (bien,) = cliente.post("/api/senales/sintetica/ejemplos/evaluar", json=RECETA).json()
    assert bien["porcentaje"] == 100 and bien["total_diferencias"] == 0

    sin_separar = {**RECETA, "tarjetas": [t for t in RECETA["tarjetas"] if t["tipo"] != "separar"]}
    (mal,) = cliente.post("/api/senales/sintetica/ejemplos/evaluar", json=sin_separar).json()
    assert mal["porcentaje"] < 100
    assert {d["columna"] for d in mal["diferencias"]} == {"Programa", "Capitulo"}

    cliente.delete("/api/senales/sintetica/ejemplos/semana-1")
    assert cliente.get("/api/senales/sintetica/ejemplos").json() == []


def test_web_se_sirve():
    c = TestClient(app)
    assert c.get("/api/no-existe").status_code == 404


def test_sin_sesion_ninguna_pantalla_se_entrega(cliente):
    anonimo = TestClient(app, follow_redirects=False)
    for ruta in ("/", "/s/canal/revisar", "/admin"):
        r = anonimo.get(ruta)
        assert (r.status_code, r.headers["location"]) == (307, "/login"), ruta
    assert anonimo.get("/login").status_code in (200, 503)  # 503 si la web no está compilada

    # Con sesión, la web resuelve sus rutas sola y el login manda al Inicio.
    cliente.follow_redirects = False
    pagina = cliente.get("/s/canal/revisar")
    assert pagina.status_code == 503 or 'id="raiz"' in pagina.text
    assert cliente.get("/login").headers["location"] == "/"
    assert cliente.get("/viejo").status_code in (200, 503)  # la web vieja ya no existe: es una ruta más de la nueva


def test_guardar_no_pisa_a_otro(cliente):
    cliente.put("/api/senales/sintetica", json=RECETA)
    version = cliente.get("/api/senales/sintetica").headers["ETag"]
    otra = {**RECETA, "nombre": "Cambiada por otro"}
    assert cliente.put("/api/senales/sintetica", json=otra, headers={"If-Match": version}).status_code == 200
    # Mi versión quedó vieja: el guardado se rechaza y dice quién guardó.
    r = cliente.put("/api/senales/sintetica", json=RECETA, headers={"If-Match": version})
    assert r.status_code == 409 and r.json()["detail"].startswith("admin guardó cambios el")
    assert cliente.put("/api/senales/sintetica", json=RECETA).status_code == 200  # "guardar igual"


def _con_asistente(monkeypatch, respuestas):
    from app.agent import cliente as modulo
    proveedor = modulo.Grabado(respuestas)
    monkeypatch.setattr(modulo, "proveedor_configurado", lambda: proveedor)
    return proveedor


ASISTENTE_OK = {"explicacion": "Pasé el programa a mayúsculas",
                "tarjetas_json": json.dumps(RECETA["tarjetas"] + [
                    {"id": "m1", "tipo": "mayus_minus", "columnas": ["Programa"], "modo": "MAYUS"}]),
                "columnas_salida": None}


def test_asistente_sin_key(cliente, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("AGENTE_FALSO", raising=False)
    r = cliente.post("/api/asistente", json={"senal": RECETA, "pedido": "x", "tabla_id": "t"})
    assert r.status_code == 503


def test_asistente_propone_y_registra(cliente, monkeypatch):
    _con_asistente(monkeypatch, [ASISTENTE_OK])
    tabla_id = cliente.post("/api/tablas", files={"archivo": ("g.xlsx", GRILLA)}).json()["tabla_id"]
    r = cliente.post("/api/asistente", json={"senal": RECETA, "pedido": "programa en mayúsculas", "tabla_id": tabla_id})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["logrado"] and cuerpo["cambios"][0]["tipo"] == "agregada"
    # La propuesta no se guarda sola.
    assert cliente.get("/api/senales/sintetica").status_code == 404
    uso = cliente.get("/api/asistente/uso").json()
    assert uso["configurado"] and uso["usuarios"][0]["usuario"] == "admin" and uso["usuarios"][0]["pedidos"] == 1


def test_asistente_tope_diario(cliente, monkeypatch):
    _con_asistente(monkeypatch, [ASISTENTE_OK])
    monkeypatch.setenv("AGENTE_LIMITE_DIARIO", "1")
    tabla_id = cliente.post("/api/tablas", files={"archivo": ("g.xlsx", GRILLA)}).json()["tabla_id"]
    pedido = {"senal": RECETA, "pedido": "x", "tabla_id": tabla_id}
    assert cliente.post("/api/asistente", json=pedido).status_code == 200
    assert cliente.post("/api/asistente", json=pedido).status_code == 429


def test_asistente_desde_ejemplo(cliente, monkeypatch):
    proveedor = _con_asistente(monkeypatch, [ASISTENTE_OK])
    tabla_id = cliente.post("/api/tablas", files={"archivo": ("g.xlsx", GRILLA)}).json()["tabla_id"]
    esperado = cliente.post("/api/export", json={"tabla_id": tabla_id, "senal": RECETA}).content
    cliente.post("/api/senales/sintetica/ejemplos", data={"nombre": "s1"},
                 files={"entrada": ("a.xlsx", GRILLA), "esperado": ("b.xlsx", esperado)})
    r = cliente.post("/api/asistente", json={"senal": RECETA, "pedido": "armá", "ejemplo": "s1"})
    # La propuesta pone el programa en mayúsculas y el ejemplo deja de dar 100 %: 3 vueltas sin lograrlo.
    assert r.status_code == 200 and not r.json()["logrado"] and r.json()["vueltas"] == 3
    assert "Así tiene que quedar" in proveedor.pedidos[0][0]["content"]


def test_cookie_segura_en_railway(monkeypatch):
    from app.api.rutas import _es_produccion

    for v in ("RAILWAY_ENVIRONMENT", "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_ENVIRONMENT_ID", "COOKIE_SEGURA"):
        monkeypatch.delenv(v, raising=False)
    assert not _es_produccion()
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
    assert _es_produccion()
    monkeypatch.setenv("COOKIE_SEGURA", "0")  # se puede apagar a mano, por ejemplo para probar sin HTTPS
    assert not _es_produccion()


def test_login_marca_la_cookie_segura(tmp_path, monkeypatch):
    from app import auth

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("COOKIE_SEGURA", "1")
    auth.crear_usuario("ana", "clave-de-ana")
    r = TestClient(app).post("/api/login", json={"usuario": "ana", "clave": "clave-de-ana"})
    assert "secure" in r.headers["set-cookie"].lower() and "httponly" in r.headers["set-cookie"].lower()


def test_cambiar_mi_clave(cliente):
    otra_sesion = TestClient(app)
    otra_sesion.post("/api/login", json={"usuario": "admin", "clave": "clave-segura"})
    r = cliente.post("/api/yo/clave", json={"actual": "equivocada", "nueva": "clave-nueva-1"})
    assert r.status_code == 422 and r.json()["detail"] == "La clave actual no es correcta"
    assert cliente.post("/api/yo/clave", json={"actual": "clave-segura", "nueva": "corta"}).status_code == 422

    assert cliente.post("/api/yo/clave", json={"actual": "clave-segura", "nueva": "clave-nueva-1"}).status_code == 200
    assert cliente.get("/api/yo").status_code == 200  # la sesión desde la que se cambió sigue
    assert otra_sesion.get("/api/yo").status_code == 401  # las otras se cierran
    assert TestClient(app).post("/api/login", json={"usuario": "admin", "clave": "clave-segura"}).status_code == 401
    assert TestClient(app).post("/api/login", json={"usuario": "admin", "clave": "clave-nueva-1"}).status_code == 200


def test_admin_resetea_clave(cliente):
    cliente.post("/api/usuarios", json={"usuario": "ana", "clave": "clave-de-ana"})
    ana = TestClient(app)
    ana.post("/api/login", json={"usuario": "ana", "clave": "clave-de-ana"})
    def resetear(quien):
        return {"acciones": [{"tipo": "resetear_clave", "usuario": quien}]}

    assert ana.post("/api/admin/acciones", json=resetear("admin")).status_code == 403
    assert not cliente.post("/api/admin/acciones", json=resetear("nadie")).json()[0]["ok"]
    (hecho,) = cliente.post("/api/admin/acciones", json=resetear("ana")).json()
    assert hecho["ok"] and ana.get("/api/yo").status_code == 401
    assert TestClient(app).post("/api/login", json={"usuario": "ana", "clave": hecho["clave"]}).status_code == 200


def test_catalogo_solo_admin_y_ordena_la_preview(cliente):
    from tests.unit.test_catalogo import excel as catalogo_excel

    cliente.post("/api/usuarios", json={"usuario": "ana", "clave": "clave-de-ana"})
    ana = TestClient(app)
    ana.post("/api/login", json={"usuario": "ana", "clave": "clave-de-ana"})
    assert ana.post("/api/catalogo", files={"archivo": ("c.xlsx", catalogo_excel())}).status_code == 403
    assert cliente.post("/api/catalogo", files={"archivo": ("c.xlsx", catalogo_excel())}).status_code == 200
    assert ana.get("/api/catalogo").json()[0]["nombre"] == "N"

    # Sin columnas de salida elegidas, la vista previa sale en el orden del catálogo.
    tabla_id = cliente.post("/api/tablas", files={"archivo": ("g.xlsx", GRILLA)}).json()["tabla_id"]
    sin_salida = {**RECETA, "salida": {"columnas": []}}
    columnas = cliente.post("/api/preview", json={"tabla_id": tabla_id, "senal": sin_salida}).json()["columnas"]
    assert columnas[:2] == ["N", "Dia"]  # "Dia" coincide con DIA del catálogo aunque cambien las mayúsculas


def test_crear_senal_desde_grilla_y_ejemplo(cliente):
    wb = Workbook()
    wb.active.append(["Schedule Data Export"])  # título arriba, como los exports reales
    wb.active.append(["Fecha", "Hora", "Titulo"])
    wb.active.append([dt.datetime(2026, 10, 23), dt.time(0), "Show"])
    buf = io.BytesIO()
    wb.save(buf)
    archivos = {"grilla_cruda": ("grilla.xlsx", buf.getvalue()), "ejemplo": ("hecho.xlsx", GRILLA)}

    assert cliente.post("/api/senales/crear", files=archivos, data={"nombre": "  "}).status_code == 422
    r = cliente.post("/api/senales/crear", files=archivos, data={"nombre": "Mi Señal  HD"})
    assert r.status_code == 200, r.text
    creada = r.json()
    assert (creada["id"], creada["nombre"]) == ("mi-senal-hd", "Mi Señal HD")
    receta = cliente.get("/api/senales/mi-senal-hd").json()
    assert receta["entrada"]["fila_encabezado"] == 2
    assert cliente.get("/api/senales/mi-senal-hd/ejemplos").json() == [creada["ejemplo"]]
    preview = cliente.post("/api/preview", json={"tabla_id": creada["tabla_id"], "senal": receta}).json()
    assert preview["total_filas"] == 1

    # Mismo id: no se puede crear igual, solo sumar como ejemplo.
    igual = cliente.post("/api/senales/crear", files=archivos, data={"nombre": "mi señal hd!", "confirmar": "true"})
    assert igual.status_code == 409 and igual.json()["detail"]["identica"]
    assert igual.json()["detail"]["parecidas"] == [{"id": "mi-senal-hd", "nombre": "Mi Señal HD"}]
    sumada = cliente.post("/api/senales/crear", files=archivos, data={"agregar_a": "mi-senal-hd"})
    assert sumada.status_code == 200
    assert len(cliente.get("/api/senales/mi-senal-hd/ejemplos").json()) == 2

    # Parecido: pide confirmación y con confirmar se crea aparte.
    parecida = cliente.post("/api/senales/crear", files=archivos, data={"nombre": "Mi Senal HD 2"})
    assert parecida.status_code == 409 and not parecida.json()["detail"]["identica"]
    confirmada = cliente.post("/api/senales/crear", files=archivos, data={"nombre": "Mi Senal HD 2", "confirmar": "true"})
    assert confirmada.json()["id"] == "mi-senal-hd-2"
    distinta = cliente.post("/api/senales/crear", files=archivos, data={"nombre": "Otra cosa"})
    assert distinta.status_code == 200


def test_charla_del_asistente(cliente, monkeypatch):
    _con_asistente(monkeypatch, [{"respuesta": "¡Hola! ¿Qué querés cambiar?", "proponer_cambios": False}])
    r = cliente.post("/api/asistente/charla", json={"senal": RECETA, "pedido": "hola", "historial": []})
    assert r.status_code == 200, r.text
    assert r.json()["respuesta"] == "¡Hola! ¿Qué querés cambiar?" and not r.json()["proponer_cambios"]
    assert cliente.post("/api/asistente/charla", json={"senal": RECETA, "pedido": " "}).status_code == 422
    assert cliente.get("/api/asistente/uso").json()["usuarios"][0]["pedidos"] == 1


def test_el_agente_sabe_que_pantalla_se_esta_mirando(cliente, monkeypatch):
    proveedor = _con_asistente(monkeypatch, [{"respuesta": "Dale.", "proponer_cambios": False}])
    r = cliente.post("/api/asistente/charla", json={"senal": RECETA, "pedido": "¿por qué frena?", "historial": [],
                                                    "contexto": "Canal Demo · Semana · Para revisar"})
    assert r.status_code == 200, r.text
    enviado = json.dumps(proveedor.pedidos[-1], ensure_ascii=False)
    assert "(La persona está mirando: Canal Demo · Semana · Para revisar)\\n¿por qué frena?" in enviado


def test_los_numeros_de_pandas_salen_como_json():
    import numpy as np
    from fastapi.encoders import jsonable_encoder
    import app.main  # noqa: F401  registra el encoder
    assert jsonable_encoder({"fila": np.int64(3), "pct": np.float64(1.5), "ok": np.bool_(True)}) == {
        "fila": 3, "pct": 1.5, "ok": True}
