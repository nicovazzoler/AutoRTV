"""Gasto del agente: costo estimado por pedido y columna nueva en bases que ya existían."""
import sqlite3

from sqlalchemy import create_engine, inspect

from app import db
from app.agent import uso


def test_costo_por_modelo():
    assert uso.costo("claude-haiku-5-5", 1_000_000, 1_000_000) == 0.60
    assert round(uso.costo("claude-opus-5-5", 10_000, 2_000), 4) == 0.08
    assert uso.costo("modelo-desconocido", 1000, 1000) is None


def test_resumen_del_mes_con_pedidos_viejos_sin_costo(cliente):
    uso.registrar("ana", "canal", "[charla] hola", 1, 1_000_000, 0, True, "claude-haiku-5-5")
    uso.registrar("ana", "canal", "armá las reglas", 1, 100_000, 10_000, True)  # sin modelo: se estima como Opus
    (ana,) = uso.resumen_del_mes()
    assert ana["pedidos"] == 2 and ana["pedidos_hoy"] == 2
    assert round(ana["usd_mes"], 2) == round(0.10 + 0.40 + 0.20, 2) == round(ana["usd_hoy"], 2)


def test_base_vieja_suma_la_columna_de_costo(tmp_path):
    archivo = tmp_path / "vieja.db"
    con = sqlite3.connect(archivo)
    con.execute("CREATE TABLE uso_agente (id INTEGER PRIMARY KEY, usuario TEXT, fecha TIMESTAMP, senal TEXT, pedido TEXT,"
                " vueltas INTEGER, tokens_entrada INTEGER, tokens_salida INTEGER, logrado BOOLEAN)")
    con.commit()
    con.close()
    motor = create_engine(f"sqlite:///{archivo}")
    db.inicializar(motor)
    assert "costo_usd" in {c["name"] for c in inspect(motor).get_columns("uso_agente")}
