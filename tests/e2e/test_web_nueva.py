"""La web nueva en un Chromium real: entrar, subir la grilla de una señal, revisar, confirmar y exportar."""
import datetime as dt
import os
import re
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


def _navegador(p):
    try:
        return p.chromium.launch(executable_path=os.environ.get("CHROMIUM"))
    except playwright.Error as e:
        pytest.skip(f"No hay Chromium para Playwright: {str(e).splitlines()[0]}")


def _con_semana(pagina, servidor, tmp_path):
    receta = {"id": "canal", "nombre": "Canal Demo", "entrada": {"tipo": "excel"}, "tarjetas": [SEPARAR],
              "salida": {"columnas": []}}
    assert pagina.request.put(servidor + "/api/senales/canal", data=receta).ok
    assert pagina.request.post(servidor + "/api/senales/canal/abierta", multipart={
        "archivo": {"name": "g.xlsx", "mimeType": "application/octet-stream", "buffer": _grilla(tmp_path).read_bytes()}}).ok


def test_semana_de_punta_a_punta(servidor, tmp_path):
    with playwright.sync_playwright() as p:
        navegador = _navegador(p)
        pagina = navegador.new_page(accept_downloads=True)
        pagina.on("dialog", lambda d: d.accept())

        pagina.goto(servidor + "/")
        pagina.wait_for_url("**/login")
        pagina.fill("input[name=usuario]", "admin")
        pagina.fill("input[name=clave]", "clave-segura")
        pagina.click("button[type=submit]")
        pagina.wait_for_url(servidor + "/")
        for id_, nombre in [("canal", "Canal Demo"), ("otra", "Otra Señal")]:
            receta = {"id": id_, "nombre": nombre, "entrada": {"tipo": "excel"}, "tarjetas": [SEPARAR],
                      "salida": {"columnas": []}}
            assert pagina.request.put(servidor + f"/api/senales/{id_}", data=receta).ok
        pagina.reload()

        # Inicio: la lista se filtra sin importar tildes; al tocar la señal se abre su semana.
        pagina.get_by_label("Filtrar señales").fill("senal")
        pagina.wait_for_function("document.querySelectorAll('.fila-senal').length === 1")
        pagina.get_by_label("Filtrar señales").fill("canal")
        pagina.get_by_role("link", name="Canal Demo").click()
        pagina.wait_for_url("**/s/canal")
        _soltar(pagina, ".zona-archivo", _grilla(tmp_path))
        pagina.get_by_text("noviembre.xlsx").wait_for()
        pagina.get_by_role("button", name="Leer la grilla").click()
        pagina.locator("h1", has_text="Del 2 al 6 de noviembre").wait_for()

        # Base vacía: los dos programas son nuevos y se arranca en "Para revisar", agrupado por motivo.
        assert pagina.get_by_role("button", name="Para revisar · 5").get_attribute("aria-pressed") == "true"
        grupo = pagina.locator("details.grupo-motivo", has_text="Programa nuevo")
        grupo.get_by_text("2 pautas").wait_for()
        pagina.get_by_role("button", name="Por pauta").click()
        filas = pagina.locator("section[aria-label='Para revisar'] tbody tr")
        assert filas.count() == 2
        pagina.get_by_label("Filtrar Motivo").fill("ruta sonora")
        pagina.wait_for_function("document.querySelectorAll(\"section[aria-label='Para revisar'] tbody tr\").length === 1")
        pagina.get_by_label("Filtrar Motivo").fill("")
        filas.first.get_by_role("button", name="Está bien").click()
        pagina.wait_for_function("document.querySelectorAll(\"section[aria-label='Para revisar'] tbody tr\").length === 1")
        assert pagina.locator(".barra-pestana[aria-current=page] .cuenta").inner_text() == "1"  # señales con algo pendiente

        # Todas: la grilla por emisión, con filtro por columna.
        pagina.get_by_role("button", name="Todas · 5").click()
        pagina.get_by_label("Filtrar Capitulo").fill("outkast")
        pagina.wait_for_function("document.querySelectorAll('main tbody tr').length === 3")

        pagina.get_by_role("button", name="Confirmar y exportar").click()
        with pagina.expect_download() as bajada:
            pagina.get_by_role("button", name="Excel (.xlsx)").click()
        assert bajada.value.suggested_filename.endswith(".xlsx")
        pagina.wait_for_selector("text=Confirmada por admin")

        # La misma semana corregida: queda como v2 y muestra qué cambió contra la v1.
        pagina.get_by_role("button", name="Subir otra").click()
        pagina.set_input_files("input[type=file]", str(_grilla(tmp_path, "Juke Box - Ep 1", "corregida.xlsx")))
        pagina.get_by_role("button", name="Leer la grilla").click()
        pagina.locator(".antetitulo", has_text="v2 · corregida.xlsx").wait_for()
        cambios = pagina.locator("details", has_text="Cambios contra la v1")
        assert cambios.locator("summary").inner_text().endswith("2")
        assert "Ruta Sonora → Juke Box" in cambios.inner_text()

        # Exportar solo el lunes.
        pagina.get_by_role("button", name="Confirmar y exportar").click()
        pagina.get_by_label("Hasta", exact=True).fill("2026-11-02T23:59")
        with pagina.expect_download() as bajada:
            pagina.get_by_role("button", name="Excel (.xlsx)").click()
        from openpyxl import load_workbook
        with open(bajada.value.path(), "rb") as f:
            assert load_workbook(f).active.max_row == 2  # encabezado + el lunes

        # Repetir la última semana pide 7 días: esta grilla trae 5.
        pagina.get_by_role("button", name="Exportar de nuevo").click()
        pagina.get_by_label("Hasta", exact=True).fill("")
        pagina.get_by_label("Repetir la última semana").select_option(label="Hasta fin de noviembre")
        pagina.get_by_role("button", name="Excel (.xlsx)").click()
        pagina.get_by_role("alert").filter(has_text="hace falta una semana entera").wait_for()

        # Volver a la lista: confirmar pasó lo nuevo a la base y no queda nada pendiente.
        pagina.get_by_role("link", name="‹ Señales").click()
        pagina.wait_for_url(servidor + "/")
        pagina.get_by_role("link", name="Canal Demo").wait_for()
        assert pagina.locator(".fila-senal .pendiente").count() == 0

        # Historial: la carga de la semana con lo aceptado y confirmado; al tocarla se ve el detalle.
        pagina.get_by_role("navigation", name="Pantallas").get_by_role("link", name="Historial").click()
        fila = pagina.locator(".fila-historial", has_text="1 aceptada")  # la v1: la v2 se confirmó sin aceptar nada
        fila.get_by_text("Confirmada", exact=True).wait_for()
        fila.click()
        pagina.locator(".detalle-historial").get_by_text("Aceptó").first.wait_for()

        pagina.locator(".cuenta-boton").click()
        pagina.get_by_role("menuitem", name="Pasar a tema claro").click()
        assert pagina.evaluate("document.documentElement.dataset.tema") == "claro"
        pagina.get_by_role("menuitem", name="Salir").click()
        pagina.wait_for_url("**/login")
        navegador.close()


def test_base_panel_y_configuracion(servidor, tmp_path):
    with playwright.sync_playwright() as p:
        navegador, pagina = _entrar(p, servidor)
        _con_semana(pagina, servidor, tmp_path)
        assert pagina.request.post(servidor + "/api/senales/canal/abierta/confirmar").ok

        # Base › Pautas: tocar una fila abre el panel; se guarda, se deshace y se aplica a todo el programa.
        pagina.goto(servidor + "/base/canal")
        pagina.locator("tr.fila-tocable", has_text="Outkast").click()
        panel = pagina.locator("aside[aria-label=Pauta]")
        panel.get_by_label("Capitulo").fill("OutKast")
        panel.get_by_role("button", name="Guardar").click()
        panel.get_by_text("Guardado en la base").wait_for()
        pagina.get_by_role("cell", name="OutKast", exact=True).wait_for()
        panel.get_by_role("button", name="deshacer").click()
        panel.get_by_text("Deshecho").wait_for()
        pagina.get_by_role("cell", name="Outkast", exact=True).wait_for()
        panel.get_by_role("button", name="Cerrar").click()

        # Marcar varias arma la frase y cambia todas juntas.
        pagina.check("input[aria-label='Marcar todas las que se ven']")
        barra = pagina.locator("[aria-label='Cambiar las marcadas']")
        barra.get_by_label("Columna").select_option("Capitulo")
        barra.get_by_label("Valor").fill("Live in Atlanta")
        assert "en 2 pautas" in barra.inner_text()
        barra.get_by_role("button", name="Cambiar").click()
        pagina.wait_for_function("[...document.querySelectorAll('main td')].filter(t => t.innerText === 'Live in Atlanta').length === 2")

        # Base › Configuración: dos ejemplos de una vez, emparejados por la fecha del nombre.
        pagina.get_by_role("link", name="Configuración").click()
        pagina.wait_for_url("**/base/canal/config")
        pagina.get_by_role("navigation", name="Secciones").get_by_role("button", name=re.compile("^Ejemplos")).click()
        archivos = []
        for fecha in ("02-11", "09-11"):
            grilla = _grilla(tmp_path, nombre=f"grilla {fecha}.xlsx")
            ejemplo = tmp_path / f"EPG {fecha}.xlsx"
            shutil.copy(_ejemplo(tmp_path), ejemplo)
            archivos += [grilla, ejemplo]
        pagina.evaluate("""([archivos]) => {
          const t = new DataTransfer();
          for (const [datos, nombre] of archivos) t.items.add(new File([new Uint8Array(datos)], nombre));
          document.querySelector("section[aria-label=Ejemplos] .zona-archivo.chica").dispatchEvent(new DragEvent("drop", { dataTransfer: t, bubbles: true }));
        }""", [[[list(a.read_bytes()), a.name] for a in archivos]])
        pagina.get_by_role("button", name="Agregar los 2 ejemplos").click()
        pagina.get_by_text("2 ejemplos agregados").wait_for()
        assert len(pagina.request.get(servidor + "/api/senales/canal/ejemplos").json()) == 2
        navegador.close()


def test_agente_flotante_con_contexto(servidor, tmp_path):
    with playwright.sync_playwright() as p:
        navegador, pagina = _entrar(p, servidor)
        _con_semana(pagina, servidor, tmp_path)
        pedidos = []
        pagina.on("request", lambda r: pedidos.append(r.post_data_json) if "/api/asistente" in r.url and r.method == "POST" else None)

        # El agente grabado charla siempre lo mismo y propone pasar Titulo a mayúsculas.
        pagina.goto(servidor + "/s/canal")
        pagina.get_by_role("button", name="Abrir el agente").click()
        agente = pagina.locator("aside[aria-label=Agente]")
        agente.get_by_text("Viendo: Canal Demo · Semana · Para revisar").wait_for()
        agente.locator("textarea").fill("hola")
        agente.get_by_role("button", name="Enviar", exact=True).click()
        agente.get_by_text("¡Hola! Decime qué querés cambiar.").wait_for()
        assert pedidos[-1]["contexto"] == "Canal Demo · Semana · Para revisar"
        agente.locator("textarea").fill("pasá los títulos a mayúscula")
        agente.locator("textarea").press("Enter")
        agente.get_by_text("Pasé los títulos a mayúsculas").wait_for()
        agente.get_by_role("button", name="Aplicar", exact=True).click()
        agente.get_by_text("(Reglas aplicadas").wait_for()

        # En Configuración se ve la regla nueva como frase y se deshace; el agente sigue con la charla.
        pagina.get_by_role("navigation", name="Pantallas").get_by_role("link", name="Base").click()
        pagina.get_by_role("link", name="Configuración").click()
        agente.get_by_text("Viendo: Base · Configuración · Reglas").wait_for()
        assert agente.get_by_text("¡Hola! Decime qué querés cambiar.").count() == 1
        agente.get_by_role("button", name="Cerrar el agente").click()  # flota encima de la pantalla
        pagina.locator("main .regla", has_text="Pasa Titulo a MAYÚSCULAS").wait_for()
        pagina.get_by_role("button", name="Deshacer el último cambio").click()
        pagina.locator("main .regla", has_text="Parte Titulo en Programa y Capitulo").wait_for()
        navegador.close()


def test_links_viejos_redirigen(servidor):
    with playwright.sync_playwright() as p:
        navegador, pagina = _entrar(p, servidor)
        for viejo, nuevo in [("/s/canal/revisar", "/s/canal"), ("/s/canal/grilla", "/s/canal"), ("/s/canal/base", "/base/canal"),
                             ("/s/canal/senal", "/base/canal/config"), ("/todas", "/")]:
            pagina.goto(servidor + viejo)
            pagina.wait_for_url(servidor + nuevo)
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
    navegador = _navegador(p)
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
        pagina.get_by_role("button", name="admin").click()
        pagina.get_by_role("menuitem", name="Administrar").click()
        pagina.wait_for_url("**/admin")
        pestanas = pagina.get_by_role("navigation", name="Administrar")
        pagina.get_by_text("No hay avisos.").wait_for()  # arranca en Avisos
        pestanas.get_by_role("button", name="Usuarios").click()
        pagina.get_by_label("Usuario nuevo").fill("lucia")
        pagina.get_by_role("button", name="Crear", exact=True).click()
        pagina.get_by_text("La clave es").wait_for()
        clave = pagina.locator("[role=status]").inner_text().split("La clave es ")[1].split(" ")[0]
        assert pagina.request.post(servidor + "/api/login", data={"usuario": "lucia", "clave": clave}).ok

        # El login de lucia cambió la cookie de esta pestaña: se vuelve a entrar como admin.
        pagina.request.post(servidor + "/api/login", data={"usuario": "admin", "clave": "clave-segura"})
        pagina.reload()
        pestanas.get_by_role("button", name="Usuarios").click()
        pagina.locator("tr", has_text="lucia").wait_for()
        fila = pagina.locator("tr", has_text="lucia")
        fila.get_by_role("button", name="Borrar").click()
        fila.wait_for(state="detached")

        pestanas.get_by_role("button", name="Uso del agente").click()
        pagina.get_by_label("pedidos por persona y día").fill("12")
        pagina.get_by_role("button", name="Cambiar").click()
        pagina.get_by_text("Listo: cambiar el tope").wait_for()
        assert pagina.request.get(servidor + "/api/asistente/limites").json()["limite_diario"] == 12

        # Borrar una señal pide escribir su nombre.
        receta = {"id": "para-borrar", "nombre": "Para Borrar", "entrada": {"tipo": "excel"}, "tarjetas": [],
                  "salida": {"columnas": []}}
        assert pagina.request.put(servidor + "/api/senales/para-borrar", data=receta).ok
        pagina.reload()
        pestanas.get_by_role("button", name="Señales").click()
        pagina.get_by_label("Buscar señal").fill("para borrar")
        RESPUESTAS["prompt"] = "para borrar"
        pagina.locator("section[aria-label='Señales'] li", has_text="Para Borrar").get_by_role("button", name="Borrar").click()
        pagina.get_by_text("Listo: se borró la señal Para Borrar").wait_for()
        assert pagina.request.get(servidor + "/api/senales/para-borrar").status == 404
        navegador.close()


def test_banco_de_agentes_desde_administrar(servidor, tmp_path):
    with playwright.sync_playwright() as p:
        navegador, pagina = _entrar(p, servidor)
        archivos = {"grilla_cruda": {"name": "g.xlsx", "mimeType": "application/octet-stream", "buffer": _grilla(tmp_path).read_bytes()},
                    "ejemplo": {"name": "e.xlsx", "mimeType": "application/octet-stream", "buffer": _ejemplo(tmp_path).read_bytes()}}
        assert pagina.request.post(servidor + "/api/senales/crear", multipart={**archivos, "nombre": "Canal Demo"}).ok

        pagina.goto(servidor + "/admin")
        pagina.get_by_role("navigation", name="Administrar").get_by_role("button", name="Banco de agentes").click()
        banco = pagina.locator("section[aria-label='Banco de agentes']")
        assert banco.get_by_label("Canal Demo").is_checked()
        banco.get_by_role("button", name="Correr banco").click()
        banco.locator("tbody tr", has_text="reglas").wait_for(timeout=20000)
        assert banco.locator("tbody tr", has_text="lectura").count() == 1
        banco.get_by_text("Reglas: Haiku alcanzó").wait_for()
        navegador.close()


def test_corregir_una_celda_ofrece_arreglar_las_parecidas(servidor, tmp_path):
    from openpyxl import Workbook
    with playwright.sync_playwright() as p:
        navegador, pagina = _entrar(p, servidor)
        receta = {"id": "mayus", "nombre": "Mayus", "entrada": {"tipo": "excel"}, "tarjetas": [SEPARAR],
                  "salida": {"columnas": []}}
        assert pagina.request.put(servidor + "/api/senales/mayus", data=receta).ok
        wb = Workbook()
        wb.active.append(["Fecha", "Hora", "Titulo"])
        for h, titulo in enumerate(["MEMORY LANE - Outkast", "MEMORY LANE - Prince", "RUTA SONORA - Live"]):
            wb.active.append([dt.datetime(2026, 11, 2), dt.time(6 + h), titulo])
        archivo = tmp_path / "mayus.xlsx"
        wb.save(archivo)
        assert pagina.request.post(servidor + "/api/senales/mayus/abierta", multipart={
            "archivo": {"name": "mayus.xlsx", "mimeType": "application/octet-stream", "buffer": archivo.read_bytes()}}).ok

        pagina.goto(servidor + "/s/mayus")
        pagina.get_by_role("button", name="Por pauta").click()
        filas = pagina.locator("section[aria-label='Para revisar'] tbody tr")
        filas.first.locator("td.programa").dblclick()
        pagina.get_by_label("Corregir Programa").fill("Memory Lane")
        pagina.get_by_label("Corregir Programa").press("Enter")

        recorrido = pagina.get_by_role("dialog", name="Pautas parecidas")
        recorrido.get_by_text("Encontré 2 parecidas a lo que cambiaste").wait_for()
        recorrido.get_by_label("Arreglar RUTA SONORA").uncheck()
        recorrido.get_by_role("button", name="Arreglar las marcadas (1)").click()
        recorrido.wait_for(state="detached")
        grilla = pagina.request.get(servidor + "/api/senales/mayus/abierta/grilla").json()
        i = grilla["columnas"].index("Programa")
        assert [f[i] for f in grilla["filas"]] == ["Memory Lane", "Memory Lane", "RUTA SONORA"]
        navegador.close()


def test_por_motivo_se_aceptan_todas_juntas(servidor, tmp_path):
    with playwright.sync_playwright() as p:
        navegador, pagina = _entrar(p, servidor)
        receta = {"id": "grupos", "nombre": "Grupos", "entrada": {"tipo": "excel"}, "tarjetas": [SEPARAR],
                  "salida": {"columnas": []}}
        assert pagina.request.put(servidor + "/api/senales/grupos", data=receta).ok
        archivo = _grilla(tmp_path)
        assert pagina.request.post(servidor + "/api/senales/grupos/abierta", multipart={
            "archivo": {"name": "g.xlsx", "mimeType": "application/octet-stream", "buffer": archivo.read_bytes()}}).ok
        pagina.goto(servidor + "/s/grupos")
        grupo = pagina.locator("details.grupo-motivo", has_text="Programa nuevo")
        grupo.get_by_role("button", name="Están bien todas").click()
        pagina.get_by_text("Nada para revisar").wait_for()
        navegador.close()
