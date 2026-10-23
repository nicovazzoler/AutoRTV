"""Registro de pedidos al asistente y tope diario por usuario."""
import datetime as dt
import os
import sqlite3

from app.config import data_dir


def limite_diario() -> int:
    return int(os.environ.get("AGENTE_LIMITE_DIARIO", "50"))


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(data_dir() / "app.db")
    con.execute("""CREATE TABLE IF NOT EXISTS uso_agente (
        id INTEGER PRIMARY KEY, usuario TEXT NOT NULL, fecha TEXT NOT NULL, senal TEXT NOT NULL,
        pedido TEXT NOT NULL, vueltas INTEGER NOT NULL, tokens_entrada INTEGER NOT NULL,
        tokens_salida INTEGER NOT NULL, logrado INTEGER NOT NULL)""")
    return con


def pedidos_de_hoy(usuario: str) -> int:
    with _db() as con:
        (n,) = con.execute("SELECT COUNT(*) FROM uso_agente WHERE usuario = ? AND fecha >= ?",
                           (usuario, dt.date.today().isoformat())).fetchone()
    return n


def registrar(usuario: str, senal: str, pedido: str, vueltas: int, tokens_entrada: int,
              tokens_salida: int, logrado: bool) -> None:
    with _db() as con:
        con.execute("INSERT INTO uso_agente (usuario, fecha, senal, pedido, vueltas, tokens_entrada, tokens_salida, logrado)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (usuario, dt.datetime.now().isoformat(timespec="seconds"), senal, pedido[:2000], vueltas,
                     tokens_entrada, tokens_salida, int(logrado)))


def resumen_del_mes() -> list[dict]:
    desde = dt.date.today().replace(day=1).isoformat()
    with _db() as con:
        filas = con.execute("SELECT usuario, COUNT(*), SUM(tokens_entrada), SUM(tokens_salida), SUM(logrado) "
                            "FROM uso_agente WHERE fecha >= ? GROUP BY usuario ORDER BY usuario", (desde,)).fetchall()
    return [{"usuario": u, "pedidos": n, "tokens_entrada": te or 0, "tokens_salida": ts or 0, "logrados": ok or 0}
            for u, n, te, ts, ok in filas]
