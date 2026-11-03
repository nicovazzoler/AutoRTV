from app import auth
from tests.unit.test_api import _con_asistente

RECETA = {"id": "xt", "nombre": "XT", "entrada": {"tipo": "excel"}, "salida": {"columnas": []}, "tarjetas": []}


def _ana(cliente):
    from fastapi.testclient import TestClient
    from app.main import app
    auth.crear_usuario("ana", "clave-segura")
    otro = TestClient(app)
    assert otro.post("/api/login", json={"usuario": "ana", "clave": "clave-segura"}).status_code == 200
    return otro


def test_cada_persona_tiene_sus_chats(cliente):
    r = cliente.post("/api/agente/mensajes", json={"rol": "persona", "texto": "Hola, ¿qué hago con XT?", "senal_id": "xt"})
    cid = r.json()["conversacion_id"]
    cliente.post("/api/agente/mensajes", json={"conversacion_id": cid, "rol": "asistente", "texto": "Abrí la semana."})
    assert cliente.get("/api/agente/conversaciones").json()[0]["titulo"] == "Hola, ¿qué hago con XT?"
    assert [m["rol"] for m in cliente.get(f"/api/agente/conversaciones/{cid}").json()] == ["persona", "asistente"]
    ana = _ana(cliente)
    assert ana.get("/api/agente/conversaciones").json() == []
    assert ana.get(f"/api/agente/conversaciones/{cid}").status_code == 404
    assert ana.post("/api/agente/mensajes", json={"conversacion_id": cid, "rol": "persona", "texto": "x"}).status_code == 404
    cliente.delete(f"/api/agente/conversaciones/{cid}")
    assert cliente.get("/api/agente/conversaciones").json() == []


def test_la_charla_sabe_con_quien_habla_recuerda_y_propone_acciones(cliente, monkeypatch):
    proveedor = _con_asistente(monkeypatch, [{
        "respuesta": "Dale, Nico.", "proponer_cambios": True, "recordar": "Lleva las señales de cine.",
        "acciones": [{"tipo": "ir_a", "pantalla": "semana", "senal": "xt", "nombre": "", "descripcion": "Abrir XT"},
                     {"tipo": "ir_a", "pantalla": "semana", "senal": "no-existe", "nombre": "", "descripcion": "x"},
                     {"tipo": "nueva_senal", "pantalla": "", "senal": "", "nombre": "Canal XX", "descripcion": "Crear"}]}])
    cliente.put("/api/senales/xt", json=RECETA)
    yo = next(u for u in cliente.get("/api/usuarios").json() if u["usuario"] == "admin")
    cliente.put(f"/api/usuarios/{yo['id']}/perfil", json={"nombre": "Nico", "descripcion": "Arma las señales nuevas."})
    c = cliente.post("/api/asistente/charla", json={"pedido": "llevame a XT y creá Canal XX"}).json()
    # la señal que no existe se descarta; ir y abrir Agregar señal las hace la web sola
    assert [(a["descripcion"], a["nivel"]) for a in c["acciones"]] == [
        ("Ir a semana de XT", "pagina"), ("Abrir Agregar señal con «Canal XX»", "pagina")]
    assert c["proponer_cambios"] is False  # sin señal abierta no hay cambios que armar
    pedido = proveedor.pedidos[-1][0]["content"]
    assert "se llama Nico" in pedido and "xt: XT" in pedido
    assert [n["texto"] for n in cliente.get("/api/agente/notas").json()] == ["Lleva las señales de cine."]
    cliente.post("/api/asistente/charla", json={"pedido": "otra cosa"})
    assert "Lleva las señales de cine." in proveedor.pedidos[-1][0]["content"]


def test_un_usuario_comun_que_cambia_reglas_le_avisa_al_admin(cliente):
    cliente.put("/api/senales/xt", json=RECETA)
    ana = _ana(cliente)
    con_regla = {**RECETA, "tarjetas": [{"id": "m", "tipo": "mayus_minus", "columnas": ["Titulo"], "modo": "MAYUS"}]}
    assert ana.put("/api/senales/xt", json=con_regla).status_code == 200
    (aviso,) = cliente.get("/api/admin/avisos?sin_ver=true").json()
    assert (aviso["usuario"], aviso["senal_id"], aviso["tipo"]) == ("ana", "xt", "reglas") and "agregó mayus_minus" in aviso["detalle"]
    cliente.post(f"/api/admin/avisos/{aviso['id']}/visto")
    assert cliente.get("/api/admin/avisos?sin_ver=true").json() == []
    assert ana.get("/api/admin/avisos").status_code == 403
    cliente.put("/api/senales/xt", json=RECETA)  # el admin no se avisa a sí mismo
    assert len(cliente.get("/api/admin/avisos").json()) == 1
