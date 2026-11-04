import json
import os
import runpy
import threading
import time

import pytest

from app import auth, caja
from app.caja import autoprueba

instalada = pytest.mark.skipif(not caja.instalada(), reason="La caja no está instalada: npm ci en caja/")


@pytest.fixture
def en_paralelo(monkeypatch):
    """Todos los núcleos para la autoprueba: en el servidor van de a dos, acá el test tardaría el doble."""
    n = max(2, os.cpu_count() or 2)
    monkeypatch.setattr(caja, "SIMULTANEOS", n)
    monkeypatch.setattr(caja, "_turnos", threading.BoundedSemaphore(n))


@instalada
def test_el_codigo_normal_corre_y_devuelve_su_resultado():
    r = caja.correr(autoprueba.NORMAL, autoprueba.NORMAL_DATOS)
    assert r["ok"] and r["resultado"] == autoprueba.NORMAL_ESPERADO, r


@instalada
def test_un_lector_que_lee_os_environ_falla_y_no_ve_las_claves(monkeypatch):
    monkeypatch.setenv("AUTORTV_PRUEBA_CLAVE", "sk-ant-no-se-tiene-que-ver-123")
    for codigo in ("import os\ndef principal(d):\n    return dict(os.environ)",
                   "import os\ndef principal(d):\n    return os.environ['AUTORTV_PRUEBA_CLAVE']",
                   "import js\ndef principal(d):\n    return js.Deno.env.toObject().to_py()"):
        r = caja.correr(codigo, None)
        assert not r["ok"] and "sk-ant-no-se-tiene-que-ver" not in json.dumps(r), r


@instalada
def test_un_lector_que_abre_un_socket_falla():
    for codigo in ("import socket\ndef principal(d):\n    socket.create_connection(('1.1.1.1', 443), 3)\n    return 'conectó'",
                   "import js\nasync def principal(d):\n    r = await js.fetch('https://example.com')\n    return await r.text()"):
        r = caja.correr(codigo, None)
        assert not r["ok"], r


@instalada
def test_un_lector_que_lee_otro_archivo_falla(tmp_path):
    secreto = tmp_path / "secreto.txt"
    secreto.write_text("contenido-que-no-se-tiene-que-ver")
    for codigo in (f"def principal(d):\n    return open({str(secreto)!r}).read()",
                   f"import js\ndef principal(d):\n    return js.Deno.readTextFileSync({str(secreto)!r})"):
        r = caja.correr(codigo, None)
        assert not r["ok"] and "contenido-que-no-se-tiene-que-ver" not in json.dumps(r), r


@instalada
def test_el_tiempo_la_memoria_y_la_salida_tienen_tope():
    r = caja.correr("def principal(d):\n    while True:\n        pass", None, segundos=4)
    assert not r["ok"] and r["error"] == "Se cortó: tardó más de 4 s." and r["segundos"] < 8
    r = caja.correr("def principal(d):\n    return len([bytearray(50_000_000) for _ in range(40)])", None, memoria_mb=400)
    assert not r["ok"] and r["error"] == "Se cortó: usó más de 400 MB."
    r = caja.correr("import js\ndef principal(d):\n    b = js.Uint8Array.new(1_000_000)\n    for _ in range(50):\n"
                    "        js.Deno.stdout.writeSync(b)\n    return []", None)
    assert not r["ok"] and "escribió de más" in r["error"]


@instalada
def test_la_autoprueba_bloquea_todos_los_intentos(en_paralelo):
    r = autoprueba.probar(segundos=5)
    assert r["anda"] and r["ok"], [c for c in r["casos"] if not c["bloqueado"]]
    assert len(r["casos"]) >= 30


@instalada
def test_un_intento_que_sale_de_la_caja_deja_el_codigo_apagado(monkeypatch, en_paralelo):
    monkeypatch.setattr(autoprueba, "_casos", lambda archivo, escrito: {"Uno que no hace nada raro": "def principal(d):\n    return 'salió'"})
    r = autoprueba.probar(segundos=5)
    assert r["anda"] and not r["ok"] and r["motivo"].startswith("Se escapó 1")


def test_en_el_build_un_escape_corta_y_una_caja_que_no_arranca_solo_avisa(monkeypatch, capsys):
    for anda, ok, codigo in ((True, False, 1), (True, True, 0), (False, False, 0)):
        monkeypatch.setattr(autoprueba, "probar", lambda: {"anda": anda, "ok": ok, "motivo": "-", "casos": []})
        with pytest.raises(SystemExit) as salida:
            runpy.run_module("app.caja", run_name="__main__")
        assert salida.value.code == codigo


def test_la_caja_se_ve_y_se_prueba_desde_administrar(cliente, monkeypatch):
    monkeypatch.setattr(autoprueba, "_estado", {"ok": False, "anda": False, "probando": False, "casos": [], "motivo": "-"})
    monkeypatch.setattr(autoprueba, "probar", lambda: {"ok": True, "anda": True, "motivo": "Bloqueó los 1 intentos.",
                                                       "casos": [{"nombre": "x", "bloqueado": True, "motivo": "-"}]})
    assert not cliente.get("/api/admin/caja").json()["ok"] and not autoprueba.disponible()
    cliente.post("/api/admin/caja/probar")
    for _ in range(50):
        if not autoprueba.estado()["probando"]:
            break
        time.sleep(0.05)
    assert cliente.get("/api/admin/caja").json()["motivo"] == "Bloqueó los 1 intentos." and autoprueba.disponible()
    auth.crear_usuario("ana", "clave-segura")
    assert cliente.post("/api/login", json={"usuario": "ana", "clave": "clave-segura"}).status_code == 200
    assert cliente.get("/api/admin/caja").status_code == 403
    assert cliente.post("/api/admin/caja/probar").status_code == 403


def test_la_autoprueba_no_cambia_el_entorno_del_servidor(monkeypatch):
    # Con el servidor andando, otro hilo puede estar leyendo el entorno: cambiarlo ahí puede tirar abajo el proceso.
    monkeypatch.setattr(caja, "instalada", lambda: True)
    monkeypatch.setattr(caja, "correr", lambda codigo, datos, **k: {"ok": True, "resultado": autoprueba.NORMAL_ESPERADO}
                        if codigo == autoprueba.NORMAL else {"ok": False, "error": "bloqueado"})
    antes = dict(os.environ)
    assert autoprueba.probar(segundos=1)["ok"]
    assert dict(os.environ) == antes and os.environ[autoprueba.CANARIO]
