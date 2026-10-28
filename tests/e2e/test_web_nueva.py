"""La web nueva en un Chromium real: entrar, subir la grilla de una señal, revisar, confirmar y exportar."""
import datetime as dt
import os
import shutil
import subprocess

import pytest

from tests.e2e.conftest import RAIZ

playwright = pytest.importorskip("playwright.sync_api")

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


# Lo que contesta el navegador cuando la página pide escribir algo (prompt).
RESPUESTAS = {}


def _grilla(tmp_path, segundo="Ruta Sonora - Live", nombre="noviembre.xlsx"):
    from openpyxl import Workbook

    wb = Workbook()
    wb.active.append(["Fecha", "Hora", "Titulo"])
    for dia in range(2, 7):
        titulo = "Memory Lane - Outkast" if dia % 2 == 0 else segundo
        wb.active.append([dt.datetime(2026, 11, dia), dt.time(6), titulo])
    archivo = tmp_path / nombre
    wb.save(archivo)
    return archivo


def _soltar(pagina, selector, archivo):
    """Arrastra un archivo del disco y lo suelta sobre el elemento, como haría una persona."""
    pagina.evaluate("""([selector, datos, nombre]) => {
      const transferencia = new DataTransfer();
      transferencia.items.add(new File([new Uint8Array(datos)], nombre));
      document.querySelector(selector).dispatchEvent(new DragEvent("drop", { dataTransfer: transferencia, bubbles: true }));
    }""", [selector, list(archivo.read_bytes()), archivo.name])


def test_semana_de_punta_a_punta(servidor, tmp_path):
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
        _soltar(pagina, ".zona-archivo", _grilla(tmp_path))
        pagina.get_by_text("noviembre.xlsx").wait_for()
        pagina.get_by_role("button", name="Leer la grilla").click()
        pagina.wait_for_url("**/s/canal/revisar")
        assert pagina.locator("h1").inner_text() == "Del 2 al 6 de noviembre"

        # Base vacía: los dos programas son nuevos. "Está bien" saca uno.
        filas = pagina.locator("section[aria-label='Para revisar'] tbody tr")
        assert filas.count() == 2
        pagina.get_by_label("Filtrar Motivo").fill("ruta sonora")
        pagina.wait_for_function("document.querySelectorAll(\"section[aria-label='Para revisar'] tbody tr\").length === 1")
        pagina.get_by_label("Filtrar Motivo").fill("")
        pagina.wait_for_function("document.querySelectorAll(\"section[aria-label='Para revisar'] tbody tr\").length === 2")
        filas.first.get_by_role("button", name="Está bien").click()
        pagina.wait_for_function("document.querySelectorAll(\"section[aria-label='Para revisar'] tbody tr\").length === 1")
        assert pagina.locator(".menu-item[aria-current=page] .cuenta").inner_text() == "2"  # Ruta Sonora sale dos veces

        pagina.get_by_role("button", name="Confirmar y exportar").click()
        with pagina.expect_download() as bajada:
            pagina.get_by_role("button", name="Excel (.xlsx)").click()
        assert bajada.value.suggested_filename.endswith(".xlsx")
        pagina.wait_for_selector("text=Confirmada por admin")
        assert pagina.locator("section[aria-label='Para revisar'] tbody tr").count() == 0

        # La misma semana corregida: queda como v2 y muestra qué cambió contra la v1.
        pagina.get_by_role("link", name="Subir otra grilla").click()
        pagina.get_by_text("y confirmada por admin").wait_for()
        pagina.set_input_files("input[type=file]", str(_grilla(tmp_path, "Juke Box - Ep 1", "corregida.xlsx")))
        pagina.get_by_role("button", name="Leer la grilla").click()
        pagina.wait_for_url("**/s/canal/revisar")
        assert "v2 · corregida.xlsx" in pagina.locator(".antetitulo").inner_text()
        cambios = pagina.locator("details", has_text="Cambios contra la v1")
        assert cambios.locator("summary").inner_text().endswith("2")
        assert "Ruta Sonora → Juke Box" in cambios.inner_text()

        # Exportar solo el lunes.
        pagina.get_by_role("button", name="Confirmar y exportar").click()
        pagina.get_by_label("Hasta").fill("2026-11-02T23:59")
        with pagina.expect_download() as bajada:
            pagina.get_by_role("button", name="Excel (.xlsx)").click()
        from openpyxl import load_workbook
        with open(bajada.value.path(), "rb") as f:
            assert load_workbook(f).active.max_row == 2  # encabezado + el lunes

        # Cambiar de señal desde el menú.
        pagina.locator(".menu-senal").click()
        assert pagina.get_by_role("dialog", name="Cambiar de señal").get_by_role("button", name="Canal Demo").is_visible()
        pagina.keyboard.press("Escape")

        # Volver al Inicio: la señal figura con la semana confirmada.
        pagina.get_by_role("link", name="Inicio").click()
        pagina.wait_for_selector("td >> text=Semana confirmada")

        pagina.get_by_role("button", name="admin").click()
        pagina.get_by_role("menuitem", name="Pasar a tema claro").click()
        assert pagina.evaluate("document.documentElement.dataset.tema") == "claro"
        pagina.get_by_role("button", name="Salir", exact=True).click()
        pagina.wait_for_url("**/login")
        navegador.close()


def test_grilla_y_base(servidor, tmp_path):
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


def test_agente_aplica_y_senal_deshace(servidor, tmp_path):
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
        agente.get_by_role("button", name="Abrir el agente").click()  # arranca plegado para dejar ancho a la tabla
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


def _ejemplo(tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    wb.active.append(["FECHA", "HORA", "Programa", "Capitulo"])
    wb.active.append([dt.datetime(2026, 11, 2), dt.time(6), "Memory Lane", "Outkast"])
    wb.active.append([dt.datetime(2026, 11, 3), dt.time(6), "Ruta Sonora", "Live"])
    archivo = tmp_path / "ejemplo.xlsx"
    wb.save(archivo)
    return archivo


def _entrar(p, servidor):
    try:
        navegador = p.chromium.launch(executable_path=os.environ.get("CHROMIUM"))
    except playwright.Error as e:
        pytest.skip(f"No hay Chromium para Playwright: {str(e).splitlines()[0]}")
    pagina = navegador.new_page()
    pagina.on("dialog", lambda d: d.accept(RESPUESTAS.get("prompt", "")) if d.type == "prompt" else d.accept())
    pagina.goto(servidor + "/login")
    pagina.fill("input[name=usuario]", "admin")
    pagina.fill("input[name=clave]", "clave-segura")
    pagina.click("button[type=submit]")
    pagina.wait_for_url(servidor + "/")
    return navegador, pagina


def test_nueva_senal_y_parecida(servidor, tmp_path):
    with playwright.sync_playwright() as p:
        navegador, pagina = _entrar(p, servidor)
        grilla, ejemplo = str(_grilla(tmp_path)), str(_ejemplo(tmp_path))

        def completar(nombre):
            pagina.goto(servidor + "/nueva")
            pagina.get_by_label("Nombre de la señal").fill(nombre)
            pagina.locator("section[aria-label='Paso 2'] input[type=file]").first.set_input_files(grilla)
            pagina.locator("section[aria-label='Paso 2'] input[type=file]").nth(1).set_input_files(ejemplo)
            pagina.get_by_role("button", name="Crear la señal").click()

        completar("Canal Demo")
        pagina.get_by_text("Base cargada:").wait_for()
        pagina.get_by_role("link", name="Ver la señal").wait_for()
        assert pagina.request.get(servidor + "/api/senales/canal-demo").ok

        # Un nombre casi igual pide confirmación; se puede sumar como ejemplo de la que ya está.
        completar("Canal Demo 2")
        pagina.get_by_role("button", name="Agregar como ejemplo de Canal Demo").click()
        pagina.get_by_text("quedó como ejemplo de").wait_for()
        assert len(pagina.request.get(servidor + "/api/senales/canal-demo/ejemplos").json()) == 2
        navegador.close()


def test_admin_usuarios_y_tope(servidor):
    with playwright.sync_playwright() as p:
        navegador, pagina = _entrar(p, servidor)
        pagina.locator(".menu-item", has_text="Admin").click()
        pagina.wait_for_url("**/admin")
        pagina.get_by_label("Usuario nuevo").fill("lucia")
        pagina.get_by_role("button", name="Crear", exact=True).click()
        pagina.get_by_text("La clave es").wait_for()
        clave = pagina.locator("[role=status]").inner_text().split("La clave es ")[1].split(" ")[0]
        assert pagina.request.post(servidor + "/api/login", data={"usuario": "lucia", "clave": clave}).ok

        # El login de lucia cambió la cookie de esta pestaña: se vuelve a entrar como admin.
        pagina.request.post(servidor + "/api/login", data={"usuario": "admin", "clave": "clave-segura"})
        pagina.reload()
        pagina.locator("tr", has_text="lucia").wait_for()  # si no, al terminar de cargar pisa el tope escrito
        pagina.get_by_label("pedidos por persona y día").fill("12")
        pagina.get_by_role("button", name="Cambiar").click()
        pagina.get_by_text("Listo: cambiar el tope").wait_for()
        assert pagina.request.get(servidor + "/api/asistente/limites").json()["limite_diario"] == 12

        fila = pagina.locator("tr", has_text="lucia")
        fila.get_by_role("button", name="Borrar").click()
        fila.wait_for(state="detached")

        # Borrar una señal pide escribir su nombre.
        receta = {"id": "para-borrar", "nombre": "Para Borrar", "entrada": {"tipo": "excel"}, "tarjetas": [],
                  "salida": {"columnas": []}}
        assert pagina.request.put(servidor + "/api/senales/para-borrar", data=receta).ok
        pagina.reload()
        pagina.get_by_label("Buscar señal").last.fill("para borrar")
        RESPUESTAS["prompt"] = "para borrar"
        pagina.locator("section[aria-label='Señales'] li", has_text="Para Borrar").get_by_role("button", name="Borrar").click()
        pagina.get_by_text("Listo: se borró la señal Para Borrar").wait_for()
        assert pagina.request.get(servidor + "/api/senales/para-borrar").status == 404
        navegador.close()
