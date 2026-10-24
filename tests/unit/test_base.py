"""Guardado concurrente, grillas compartidas entre réplicas y migración desde el volumen viejo."""
import datetime as dt
import io
import json
import sqlite3
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from app import almacen, auth, db, migrar, tablas
from app.engine import model as m
from app.main import app

RAIZ = Path(__file__).resolve().parents[2]
RECETA = json.loads((RAIZ / "ejemplos" / "sintetica.json").read_text(encoding="utf-8"))


@pytest.fixture
def datos(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return tmp_path


def test_dos_guardados_con_la_misma_version(datos):
    senal = m.Senal.model_validate(RECETA)
    v1 = almacen.guardar(senal, "ana")
    almacen.guardar(senal.model_copy(update={"nombre": "Cambio de Beto"}), "beto", esperada=v1)
    with pytest.raises(almacen.Conflicto) as c:
        almacen.guardar(senal.model_copy(update={"nombre": "Cambio de Ana"}), "ana", esperada=v1)
    assert c.value.usuario == "beto"
    assert almacen.leer("sintetica").nombre == "Cambio de Beto"
    assert [h["usuario"] for h in almacen.historial("sintetica")] == ["ana", "beto"]  # el rechazado no deja rastro


def test_grilla_subida_se_lee_desde_otra_replica(datos):
    buf = io.BytesIO()
    pd.DataFrame({"a": ["x"]}).to_excel(buf, index=False)
    tabla_id = tablas.subir(buf.getvalue())
    tablas.olvidar_cache()  # otra réplica: no tiene nada en memoria
    assert tablas.tabla(tabla_id, m.EntradaExcel(tipo="excel"))["a"].tolist() == ["x"]


def test_grillas_viejas_se_borran(datos):
    vieja = tablas.subir(b"vieja")
    with db.transaccion() as con:
        con.execute(update(db.tablas_subidas).where(db.tablas_subidas.c.id == vieja)
                    .values(creada=dt.datetime.now() - dt.timedelta(hours=25)))
    tablas.olvidar_cache()
    tablas.subir(b"nueva")
    with pytest.raises(KeyError):
        tablas.tabla(vieja, m.EntradaExcel(tipo="excel"))


def _volumen_viejo(raiz: Path, esperado: bytes, grilla: bytes) -> None:
    """Arma DATA_DIR como lo dejaba la versión con archivos: app.db + senales/<id>/..."""
    con = sqlite3.connect(raiz / "app.db")
    con.execute("CREATE TABLE usuarios (id INTEGER PRIMARY KEY, usuario TEXT UNIQUE, hash TEXT, admin INTEGER)")
    con.execute("CREATE TABLE uso_agente (id INTEGER PRIMARY KEY, usuario TEXT, fecha TEXT, senal TEXT, pedido TEXT, "
                "vueltas INTEGER, tokens_entrada INTEGER, tokens_salida INTEGER, logrado INTEGER)")
    con.execute("INSERT INTO usuarios VALUES (7, 'nico', ?, 1)", (auth._hashear("clave-vieja"),))
    con.execute("INSERT INTO uso_agente VALUES (1, 'nico', ?, 'sintetica', 'algo', 1, 100, 20, 1)",
                (dt.datetime.now().isoformat(timespec="seconds"),))
    con.commit()
    con.close()
    carpeta = raiz / "senales" / "sintetica"
    (carpeta / "historial").mkdir(parents=True)
    (carpeta / "senal.json").write_text(json.dumps(RECETA), encoding="utf-8")
    for sello in ("20261001-100000-000000_nico", "20261002-110000-000000_ana"):
        (carpeta / "historial" / f"{sello}.json").write_text(json.dumps(RECETA), encoding="utf-8")
    ej = carpeta / "ejemplos" / "semana-1"
    ej.mkdir(parents=True)
    (ej / "entrada.xlsx").write_bytes(grilla)
    (ej / "esperado.xlsx").write_bytes(esperado)


def test_migracion_desde_el_volumen(datos):
    from tests.unit.test_api import GRILLA

    # El esperado se arma con la app misma: así el ejemplo migrado tiene que dar 100 %.
    with db.transaccion() as con:
        con.execute(db.usuarios.insert().values(usuario="tmp", hash=auth._hashear("tmp-clave-1"), admin=True))
    c = TestClient(app)
    c.post("/api/login", json={"usuario": "tmp", "clave": "tmp-clave-1"})
    tabla_id = c.post("/api/tablas", files={"archivo": ("g.xlsx", GRILLA)}).json()["tabla_id"]
    esperado = c.post("/api/export", json={"tabla_id": tabla_id, "senal": RECETA}).content
    with db.transaccion() as con:
        for tabla in reversed(db.metadata.sorted_tables):
            con.execute(tabla.delete())

    _volumen_viejo(datos, esperado, GRILLA)
    with db.transaccion() as con:
        migrar.desde_volumen(con)

    assert [u.usuario for u in auth.listar_usuarios()] == ["nico"]
    assert auth.iniciar_sesion("nico", "clave-vieja")  # el hash se copió tal cual
    auth.crear_usuario("ana", "clave-de-ana")  # la secuencia de ids sigue después del 7
    assert almacen.leer("sintetica") == m.Senal.model_validate(RECETA)
    assert [(h["usuario"], h["fecha"].day) for h in almacen.historial("sintetica")] == [("nico", 1), ("ana", 2)]

    c = TestClient(app)
    c.post("/api/login", json={"usuario": "nico", "clave": "clave-vieja"})
    (resultado,) = c.post("/api/senales/sintetica/ejemplos/evaluar", json=RECETA).json()
    assert resultado["nombre"] == "semana-1" and resultado["porcentaje"] == 100
    assert c.get("/api/asistente/uso").json()["usuarios"][0]["pedidos"] == 1

    # Una segunda pasada no duplica nada.
    with db.transaccion() as con:
        migrar.desde_volumen(con)
    assert len(auth.listar_usuarios()) == 2 and len(almacen.historial("sintetica")) == 2


def test_guardados_simultaneos_uno_solo_gana(datos):
    from concurrent.futures import ThreadPoolExecutor

    senal = m.Senal.model_validate(RECETA)
    version = almacen.guardar(senal, "inicial")

    def guardar(usuario):
        try:
            almacen.guardar(senal.model_copy(update={"nombre": usuario}), usuario, esperada=version)
            return "ok"
        except almacen.Conflicto:
            return "conflicto"

    with ThreadPoolExecutor(8) as hilos:
        resultados = list(hilos.map(guardar, [f"u{i}" for i in range(8)]))
    assert sorted(resultados) == ["conflicto"] * 7 + ["ok"]
    assert len(almacen.historial("sintetica")) == 2
