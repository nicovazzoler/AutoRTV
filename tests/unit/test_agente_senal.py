import datetime as dt
import io
import json

import pandas as pd
import pytest
from openpyxl import Workbook

from app import almacen, armados, auth, caja, conversaciones, pautas
from app.agent import cliente as proveedores
from app.agent import lectura, senal
from app.caja import datos, pasos
from app.engine import model as m
from app.inputs import varios
from tests.unit.test_api import excel

COLUMNAS = ["FECHA", "HORA", "PROGRAMA", "DUR"]
FIN = "Fin de transmisión"
GRILLA = pd.DataFrame([[dt.datetime(2026, 11, d), dt.time(h), p, dur] for d in (2, 3, 4)
                       for h, p, dur in ((6, "Noticias", 120), (8, "Cine", 960))], columns=COLUMNAS)
# Como AGAPE: el EPG terminado agrega a mano "Fin de transmisión" a las 00:00, que la grilla no trae.
ESPERADO = pd.DataFrame([f for d in (2, 3, 4) for f in (
    [dt.datetime(2026, 11, d), dt.time(6), "Noticias", 120], [dt.datetime(2026, 11, d), dt.time(8), "Cine", 960],
    [dt.datetime(2026, 11, d + 1), dt.time(0), FIN, 360])], columns=COLUMNAS)
FINAL = '''
import datetime as dt
def ajustar(filas):
    salida = []
    for i, f in enumerate(filas):
        salida.append(f)
        sigue = filas[i + 1] if i + 1 < len(filas) else None
        if sigue is None or sigue["FECHA"] != f["FECHA"]:
            dia = dt.datetime.strptime(f["FECHA"], "%d/%m/%Y") + dt.timedelta(days=1)
            salida.append({"FECHA": dia.strftime("%d/%m/%Y"), "HORA": "00:00", "PROGRAMA": "Fin de transmisión", "DUR": 360})
    return salida
'''
EXPLICACION = "Después del último programa de cada día agrega Fin de transmisión a las 00:00."


@pytest.fixture
def con_caja(monkeypatch):
    if not caja.instalada():
        pytest.skip("La caja no está instalada: npm ci en caja/")
    monkeypatch.setattr(pasos, "apagada", lambda: None)  # la autoprueba se prueba en test_caja


class Guion(proveedores.Grabado):
    """El agente de la señal con pasos fijos: cada paso es una lista de (herramienta, datos) o el texto final."""
    con_agente_de_la_senal = True

    def __init__(self, pasos_, respuestas=("no es JSON",)):
        super().__init__(list(respuestas))
        self.guion, self.resultados, self.contexto = list(pasos_), [], ""

    def con_herramientas(self, sistema, mensajes, herramientas, modelo=None, effort="low", max_tokens=4000):
        ultimo = mensajes[-1]["content"]
        if isinstance(ultimo, list):
            self.resultados.append([b["content"] for b in ultimo])
        else:
            self.contexto = ultimo
        paso = self.guion.pop(0) if self.guion else "Listo."
        if isinstance(paso, str):
            return proveedores.Respuesta(paso, bloques=[{"type": "text", "text": paso}], parar="end_turn", modelo=modelo)
        bloques = [{"type": "tool_use", "id": f"t{len(self.resultados)}-{i}", "name": n, "input": d} for i, (n, d) in enumerate(paso)]
        return proveedores.Respuesta("", bloques=bloques, parar="tool_use", modelo=modelo, tokens_entrada=2000, tokens_salida=200)


def _ejemplo() -> senal.EjemploCrudo:
    return senal.EjemploCrudo("ejemplo-1", excel(GRILLA), pd.read_excel(io.BytesIO(excel(ESPERADO)), dtype=object))


def _receta(**cambios) -> m.Senal:
    return m.Senal(**{"id": "agape", "nombre": "Agape", "entrada": {"tipo": "excel"}, "tarjetas": [],
                      "salida": m.Salida(columnas=[]), **cambios})


def test_el_archivo_y_el_epg_pasan_a_datos_simples_y_vuelven():
    wb = Workbook()
    wb.active.append(["Fecha", "Hora", "Programa"])
    wb.active.append([dt.datetime(2026, 11, 2), dt.time(6), "Noticias"])
    wb.active.merge_cells("C2:D2")
    buf = io.BytesIO()
    wb.save(buf)
    hoja = datos.del_archivo(buf.getvalue(), "g.xlsx")["hojas"][0]
    assert hoja["celdas"][1][:3] == ["2026-11-02T00:00:00", "06:00:00", "Noticias"] and hoja["combinadas"] == [[1, 2, 2, 4]]
    zip_ = datos.del_archivo(varios.empaquetar([("a.txt", b"06:00 Noticias"), ("b.xlsx", buf.getvalue())]))
    assert [(a["nombre"], a["tipo"]) for a in zip_["archivos"]] == [("a.txt", "texto"), ("b.xlsx", "excel")]

    filas = datos.de_tabla(GRILLA.head(2))
    assert filas[0] == {"FECHA": "02/11/2026", "HORA": "06:00", "PROGRAMA": "Noticias", "DUR": 120, "_fila": 0}
    nueva = {"FECHA": "02/11/2026", "HORA": "07:00", "PROGRAMA": FIN, "DUR": "60", "Extra": "x"}
    tabla, origen = datos.a_tabla([filas[0], nueva, filas[1]], GRILLA.head(2))
    assert origen == [0, None, 1] and list(tabla.columns) == COLUMNAS + ["Extra"]
    assert tabla.iloc[1]["FECHA"] == dt.datetime(2026, 11, 2) and tabla.iloc[1]["HORA"] == dt.time(7)
    assert tabla.iloc[1]["DUR"] == 60  # la columna era de números: vuelve a número


def test_el_paso_final_agrega_filas_y_la_semana_las_muestra_sin_pasarlas_a_la_base(cliente, con_caja):
    codigo = m.Codigo(codigo=FINAL, explicacion=EXPLICACION, comprobado=True)
    almacen.guardar(_receta(final=codigo), "admin")
    r = cliente.post("/api/senales/agape/abierta", files={"archivo": ("g.xlsx", excel(GRILLA))})
    assert r.status_code == 200, r.text
    semana = cliente.get("/api/senales/agape/abierta").json()
    assert semana["resumen"]["filas"] == 9 and semana["resumen"]["revisar"] == 6  # sin base, lo de la grilla es nuevo
    fin = next(g for g in semana["nuevas"] if g["salida"].get("PROGRAMA") == FIN)
    assert fin["veces"] == 3 and fin["hash"].startswith(pautas.GENERADA)
    r = cliente.post("/api/senales/agape/abierta/celda", json={"fila": fin["filas"][0], "columna": "PROGRAMA", "valor": "Otra"})
    assert r.status_code == 422 and "paso final" in r.json()["detail"]
    assert cliente.post("/api/senales/agape/abierta/confirmar").status_code == 200
    base = pautas.base("agape")
    assert base and not any(h.startswith(pautas.GENERADA) for h in base)  # lo de la grilla sí, lo agregado no


def test_un_codigo_sin_comprobar_deja_la_semana_entera_para_revisar(cliente, con_caja):
    almacen.guardar(_receta(final=m.Codigo(codigo=FINAL, explicacion=EXPLICACION)), "admin")
    cliente.post("/api/senales/agape/abierta", files={"archivo": ("g.xlsx", excel(GRILLA))})
    semana = cliente.get("/api/senales/agape/abierta").json()
    assert semana["resumen"]["revisar"] == semana["resumen"]["filas"] == 9
    assert "codigo_sin_comprobar" in semana["revisar"][0]["codigos"]


def test_el_codigo_lo_escribe_el_agente_y_el_admin_lo_apaga(cliente):
    receta = _receta(final=m.Codigo(codigo=FINAL, explicacion=EXPLICACION, comprobado=True)).model_dump(mode="json")
    assert cliente.put("/api/senales/agape", json=receta).status_code == 200
    guardada = almacen.leer("agape").final
    assert not guardada.comprobado and guardada.autor == "admin"  # puesto a mano: queda sin comprobar
    almacen.guardar(_receta(final=guardada.model_copy(update={"comprobado": True})), "agente")

    auth.crear_usuario("ana", "clave-segura")
    assert cliente.post("/api/login", json={"usuario": "ana", "clave": "clave-segura"}).status_code == 200
    otro = {**receta, "final": {**receta["final"], "codigo": FINAL + "\n# otra cosa"}}
    assert cliente.put("/api/senales/agape", json=otro).status_code == 403
    assert cliente.post("/api/senales/agape/codigo", json={"donde": "final", "activo": False}).status_code == 403
    sin_codigo = {**receta, "final": None, "nombre": "Agape sin código"}
    assert cliente.put("/api/senales/agape", json=sin_codigo).status_code == 200  # sacarlo sí se puede

    almacen.guardar(_receta(final=guardada.model_copy(update={"comprobado": True})), "agente")
    assert cliente.post("/api/login", json={"usuario": "admin", "clave": "clave-segura"}).status_code == 200
    assert cliente.post("/api/senales/agape/codigo", json={"donde": "final", "activo": False}).json()["activo"] is False
    assert almacen.leer("agape").final.activo is False


def test_el_agente_ve_las_filas_que_faltan_las_agrega_con_codigo_y_guarda_comprobado(con_caja):
    guion = Guion([[("ver_resultado", {})], [("probar", {"final_codigo": FINAL})],
                   [("guardar", {"explicacion": "Agregué Fin de transmisión."})],
                   [("guardar", {"explicacion": "Agregué Fin de transmisión.", "explicacion_codigo": EXPLICACION})]])
    t = senal.trabajar(_receta(), [_ejemplo()], guion)
    vista = json.loads(guion.resultados[0][0])
    assert vista["cuantas_faltan"] == 2 and vista["faltan_en_el_epg"][0]["tenia_que_quedar"]["PROGRAMA"] == FIN
    prueba = json.loads(guion.resultados[1][0])["ejemplos"]["ejemplo-1"]
    assert (prueba["filas_que_faltan_hoy"], prueba["filas_que_faltan_con_esto"]) == (2, 0)
    assert "explicacion_codigo" in guion.resultados[2][0]  # sin explicar el código no se guarda
    assert t.receta is not None and t.codigo == ["paso final"]
    assert t.receta.final.comprobado and t.receta.final.explicacion == EXPLICACION
    assert "Le faltaban 2 filas y ahora ninguna" in t.resultado


def test_no_se_guarda_algo_que_empeora_el_ejemplo(con_caja):
    rompe = "def ajustar(filas):\n    return [dict(f, PROGRAMA='?') for f in filas]"
    guion = Guion([[("probar", {"final_codigo": rompe})], [("guardar", {"explicacion": "x", "explicacion_codigo": "y"})],
                   "No encontré cómo mejorarlo."])
    t = senal.trabajar(_receta(), [_ejemplo()], guion)
    assert "No se guarda" in guion.resultados[1][0] and t.receta is None and t.final == "No encontré cómo mejorarlo."


def test_el_agente_escribe_un_lector_para_una_grilla_que_ninguna_lectura_entiende(con_caja):
    rara = "\n".join(f"== {d:02d}/11/2026 ==\n06h00 · Noticias\n08h00 · Cine" for d in (2, 3, 4)).encode()
    esperado = pd.read_excel(io.BytesIO(excel(pd.DataFrame(
        [[dt.datetime(2026, 11, d), dt.time(h), p] for d in (2, 3, 4) for h, p in ((6, "Noticias"), (8, "Cine"))],
        columns=["Fecha", "Hora", "Programa"]))), dtype=object)
    lector = '''
import re
def leer(datos):
    filas, dia = [], None
    for linea in datos["texto"].splitlines():
        if m := re.match(r"== (\\d\\d)/(\\d\\d)/(\\d{4}) ==", linea):
            dia = f"{m[3]}-{m[2]}-{m[1]}"
        elif m := re.match(r"(\\d\\d)h(\\d\\d) · (.+)", linea):
            filas.append({"Fecha": dia, "Hora": f"{m[1]}:{m[2]}", "Programa": m[3]})
    return filas
'''
    receta = m.Senal(id="rara", nombre="Rara", entrada={"tipo": "texto"}, tarjetas=[], salida=m.Salida(columnas=[]))
    guion = Guion([[("ver_archivo", {})], [("probar", {"lector_codigo": lector})],
                   [("guardar", {"explicacion": "La grilla trae los días como «== dd/mm/aaaa ==».",
                                 "explicacion_codigo": "Lee cada día y cada «06h00 · Programa»."})]])
    t = senal.trabajar(receta, [senal.EjemploCrudo("e", rara, esperado)], guion)
    assert "06h00 · Noticias" in guion.resultados[0][0]
    assert t.codigo == ["lector"] and t.receta.entrada.lector.comprobado and t.despues == 100.0
    tabla = senal.inputs.leer(rara, t.receta.entrada)
    assert len(tabla) == 6
    assert tabla.iloc[0].to_dict() == {"Fecha": dt.datetime(2026, 11, 2), "Hora": dt.time(6), "Programa": "Noticias"}


def test_al_crear_la_senal_el_agente_de_la_senal_sigue_donde_haiku_no_llega_y_avisa_al_admin(cliente, con_caja,
                                                                                            monkeypatch):
    monkeypatch.setattr(armados, "EN_HILO", False)
    guion = Guion([[("probar", {"final_codigo": FINAL})],
                   [("guardar", {"explicacion": "Agregué Fin de transmisión.", "explicacion_codigo": EXPLICACION})]])
    monkeypatch.setattr(proveedores, "proveedor_configurado", lambda: guion)
    r = cliente.post("/api/senales/crear", files={"grilla_cruda": ("g.xlsx", excel(GRILLA)),
                                                  "ejemplo": ("e.xlsx", excel(ESPERADO))}, data={"nombre": "Agape"})
    assert r.status_code == 200 and r.json()["armando_reglas"], r.text
    armado = cliente.get("/api/senales/agape/reglas/armado").json()
    assert armado["estado"] == "aplicado" and "Le faltaban 2 filas" in armado["mensaje"], armado
    assert almacen.leer("agape").final.comprobado
    (aviso,) = [a for a in conversaciones.avisos() if a["tipo"] == "codigo"]
    assert aviso["senal_id"] == "agape" and EXPLICACION in aviso["detalle"]


def test_el_agente_de_lectura_no_escribe_codigo():
    codigo = {"tipo": "varios", "cada_uno": {"tipo": "codigo", "lector": {"codigo": "def leer(d):\n    return []"}}}
    _, _, problemas = lectura._probar(b"06:00 Noticias", {"entrada_json": json.dumps(codigo)}, None)
    assert problemas == ["Acá no se escribe código: elegí una de las lecturas que hay."]


def test_el_banco_mide_el_agente_de_la_senal_sin_guardar_nada(con_caja):
    from app.agent import banco
    guion = Guion([[("probar", {"final_codigo": FINAL})],
                   [("guardar", {"explicacion": "Agregué Fin de transmisión.", "explicacion_codigo": EXPLICACION})]])
    par = banco.Par("Agape", excel(GRILLA), excel(ESPERADO), "agape", receta=_receta().model_dump(mode="json"))
    r = banco.probar_par(par, guion, banco.Caja(5.0), pasos=["agente"])
    assert r["agente"]["logrado"] and r["agente"]["codigo"] == ["paso final"] and "Le faltaban 2" in r["agente"]["resultado"]
    assert banco.resumen([banco.limpio(r)])["agente"] == {"senales": 1, "al_100": 1, "mejoro": 0, "con_codigo": 1}
    assert almacen.listar() == []  # el banco no guarda la receta


def test_una_vista_previa_corre_el_codigo_guardado_y_no_el_que_trae_el_pedido(cliente, con_caja):
    almacen.guardar(_receta(), "admin")
    tabla_id = cliente.post("/api/tablas", files={"archivo": ("g.xlsx", excel(GRILLA))}).json()["tabla_id"]
    con_codigo = _receta(final=m.Codigo(codigo=FINAL, comprobado=True)).model_dump(mode="json")
    assert cliente.post("/api/preview", json={"tabla_id": tabla_id, "senal": con_codigo}).json()["total_filas"] == 6
    almacen.guardar(_receta(final=m.Codigo(codigo=FINAL, comprobado=True)), "agente")
    assert cliente.post("/api/preview", json={"tabla_id": tabla_id, "senal": con_codigo}).json()["total_filas"] == 9


def test_un_lector_en_codigo_que_no_puede_con_la_grilla_no_se_cambia_solo(cliente, monkeypatch):
    monkeypatch.setattr(pasos, "apagada", lambda: "la caja está apagada")
    lector = m.EntradaCodigo(tipo="codigo", lector=m.Codigo(codigo="def leer(datos):\n    return []", comprobado=True))
    almacen.guardar(_receta(entrada=lector), "agente")
    r = cliente.post("/api/senales/agape/abierta", files={"archivo": ("g.xlsx", excel(GRILLA))})
    assert r.status_code == 422 and "actualice el lector" in r.json()["detail"]
    assert almacen.leer("agape").entrada.tipo == "codigo"
