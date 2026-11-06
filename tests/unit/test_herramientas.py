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
        "senal": otra, "filtro": {"Programa": "Cine"}, "columna": "Genero", "valor": "Película"}}], senal="xt")
    (cambio,) = c["acciones"]
    assert (cambio["otra_senal"], cambio["pautas"]) == (True, 1)
    assert "En TBN, en 1 pauta con Programa = Cine, poner Genero = Película" == cambio["descripcion"]
    assert cliente.get(f"/api/senales/{otra}/pautas").json()["pautas"][0]["salida"]["Genero"] in (None, "")  # no cambió


def test_proponer_reglas_va_a_la_senal_que_se_nombra_o_a_la_activa(cliente, monkeypatch):
    _senal(cliente, "XT")
    otra = _senal(cliente, "TBN")
    _, c = _charla(cliente, monkeypatch, [{"nombre": "proponer_reglas", "datos": {"pedido": "año aparte"}},
                             {"nombre": "proponer_reglas", "datos": {"senal": otra, "pedido": "mayúsculas"}}], senal="xt")
    assert [(p["senal"], p["otra_senal"]) for p in c["propuestas"]] == [("xt", False), ("tbn", True)]
    assert c["proponer_cambios"]


def test_lo_hecho_con_el_agente_queda_marcado_y_le_avisa_al_admin_una_vez(cliente):
    otra = _senal(cliente, "TBN")
    ana = _ana(cliente)
    r = ana.post(f"/api/senales/{otra}/pautas/editar-varias", headers={"X-Origen": "agente"},
                 json={"filtro": {"Programa": "Cine"}, "columna": "Genero", "valor": "Película"})
    assert r.status_code == 200, r.text
    carga = next(x for x in cliente.get("/api/historial").json() if x["senal_id"] == otra and x["cuenta"].get("base"))
    detalle = cliente.get(f"/api/historial/{otra}?carga={carga['carga']}").json()
    assert [d["origen"] for d in detalle if d["tipo"] == "base"] == ["agente"]
    (aviso,) = cliente.get("/api/admin/avisos").json()
    assert (aviso["usuario"], aviso["tipo"]) == ("ana", "agente")
    assert aviso["detalle"] == "Con el agente: cambió Genero a «Película» en 1 pauta"
    ana.post(f"/api/senales/{otra}/pautas/editar-varias", json={"filtro": {"Programa": "Cine"}, "columna": "Genero", "valor": "Drama"})
    assert len(cliente.get("/api/admin/avisos").json()) == 1  # sin el agente, un cambio chico no avisa


def test_muchas_pautas_con_el_agente_avisan_una_sola_vez(cliente):
    from app import pautas
    otra = _senal(cliente, "TBN")
    pautas.guardar(otra, {f"p{i:014d}": {"crudo": {"Programa": f"Serie {i}"}, "salida": {"Programa": "Serie", "Genero": ""}}
                          for i in range(25)}, "revisada", "admin")
    ana = _ana(cliente)
    r = ana.post(f"/api/senales/{otra}/pautas/editar-varias", headers={"X-Origen": "agente"},
                 json={"filtro": {"Programa": "Serie"}, "columna": "Genero", "valor": "Drama"})
    assert r.json()["editadas"] == 25
    (aviso,) = cliente.get("/api/admin/avisos").json()
    assert aviso["detalle"] == "Con el agente: cambió Genero en 25 pautas"


def test_un_resultado_largo_acorta_las_listas_y_queda_json():
    import json
    from app.agent import herramientas
    dato = {"resumen": {"filas": 200}, "pautas": [{"hash": f"h{i}", "salida": {"Titulo": "x" * 70}} for i in range(200)]}
    texto = herramientas.a_texto(dato)
    leido = json.loads(texto)
    assert len(texto) <= herramientas.MAX_RESULTADO and leido["resumen"] == {"filas": 200}
    assert leido["cortado"] == {"pautas": f"se muestran {len(leido['pautas'])} de 200"} and len(dato["pautas"]) == 200
    assert json.loads(herramientas.a_texto([1, 2]))  == [1, 2]  # lo corto va igual


def test_una_herramienta_que_falla_queda_en_el_log(caplog):
    from app.agent import herramientas
    estado = herramientas.Estado("ana", False, "xt", {"xt": "XT"})
    estado._ver_reglas = lambda senal: 1 / 0
    with caplog.at_level("ERROR", logger="autortv"):
        assert estado.usar("ver_reglas", {"senal": "xt"}).startswith("No se pudo: division by zero")
    assert "herramienta ver_reglas falló" in caplog.text


def test_cada_paso_de_la_charla_marca_el_ultimo_bloque_para_el_cache():
    from app.agent.cliente import _con_cache
    mensajes = [{"role": "user", "content": "contexto"}, {"role": "assistant", "content": [{"type": "text", "text": "a"}]},
                {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "x"},
                                             {"type": "tool_result", "tool_use_id": "t2", "content": "y"}]}]
    marcados = _con_cache(mensajes)
    assert [b.get("cache_control") for b in marcados[-1]["content"]] == [None, {"type": "ephemeral"}]
    assert "cache_control" not in mensajes[-1]["content"][1]  # no toca el historial que se sigue usando
    assert _con_cache(mensajes[:1])[0]["content"] == [{"type": "text", "text": "contexto", "cache_control": {"type": "ephemeral"}}]


def test_un_filtro_con_una_columna_que_no_existe_no_deja_cambio(cliente, monkeypatch):
    _senal(cliente, "XT")
    proveedor, c = _charla(cliente, monkeypatch, [{"nombre": "corregir_pautas", "datos": {
        "senal": "xt", "filtro": {"Columna mal escrita": ""}, "columna": "Genero", "valor": "Película"}}], senal="xt")
    assert c["acciones"] == []
    (resultado,) = [b["content"] for b in proveedor.pedidos[-1][-1]["content"]]
    assert "no existen en XT: Columna mal escrita" in resultado and "Programa" in resultado and "Genero" in resultado


def test_hacerlo_cambia_solo_las_pautas_que_se_contaron_al_proponerlo(cliente, monkeypatch):
    from app import pautas
    _senal(cliente, "XT")
    _, c = _charla(cliente, monkeypatch, [{"nombre": "corregir_pautas", "datos": {
        "senal": "xt", "filtro": {"Programa": "Cine"}, "columna": "Genero", "valor": "Película"}}], senal="xt")
    (accion,) = c["acciones"]
    assert len(accion["hashes"]) == 1
    # Entre la propuesta y el «Hacerlo» llega otra pauta que también cumple el filtro.
    pautas.guardar("xt", {"nueva0000000000": {"crudo": {"Programa": "Cine 2"},
                                              "salida": {"Programa": "Cine", "Genero": "Drama"}}}, "revisada", "admin")
    r = cliente.post("/api/senales/xt/pautas/editar-varias", headers={"X-Origen": "agente"},
                     json={"hashes": accion["hashes"], "columna": accion["columna"], "valor": accion["valor"]})
    assert r.json()["editadas"] == 1
    assert pautas.leer("xt", "nueva0000000000")["salida"]["Genero"] == "Drama"
