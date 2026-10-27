"""Humo de la web vieja (/viejo) en un Chromium real: login, subir grilla, agregar tarjeta, ver la tabla cambiar."""
import json
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
    # El asistente charla siempre lo mismo y propone siempre lo mismo: pasar Titulo a mayúsculas.
    falso = tmp_path / "asistente.json"
    falso.write_text(json.dumps([{"respuesta": "¡Hola! Decime qué querés cambiar.", "proponer_cambios": False},
                                 {"explicacion": "Pasé los títulos a mayúsculas", "columnas_salida": None,
                                  "tarjetas_json": json.dumps([{"id": "a1", "tipo": "mayus_minus",
                                                                "columnas": ["Titulo"], "modo": "MAYUS"}])}]))
    entorno = {"DATA_DIR": str(tmp_path), "ADMIN_USUARIO": "admin", "ADMIN_CLAVE": "clave-segura", "PATH": "",
               "AGENTE_FALSO": str(falso)}
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
    # Un ejemplo de otro día: no empareja ninguna fila, así la base de pautas arranca vacía.
    wb = Workbook()
    wb.active.append(["FECHA", "HORA", "Titulo"])
    wb.active.append([dt.datetime(2026, 9, 1), dt.time(5), "Otro"])
    wb.active.append([dt.datetime(2026, 9, 1), dt.time(6), "Otro más"])
    wb.active.append([dt.datetime(2026, 9, 1), dt.time(7), "Y otro"])
    ejemplo = tmp_path / "ejemplo.xlsx"
    wb.save(ejemplo)

    with playwright.sync_playwright() as p:
        # CHROMIUM permite usar un Chromium ya instalado en vez del que baja Playwright.
        try:
            navegador = p.chromium.launch(executable_path=os.environ.get("CHROMIUM"))
        except playwright.Error as e:
            pytest.skip(f"No hay Chromium para Playwright: {str(e).splitlines()[0]}")
        pagina = navegador.new_page()
        pagina.on("dialog", lambda d: d.accept())
        pagina.goto(servidor + "/viejo")
        pagina.wait_for_url("**/viejo/login")
        pagina.fill("input[name=usuario]", "admin")
        pagina.fill("input[name=clave]", "clave-segura")
        pagina.click("button[type=submit]")
        pagina.wait_for_url(servidor + "/viejo")

        pagina.click("#btn-nueva")
        pagina.fill("#form-senal input[name=nombre]", "Señal de prueba")
        pagina.set_input_files("#form-senal input[name=grilla_cruda]", str(grilla))
        pagina.set_input_files("#form-senal input[name=ejemplo]", str(ejemplo))
        pagina.click("#form-senal button[type=submit]")
        pagina.wait_for_selector("#tabla td:text('joseph prince')")
        assert pagina.input_value("#sel-senal") == "senal-de-prueba"
        # La grilla no tiene duración: el panel avisa qué columna falta para validar horarios.
        pagina.wait_for_selector("#resumen-validaciones:has-text('1 avisos')")
        assert "falta la columna de duracion" in pagina.text_content("#lista-validaciones")

        pagina.select_option("#sel-tipo", "mayus_minus")
        pagina.click("#btn-agregar")
        pagina.check(".formulario .opciones-columnas label:has-text('Titulo') input")
        pagina.select_option(".formulario select", "Titulo")
        pagina.wait_for_selector("#tabla td:text('Joseph Prince')")
        assert pagina.locator(".insignia").first.inner_text() == "2 celdas"

        pagina.click("#bloque-titulos summary")
        pagina.set_input_files("#tit-archivos", str(grilla))
        pagina.wait_for_selector("#tit-resultado:not([hidden])")
        pagina.click("#btn-tit-agregar")
        assert pagina.inner_text("#cant-titulos") == "(2)"

        pagina.click("#btn-guardar")
        pagina.wait_for_selector("#estado:text('Guardado')")
        assert pagina.locator("#sel-senal option[value=senal-de-prueba]").count() == 1

        pagina.click("#usuario")
        pagina.fill("#form-clave input[name=actual]", "clave-segura")
        pagina.fill("#form-clave input[name=nueva]", "otra-clave-1")
        pagina.fill("#form-clave input[name=repetida]", "otra-clave-2")
        pagina.click("#form-clave button[type=submit]")
        assert pagina.inner_text("#error-clave") == "Las claves nuevas no coinciden"
        pagina.fill("#form-clave input[name=repetida]", "otra-clave-1")
        pagina.click("#form-clave button[type=submit]")
        pagina.wait_for_selector("#estado:has-text('Clave cambiada')")
        assert pagina.request.post(servidor + "/api/login", data={"usuario": "admin", "clave": "otra-clave-1"}).ok

        # La charla responde en el hilo sin proponer; "Proponer cambios" va directo a la propuesta.
        pagina.fill("#in-pedido", "hola")
        pagina.press("#in-pedido", "Enter")
        pagina.wait_for_selector("#hilo li.asistente:text('¡Hola! Decime qué querés cambiar.')")
        assert pagina.is_hidden("#propuesta")
        pagina.fill("#in-pedido", "pasá los títulos a mayúsculas")
        pagina.click("#btn-proponer")
        pagina.wait_for_selector("#propuesta:not([hidden]) >> text=Pasé los títulos a mayúsculas")
        assert pagina.locator("#hilo li").all_inner_texts()[-1] == "Pasé los títulos a mayúsculas"
        assert "+ Mayúsculas / minúsculas" in pagina.inner_text("#propuesta")
        assert "− Mayúsculas / minúsculas" in pagina.inner_text("#propuesta")  # reemplaza la tarjeta manual
        pagina.click("#propuesta button:text('Ver en la tabla')")
        pagina.wait_for_selector("#tabla td:text('JOSEPH PRINCE')")
        pagina.click("#propuesta button:text('Aplicar')")
        assert pagina.locator("#lista-tarjetas > li").count() == 1
        pagina.wait_for_selector("#tabla td:text('JOSEPH PRINCE')")

        pagina.click(".pestanas button[data-pestana=reglas]")
        assert pagina.inner_text("#lista-reglas li").startswith("Pasa Titulo a MAYÚSCULAS")
        pagina.uncheck("#lista-reglas li input[type=checkbox]")
        pagina.click(".pestanas button[data-pestana=tabla]")
        pagina.wait_for_selector("#tabla td:text('joseph prince')")
        navegador.close()


def _entrar(p, servidor):
    try:
        navegador = p.chromium.launch(executable_path=os.environ.get("CHROMIUM"))
    except playwright.Error as e:
        pytest.skip(f"No hay Chromium para Playwright: {str(e).splitlines()[0]}")
    pagina = navegador.new_page()
    pagina.goto(servidor + "/viejo/login")
    pagina.fill("input[name=usuario]", "admin")
    pagina.fill("input[name=clave]", "clave-segura")
    pagina.click("button[type=submit]")
    pagina.wait_for_url(servidor + "/viejo")
    return navegador, pagina


def test_base_de_pautas_y_nombre_parecido(servidor, tmp_path):
    import datetime as dt
    from openpyxl import Workbook

    wb = Workbook()
    wb.active.append(["Fecha", "Hora", "Titulo"])
    wb.active.append([dt.datetime(2026, 10, 23), dt.time(0), "joseph prince"])
    wb.active.append([dt.datetime(2026, 10, 23), dt.time(1, 30), "praise"])
    grilla = tmp_path / "grilla.xlsx"
    wb.save(grilla)
    # El EPG terminado trae solo la primera fila: esa pauta queda conocida y la otra, nueva.
    wb = Workbook()
    wb.active.append(["FECHA", "HORA", "Programa"])
    wb.active.append([dt.datetime(2026, 10, 23), dt.time(0), "Joseph Prince"])
    ejemplo = tmp_path / "ejemplo.xlsx"
    wb.save(ejemplo)

    with playwright.sync_playwright() as p:
        navegador, pagina = _entrar(p, servidor)
        pagina.on("dialog", lambda d: d.accept())
        pagina.click("#btn-nueva")
        pagina.set_input_files("#form-senal input[name=grilla_cruda]", str(grilla))
        pagina.set_input_files("#form-senal input[name=ejemplo]", str(ejemplo))
        pagina.click("#form-senal button[type=submit]")
        assert pagina.evaluate("document.querySelector('#form-senal input[name=nombre]').validity.valueMissing")
        pagina.fill("#form-senal input[name=nombre]", "Canal Uno")
        pagina.click("#form-senal button[type=submit]")
        pagina.wait_for_selector("#tabla td:text('Joseph Prince')")
        assert pagina.locator("#tabla td.estado-pauta").all_inner_texts() == ["✔", "●"]
        assert "1 nuevas" in pagina.inner_text("#resumen-pautas")

        pagina.dblclick("#tabla tr[data-fila='2'] td:text('—')")
        pagina.fill("#tabla input.edicion", "Praise Live")
        pagina.press("#tabla input.edicion", "Enter")
        pagina.wait_for_selector("#tabla td:text('Praise Live')")
        assert pagina.locator("#tabla td.estado-pauta").all_inner_texts() == ["✔", "✎"]
        pagina.click(".pestanas button[data-pestana=base]")
        pagina.wait_for_selector("#tabla-base td:text('Praise Live')")
        assert "2 pautas · 1 revisadas · 1 editadas" in pagina.inner_text("#base-resumen")

        pagina.click("#btn-nueva")
        pagina.fill("#form-senal input[name=nombre]", "canal uno!")
        pagina.set_input_files("#form-senal input[name=grilla_cruda]", str(grilla))
        pagina.set_input_files("#form-senal input[name=ejemplo]", str(ejemplo))
        pagina.click("#form-senal button[type=submit]")
        pagina.wait_for_selector("#dialogo-parecidas[open]")
        assert pagina.inner_text("#parecidas-titulo") == 'Ya existe la señal "canal uno!"'
        assert not pagina.is_visible("#btn-parecidas-crear")
        pagina.click("#parecidas-lista button")
        pagina.wait_for_selector("#estado:has-text('lista')")
        assert len(pagina.request.get(servidor + "/api/senales/canal-uno/ejemplos").json()) == 2
        pagina.screenshot(path=str(tmp_path / "base.png"), full_page=True)
        navegador.close()


def test_tarjetas_agrupadas_por_tema(servidor, tmp_path):
    import datetime as dt
    from openpyxl import Workbook

    wb = Workbook()
    wb.active.append(["Fecha", "Hora", "Titulo"])
    wb.active.append([dt.datetime(2026, 10, 23), dt.time(0), " a  b "])
    grilla = tmp_path / "grilla.xlsx"
    wb.save(grilla)
    receta = {"id": "grupos", "nombre": "Grupos", "entrada": {"tipo": "excel"}, "salida": {"columnas": []},
              "tarjetas": [
                  {"id": "l1", "tipo": "limpiar_espacios"},
                  {"id": "l2", "tipo": "reemplazar", "columnas": ["Titulo"], "buscar": "a", "por": "A"},
                  {"id": "c1", "tipo": "numerar"},
                  {"id": "l3", "tipo": "quitar", "columnas": ["Titulo"], "texto": "b"},
                  {"id": "c2", "tipo": "renombrar", "mapa": {"NoExiste": "X"}},
              ]}

    with playwright.sync_playwright() as p:
        try:
            navegador = p.chromium.launch(executable_path=os.environ.get("CHROMIUM"))
        except playwright.Error as e:
            pytest.skip(f"No hay Chromium para Playwright: {str(e).splitlines()[0]}")
        pagina = navegador.new_page()
        pagina.goto(servidor + "/viejo/login")
        pagina.fill("input[name=usuario]", "admin")
        pagina.fill("input[name=clave]", "clave-segura")
        pagina.click("button[type=submit]")
        pagina.wait_for_url(servidor + "/viejo")
        assert pagina.request.put(servidor + "/api/senales/grupos", data=receta).ok
        pagina.reload()
        pagina.select_option("#sel-senal", "grupos")
        pagina.set_input_files("#in-archivo", str(grilla))
        pagina.wait_for_selector("#tabla td:text('A')")

        # Solo se juntan las seguidas: limpieza, columnas, limpieza, columnas.
        grupos = pagina.locator("#lista-tarjetas > li.grupo")
        assert grupos.count() == 4
        assert pagina.inner_text("#res-tarjetas") == "(5 en 4 grupos)"
        assert "Limpieza de texto · 2 tarjetas" in grupos.nth(0).inner_text()
        # El bloque cerrado suma las celdas: " a  b " → "a b" → "A b" son 2 cambios.
        assert "2 celdas" in grupos.nth(0).inner_text()
        assert pagina.locator("#lista-tarjetas li.tarjeta").count() == 1  # solo el bloque con error se abre
        assert "1 con error" in grupos.nth(3).inner_text()

        grupos.nth(0).locator(".cabeza-grupo").click()
        assert pagina.locator("#lista-tarjetas li.tarjeta").count() == 3
        pagina.click("#btn-abrir-todo")
        assert pagina.locator("#lista-tarjetas li.tarjeta").count() == 5
        pagina.click("#btn-cerrar-todo")
        assert pagina.locator("#lista-tarjetas li.tarjeta").count() == 1

        with pagina.expect_download() as descarga:
            pagina.click("#btn-exportar-receta")
        exportada = json.loads(open(descarga.value.path(), encoding="utf-8").read())
        assert [t["id"] for t in exportada["tarjetas"]] == ["l1", "l2", "c1", "l3", "c2"]
        copia = tmp_path / "copia.json"
        copia.write_text(json.dumps({**exportada, "id": "grupos-copia", "nombre": "Copia"}), encoding="utf-8")
        pagina.set_input_files("#in-receta", str(copia))
        pagina.wait_for_selector("#estado:has-text('importada')")
        assert pagina.inner_text("#res-tarjetas") == "(5 en 4 grupos)"
        pagina.click("#btn-guardar")
        pagina.wait_for_selector("#sel-senal option[value=grupos-copia]", state="attached")
        navegador.close()
