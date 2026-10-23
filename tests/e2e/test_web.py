"""Humo de la web en un Chromium real: login, subir grilla, agregar tarjeta, ver la tabla cambiar."""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")
RAIZ = Path(__file__).resolve().parents[2]


@pytest.fixture
def servidor(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]
    entorno = {"DATA_DIR": str(tmp_path), "ADMIN_USUARIO": "admin", "ADMIN_CLAVE": "clave-segura", "PATH": ""}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(puerto)],
                            cwd=RAIZ, env=entorno, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{puerto}"
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", puerto), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    yield url
    proc.terminate()
    proc.wait()


def test_flujo_basico(servidor, tmp_path):
    import io
    import datetime as dt
    from openpyxl import Workbook

    wb = Workbook()
    wb.active.append(["Fecha", "Hora", "Titulo"])
    wb.active.append([dt.datetime(2026, 10, 23), dt.time(0), "joseph prince"])
    wb.active.append([dt.datetime(2026, 10, 23), dt.time(1, 30), "praise"])
    grilla = tmp_path / "grilla.xlsx"
    wb.save(grilla)

    with playwright.sync_playwright() as p:
        # CHROMIUM permite usar un Chromium ya instalado en vez del que baja Playwright.
        try:
            navegador = p.chromium.launch(executable_path=os.environ.get("CHROMIUM"))
        except playwright.Error as e:
            pytest.skip(f"No hay Chromium para Playwright: {str(e).splitlines()[0]}")
        pagina = navegador.new_page()
        pagina.on("dialog", lambda d: d.accept("Señal de prueba"))
        pagina.goto(servidor + "/")
        pagina.wait_for_url("**/login")
        pagina.fill("input[name=usuario]", "admin")
        pagina.fill("input[name=clave]", "clave-segura")
        pagina.click("button[type=submit]")
        pagina.wait_for_url(servidor + "/")

        pagina.click("#btn-nueva")
        pagina.set_input_files("#in-archivo", str(grilla))
        pagina.wait_for_selector("#tabla td:text('joseph prince')")

        pagina.select_option("#sel-tipo", "mayus_minus")
        pagina.click("#btn-agregar")
        pagina.check(".formulario .opciones-columnas label:has-text('Titulo') input")
        pagina.select_option(".formulario select", "Titulo")
        pagina.wait_for_selector("#tabla td:text('Joseph Prince')")
        assert pagina.locator(".insignia").first.inner_text() == "2 celdas"

        pagina.click("#btn-guardar")
        pagina.wait_for_selector("#estado:text('Guardado')")
        assert pagina.locator("#sel-senal option[value=senal-de-prueba]").count() == 1
        navegador.close()
