import datetime as dt

import pandas as pd

from app import pautas
from tests.unit.test_api import excel

CRUDO = pd.DataFrame({
    "Fecha": [dt.datetime(2026, 10, 1)] * 3,
    "Hora": [dt.time(6), dt.time(7), dt.time(8)],
    "Duracion": [dt.time(1), dt.time(1), dt.time(1)],
    "Titulo": ["Memory Lane - Outkast", "Koko Pop", "Memory Lane - Outkast"],
    "Sinopsis": ["Live sets", "Pop", "Live sets"],
}, dtype=object)
ESPERADO = pd.DataFrame({
    "FECHA": [dt.datetime(2026, 10, 1)] * 3,
    "HORA": [dt.time(6), dt.time(7), dt.time(8)],
    "DUR": [60, 60, 60],
    "Programa": ["Memory Lane", "Koko Pop", "Memory Lane"],
    "Capitulo": ["Outkast", None, "Outkast"],
}, dtype=object)


def test_hash_ignora_mayusculas_tildes_signos_y_horario():
    a = pautas.hash_pauta({"t": "Canción: ¡Ya!", "n": 3.0})
    assert a == pautas.hash_pauta({"t": "  cancion ya ", "n": 3})
    assert a != pautas.hash_pauta({"t": "cancion ya", "n": 4})
    otro_dia = CRUDO.assign(Fecha=dt.datetime(2026, 10, 8), Hora=dt.time(23), Duracion=dt.time(0, 30))
    assert [pautas.hash_pauta(f) for f in pautas.crudas(CRUDO)] == [pautas.hash_pauta(f) for f in pautas.crudas(otro_dia)]


def test_columnas_de_horario_por_nombre_y_por_tipo():
    tabla = CRUDO.rename(columns={"Duracion": "Largo"}).assign(**{"Schedule Item Calendar Start Time": "06:00",
                                                                 "Legend": "x"})
    assert pautas.columnas_de_horario(tabla) == ["Fecha", "Hora", "Largo", "Schedule Item Calendar Start Time"]


def test_columnas_de_contenido_dejan_afuera_numeracion_y_horario():
    columnas = ["N", "DIA", "FECHA", "HORA", "DUR", "Duración", "TIT ING", "Año"]
    assert pautas.columnas_de_contenido(columnas) == ["TIT ING", "Año"]


def test_aplicar_pisa_contenido_y_respeta_horario():
    ejemplo, conflictos = pautas.desde_ejemplo(CRUDO, ESPERADO)
    assert len(ejemplo) == 2 and conflictos == 0
    base = {h: {"salida": p["salida"], "estado": "revisada"} for h, p in ejemplo.items()}
    h_koko = pautas.hash_pauta(pautas.crudas(CRUDO)[1])
    base[h_koko]["estado"] = "editada"
    procesada = CRUDO.assign(Hora=[dt.time(6, 5), dt.time(7, 5), dt.time(8, 5)])
    nueva = pd.concat([CRUDO, CRUDO.iloc[[0]].assign(Titulo="Otro")], ignore_index=True)

    df, estados, hashes = pautas.aplicar(nueva, pd.concat([procesada, procesada.iloc[[0]]], ignore_index=True), base)
    assert estados == ["conocida", "editada", "conocida", "nueva"]
    assert list(df["Programa"]) == ["Memory Lane", "Koko Pop", "Memory Lane", None]
    assert df["Hora"][0] == dt.time(6, 5)  # el horario sigue saliendo de las reglas
    assert hashes[0] == hashes[2]


def test_desde_ejemplo_con_filas_desparejas_y_conflictos():
    sin_primera = ESPERADO.iloc[1:].reset_index(drop=True)
    ejemplo, _ = pautas.desde_ejemplo(CRUDO, sin_primera)  # se empareja por fecha y hora
    assert sorted(p["salida"]["Programa"] for p in ejemplo.values()) == ["Koko Pop", "Memory Lane"]

    distinto = ESPERADO.assign(Capitulo=["Outkast", None, "OutKast (repetido)"])
    ejemplo, conflictos = pautas.desde_ejemplo(CRUDO, distinto)
    assert conflictos == 1
    assert next(p for p in ejemplo.values() if p["salida"]["Programa"] == "Memory Lane")["salida"]["Capitulo"] == "Outkast"


def _crear(cliente):
    archivos = {"grilla_cruda": ("g.xlsx", excel(CRUDO)), "ejemplo": ("e.xlsx", excel(ESPERADO))}
    r = cliente.post("/api/senales/crear", files=archivos, data={"nombre": "Concierto"})
    assert r.status_code == 200, r.text
    creada = r.json()
    assert creada["pautas"] == {"agregadas": 2, "conflictos": 0}
    return creada, cliente.get("/api/senales/concierto").json()


def test_base_de_pautas_por_api(cliente):
    creada, receta = _crear(cliente)
    pedido = {"tabla_id": creada["tabla_id"], "senal": receta}
    preview = cliente.post("/api/preview", json=pedido).json()
    assert preview["estados"] == ["conocida"] * 3
    assert preview["resumen_pautas"] == {"conocida": 3, "editada": 0, "nueva": 0}
    programa = preview["columnas"].index("Programa")
    assert [f[programa] for f in preview["filas"]] == ["Memory Lane", "Koko Pop", "Memory Lane"]

    # Corregir una celda de la semana cambia todas las filas de esa pauta.
    cliente.post("/api/senales/concierto/abierta", files={"archivo": ("g.xlsx", excel(CRUDO))})
    r = cliente.post("/api/senales/concierto/abierta/celda", json={"fila": 2, "columna": "Programa", "valor": "Memory Lane Live"})
    assert r.status_code == 200, r.text
    assert cliente.post("/api/senales/concierto/abierta/celda",
                        json={"fila": 0, "columna": "Hora", "valor": "07:00"}).status_code == 422
    preview = cliente.post("/api/preview", json=pedido).json()
    assert preview["estados"] == ["editada", "conocida", "editada"]
    assert preview["filas"][0][programa] == "Memory Lane Live"

    lista = cliente.get("/api/senales/concierto/pautas", params={"q": "MEMORY live"}).json()
    assert lista["total"] == 1 and lista["pautas"][0]["estado"] == "editada"
    assert lista["por_estado"] == {"editada": 1, "revisada": 1}
    h = lista["pautas"][0]["hash"]
    assert cliente.put(f"/api/senales/concierto/pautas/{h}",
                       json={"salida": {"Programa": "ML", "Capitulo": None}}).status_code == 200
    assert cliente.put("/api/senales/concierto/pautas/noexiste", json={"salida": {}}).status_code == 404

    # Olvidar una pauta la vuelve nueva; confirmar la semana la guarda con lo que arman las reglas.
    cliente.delete(f"/api/senales/concierto/pautas/{h}")
    preview = cliente.post("/api/preview", json={**pedido, "solo_nuevas": True}).json()
    assert preview["indices"] == [0, 2] and preview["resumen_pautas"]["nueva"] == 2
    exportado = cliente.post("/api/export", json={**pedido, "formato": "csv"})
    assert exportado.headers["X-Pautas-Nuevas"] == "2"
    assert cliente.post("/api/senales/concierto/abierta/confirmar").status_code == 200
    assert cliente.post("/api/preview", json=pedido).json()["resumen_pautas"]["nueva"] == 0
