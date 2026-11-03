import pandas as pd

from tests.unit.test_api import _con_asistente, excel
from tests.unit.test_conversaciones import _ana

GRILLA = pd.DataFrame({"Fecha": ["2026-11-02", "2026-11-02"], "Hora": ["06:00", "07:00"],
                       "Programa": ["Noticias", "Cine"]})
EPG = pd.DataFrame({"Fecha": ["2026-11-02", "2026-11-02"], "Hora": ["06:00", "07:00"],
                    "Programa": ["Noticias", "Cine"], "Genero": ["Info", ""]})


def _senal(cliente, nombre: str) -> str:
    r = cliente.post("/api/senales/crear", data={"nombre": nombre},
                     files={"grilla_cruda": ("g.xlsx", excel(GRILLA)), "ejemplo": ("e.xlsx", excel(EPG))})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _charla(cliente, monkeypatch, herramientas: list[dict], senal=None):
    proveedor = _con_asistente(monkeypatch, [{"respuesta": "Listo.", "herramientas": herramientas}])
    receta = cliente.get(f"/api/senales/{senal}").json() if senal else None
    return proveedor, cliente.post("/api/asistente/charla", json={"senal": receta, "pedido": "x", "historial": []}).json()


def test_el_agente_mira_otra_senal_y_recibe_lo_que_pidio(cliente, monkeypatch):
    _senal(cliente, "XT")
    otra = _senal(cliente, "TBN")
    proveedor, c = _charla(cliente, monkeypatch, [{"nombre": "listar_senales", "datos": {}},
                                     {"nombre": "buscar_pautas", "datos": {"senal": otra, "texto": "cine"}},
                                     {"nombre": "ver_reglas", "datos": {"senal": "no-existe"}}], senal="xt")
    assert c["respuesta"] == "Listo." and c["acciones"] == []
    resultados = [b["content"] for b in proveedor.pedidos[-1][-1]["content"]]
    assert '"id": "tbn"' in resultados[0] and '"activa": true' in resultados[0]
    assert '"total": 1' in resultados[1] and "Cine" in resultados[1]
    assert "No existe la señal «no-existe»" in resultados[2]


def test_un_cambio_en_otra_senal_queda_para_confirmar_y_marcado(cliente, monkeypatch):
    _senal(cliente, "XT")
    otra = _senal(cliente, "TBN")
    _, c = _charla(cliente, monkeypatch, [{"nombre": "corregir_pautas", "datos": {
        "senal": otra, "filtro": {"Programa": "Cine"}, "columna": "Genero", "valor": "Película"}},
        {"nombre": "ir_a", "datos": {"pantalla": "base", "senal": otra}}], senal="xt")
    cambio, pagina = c["acciones"]
    assert (cambio["nivel"], cambio["otra_senal"], cambio["pautas"]) == ("cambio", True, 1)
    assert "En TBN, en las 1 pautas con Programa = Cine, poner Genero = Película" == cambio["descripcion"]
    assert (pagina["nivel"], pagina["descripcion"]) == ("pagina", "Ir a base de TBN")
    assert cliente.get(f"/api/senales/{otra}/pautas").json()["pautas"][0]["salida"]["Genero"] in (None, "")  # no cambió


def test_proponer_reglas_va_a_la_senal_que_se_nombra_o_a_la_activa(cliente, monkeypatch):
    _senal(cliente, "XT")
    otra = _senal(cliente, "TBN")
    _, c = _charla(cliente, monkeypatch, [{"nombre": "proponer_reglas", "datos": {"pedido": "año aparte"}},
                             {"nombre": "proponer_reglas", "datos": {"senal": otra, "pedido": "mayúsculas"}}], senal="xt")
    assert [(p["senal"], p["otra_senal"]) for p in c["propuestas"]] == [("xt", False), ("tbn", True)]
    assert c["proponer_cambios"]


def test_lo_hecho_con_el_agente_queda_marcado_y_le_avisa_al_admin(cliente):
    otra = _senal(cliente, "TBN")
    ana = _ana(cliente)
    r = ana.post(f"/api/senales/{otra}/pautas/editar-varias", headers={"X-Origen": "agente"},
                 json={"filtro": {"Programa": "Cine"}, "columna": "Genero", "valor": "Película"})
    assert r.status_code == 200, r.text
    ana.post("/api/agente/hecho", json={"senal": otra, "descripcion": "Poner Genero = Película en Cine"})
    carga = next(x for x in cliente.get("/api/historial").json() if x["senal_id"] == otra and x["cuenta"].get("base"))
    detalle = cliente.get(f"/api/historial/{otra}?carga={carga['carga']}").json()
    assert [d["origen"] for d in detalle if d["tipo"] == "base"] == ["agente"]
    (aviso,) = [a for a in cliente.get("/api/admin/avisos").json() if a["tipo"] == "agente"]
    assert aviso["usuario"] == "ana" and "Película" in aviso["detalle"]
