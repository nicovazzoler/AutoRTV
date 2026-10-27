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
