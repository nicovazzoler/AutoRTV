"""Copia a la base los datos del formato viejo del volumen: app.db (SQLite) y carpetas de señales.

Corre al arrancar y solo si la base está vacía, así que es seguro dejarla siempre activa.
"""
import datetime as dt
import json
import logging
import sqlite3

from sqlalchemy import func, insert, select, text
from sqlalchemy.engine import Connection

from app import db
from app.config import data_dir

log = logging.getLogger("autortv.migrar")


def desde_volumen(con: Connection) -> None:
    hay_datos = con.execute(select(func.count()).select_from(db.usuarios)).scalar() or \
        con.execute(select(func.count()).select_from(db.senales)).scalar()
    if hay_datos:
        return
    raiz = data_dir()
    usuarios = _usuarios_y_uso(con, raiz / "app.db")
    senales = _senales(con, raiz / "senales")
    if usuarios or senales:
        log.warning("Migradas desde el volumen: %d usuarios y %d señales", usuarios, senales)


def _usuarios_y_uso(con: Connection, archivo) -> int:
    if not archivo.exists():
        return 0
    viejo = sqlite3.connect(archivo)
    try:
        tablas = {t for (t,) in viejo.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        filas = viejo.execute("SELECT id, usuario, hash, admin FROM usuarios").fetchall() if "usuarios" in tablas else []
        for id_, usuario, hash_, admin in filas:
            # Mismo hash: las claves de siempre siguen andando.
            con.execute(insert(db.usuarios).values(id=id_, usuario=usuario, hash=hash_, admin=bool(admin)))
        if "uso_agente" in tablas:
            for u, fecha, senal, pedido, vueltas, te, ts, ok in viejo.execute(
                    "SELECT usuario, fecha, senal, pedido, vueltas, tokens_entrada, tokens_salida, logrado FROM uso_agente"):
                con.execute(insert(db.uso_agente).values(
                    usuario=u, fecha=dt.datetime.fromisoformat(fecha), senal=senal, pedido=pedido, vueltas=vueltas,
                    tokens_entrada=te, tokens_salida=ts, logrado=bool(ok)))
        if filas and con.dialect.name == "postgresql":
            # Los ids se copiaron a mano: la secuencia tiene que seguir desde el más alto.
            con.execute(text("SELECT setval(pg_get_serial_sequence('usuarios', 'id'), (SELECT MAX(id) FROM usuarios))"))
        return len(filas)
    finally:
        viejo.close()


def _senales(con: Connection, raiz) -> int:
    from app.almacen import calcular_version

    if not raiz.exists():
        return 0
    cantidad = 0
    for carpeta in sorted(p for p in raiz.iterdir() if (p / "senal.json").exists()):
        receta = json.loads((carpeta / "senal.json").read_text(encoding="utf-8"))
        historial = sorted((carpeta / "historial").glob("*.json")) if (carpeta / "historial").exists() else []
        quien, cuando = "migración", dt.datetime.now()
        for archivo in historial:
            sello, _, usuario = archivo.stem.partition("_")
            fecha = dt.datetime.strptime(sello, "%Y%m%d-%H%M%S-%f")
            con.execute(insert(db.senales_historial).values(
                senal_id=receta["id"], receta=json.loads(archivo.read_text(encoding="utf-8")), usuario=usuario, fecha=fecha))
            quien, cuando = usuario, fecha
        con.execute(insert(db.senales).values(
            id=receta["id"], nombre=receta["nombre"], receta=receta, version=calcular_version(receta),
            actualizado=cuando, actualizado_por=quien))
        for ej in sorted(p for p in (carpeta / "ejemplos").glob("*") if (p / "esperado.xlsx").exists()):
            con.execute(insert(db.ejemplos).values(
                senal_id=receta["id"], nombre=ej.name, entrada=(ej / "entrada.xlsx").read_bytes(),
                esperado=(ej / "esperado.xlsx").read_bytes(), subido_por="migración", fecha=dt.datetime.now()))
        cantidad += 1
    return cantidad
