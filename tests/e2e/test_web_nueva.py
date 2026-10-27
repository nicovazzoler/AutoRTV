"""La web nueva en un Chromium real: entrar, subir la grilla de una señal, revisar, confirmar y exportar."""
import datetime as dt
import os
import shutil
import subprocess

import pytest

from tests.e2e.test_web import RAIZ, playwright, servidor  # noqa: F401 (servidor es un fixture)

FRONT = RAIZ / "front"
SEPARAR = {"id": "s1", "tipo": "separar", "columna": "Titulo", "modo": "separador", "valor": " - ",
           "destinos": ["Programa", "Capitulo"]}


@pytest.fixture(scope="module", autouse=True)
def web_compilada():
    if (FRONT / "dist" / "index.html").exists():
        return
    if not shutil.which("npm"):
        pytest.skip("La web nueva no está compilada y no hay npm para compilarla")
    if not (FRONT / "node_modules").exists():
        subprocess.run(["npm", "ci"], cwd=FRONT, check=True)
    subprocess.run(["npm", "run", "build"], cwd=FRONT, check=True)


def _grilla(tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    wb.active.append(["Fecha", "Hora", "Titulo"])
    wb.active.append([dt.datetime(2026, 11, 2), dt.time(6), "Memory Lane - Outkast"])
    wb.active.append([dt.datetime(2026, 11, 3), dt.time(6), "Ruta Sonora - Live"])
    archivo = tmp_path / "noviembre.xlsx"
    wb.save(archivo)
    return archivo


def test_semana_de_punta_a_punta(servidor, tmp_path):  # noqa: F811
    with playwright.sync_playwright() as p:
        try:
            navegador = p.chromium.launch(executable_path=os.environ.get("CHROMIUM"))
        except playwright.Error as e:
            pytest.skip(f"No hay Chromium para Playwright: {str(e).splitlines()[0]}")
        pagina = navegador.new_page(accept_downloads=True)
        pagina.on("dialog", lambda d: d.accept())

        pagina.goto(servidor + "/")
        pagina.wait_for_url("**/login")
        pagina.fill("input[name=usuario]", "admin")
        pagina.fill("input[name=clave]", "clave-segura")
        pagina.click("button[type=submit]")
        pagina.wait_for_url(servidor + "/")
        receta = {"id": "canal", "nombre": "Canal Demo", "entrada": {"tipo": "excel"}, "tarjetas": [SEPARAR],
                  "salida": {"columnas": []}}
        assert pagina.request.put(servidor + "/api/senales/canal", data=receta).ok
        pagina.reload()
        assert "admin." in pagina.locator("h1").inner_text()

        # Sin semana abierta, la señal lleva a subir la grilla.
        pagina.fill("input[type=search]", "canal")
        pagina.get_by_role("link", name="Canal Demo").first.click()
        pagina.wait_for_url("**/s/canal/subir")
        pagina.set_input_files("input[type=file]", str(_grilla(tmp_path)))
        pagina.get_by_role("button", name="Leer la grilla").click()
        pagina.wait_for_url("**/s/canal/revisar")
        assert pagina.locator("h1").inner_text() == "Del 2 al 3 de noviembre"

        # Base vacía: los dos programas son nuevos. "Está bien" saca uno.
        filas = pagina.locator("section[aria-label='Para revisar'] tbody tr")
        assert filas.count() == 2
        filas.first.get_by_role("button", name="Está bien").click()
        pagina.wait_for_function("document.querySelectorAll(\"section[aria-label='Para revisar'] tbody tr\").length === 1")
        assert pagina.locator(".menu-item[aria-current=page] .cuenta").inner_text() == "1"

        pagina.get_by_role("button", name="Confirmar y exportar").click()
        with pagina.expect_download() as bajada:
            pagina.get_by_role("menuitem", name="Excel (.xlsx)").click()
        assert bajada.value.suggested_filename.endswith(".xlsx")
        pagina.wait_for_selector("text=Confirmada por admin")
        assert pagina.locator("section[aria-label='Para revisar'] tbody tr").count() == 0

        # Volver al Inicio: la señal figura con la semana confirmada.
        pagina.get_by_role("link", name="Inicio").click()
        pagina.wait_for_selector("td >> text=Semana confirmada")

        pagina.get_by_role("button", name="admin").click()
        pagina.get_by_role("menuitem", name="Pasar a tema claro").click()
        assert pagina.evaluate("document.documentElement.dataset.tema") == "claro"
        pagina.get_by_role("button", name="Salir", exact=True).click()
        pagina.wait_for_url("**/login")
        navegador.close()


def test_grilla_y_base(servidor, tmp_path):  # noqa: F811
    with playwright.sync_playwright() as p:
        try:
            navegador = p.chromium.launch(executable_path=os.environ.get("CHROMIUM"))
        except playwright.Error as e:
            pytest.skip(f"No hay Chromium para Playwright: {str(e).splitlines()[0]}")
        pagina = navegador.new_page()
        pagina.on("dialog", lambda d: d.accept())
        pagina.goto(servidor + "/login")
        pagina.fill("input[name=usuario]", "admin")
        pagina.fill("input[name=clave]", "clave-segura")
        pagina.click("button[type=submit]")
        pagina.wait_for_url(servidor + "/")
        receta = {"id": "canal", "nombre": "Canal Demo", "entrada": {"tipo": "excel"}, "tarjetas": [SEPARAR],
                  "salida": {"columnas": []}}
        assert pagina.request.put(servidor + "/api/senales/canal", data=receta).ok
        grilla = _grilla(tmp_path).read_bytes()
        assert pagina.request.post(servidor + "/api/senales/canal/abierta", multipart={
            "archivo": {"name": "g.xlsx", "mimeType": "application/octet-stream", "buffer": grilla}}).ok

        # Grilla: doble clic en el capítulo, se corrige y la fila pasa a salir de la base.
        pagina.goto(servidor + "/s/canal/grilla")
        celda = pagina.locator("tbody tr").first.get_by_role("cell", name="Outkast", exact=True)
        celda.dblclick()
        pagina.fill("input[aria-label='Corregir Capitulo']", "OutKast")
        pagina.keyboard.press("Enter")
        primera = pagina.locator("tbody tr").first
        primera.locator(".marca-estado", has_text="base").wait_for()
        assert primera.get_by_role("cell", name="OutKast", exact=True).count() == 1

        # Base: la pauta corregida está; se marca y se le cambia una columna a todas las marcadas.
        pagina.get_by_role("link", name="Base").click()
        pagina.wait_for_url("**/s/canal/base")
        pagina.get_by_role("cell", name="OutKast", exact=True).wait_for()
        pagina.check("input[aria-label='Marcar todas las que se ven']")
        barra = pagina.locator("[aria-label='Cambiar las marcadas']")
        barra.locator("select").select_option("Capitulo")
        barra.locator("input").fill("Live in Atlanta")
        barra.get_by_role("button", name="Aplicar").click()
        pagina.wait_for_selector("text=Listo: 1 pautas")
        pagina.get_by_role("cell", name="Live in Atlanta", exact=True).wait_for()
        navegador.close()


def test_agente_aplica_y_senal_deshace(servidor, tmp_path):  # noqa: F811
    with playwright.sync_playwright() as p:
        try:
            navegador = p.chromium.launch(executable_path=os.environ.get("CHROMIUM"))
        except playwright.Error as e:
            pytest.skip(f"No hay Chromium para Playwright: {str(e).splitlines()[0]}")
        pagina = navegador.new_page()
        pagina.on("dialog", lambda d: d.accept())
        pagina.goto(servidor + "/login")
        pagina.fill("input[name=usuario]", "admin")
        pagina.fill("input[name=clave]", "clave-segura")
        pagina.click("button[type=submit]")
        pagina.wait_for_url(servidor + "/")
        receta = {"id": "canal", "nombre": "Canal Demo", "entrada": {"tipo": "excel"}, "tarjetas": [SEPARAR],
                  "salida": {"columnas": []}}
        assert pagina.request.put(servidor + "/api/senales/canal", data=receta).ok
        assert pagina.request.post(servidor + "/api/senales/canal/abierta", multipart={
            "archivo": {"name": "g.xlsx", "mimeType": "application/octet-stream", "buffer": _grilla(tmp_path).read_bytes()}}).ok

        # El agente grabado charla siempre lo mismo y propone pasar Titulo a mayúsculas.
        pagina.goto(servidor + "/s/canal/revisar")
        agente = pagina.locator("aside[aria-label=Agente]")
        agente.locator("textarea").fill("hola")
        agente.get_by_role("button", name="Enviar").click()
        agente.get_by_text("¡Hola! Decime qué querés cambiar.").wait_for()
        agente.locator("textarea").fill("pasá los títulos a mayúscula")
        agente.get_by_role("button", name="Proponer cambios").click()
        agente.get_by_text("Pasé los títulos a mayúsculas").wait_for()
        agente.get_by_role("button", name="Aplicar", exact=True).click()
        agente.get_by_text("(Reglas aplicadas").wait_for()

        # En Señal se ve la regla nueva como frase, y se deshace.
        pagina.locator(".menu-item", has_text="Señal").click()
        pagina.wait_for_url("**/s/canal/senal")
        pagina.locator("main .regla", has_text="Pasa Titulo a MAYÚSCULAS").wait_for()
        pagina.get_by_role("button", name="Deshacer el último cambio").click()
        pagina.locator("main .regla", has_text="Parte Titulo en Programa y Capitulo").wait_for()
        # La conversación sigue en el panel al cambiar de pantalla.
        assert agente.get_by_text("¡Hola! Decime qué querés cambiar.").count() == 1
        navegador.close()
