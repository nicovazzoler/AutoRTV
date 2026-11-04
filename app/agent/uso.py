"""Registro de pedidos al asistente y tope diario por usuario."""
import datetime as dt
import os

from sqlalchemy import delete, func, insert, select

from app import db


def limite_diario() -> int:
    """El que puso un admin desde la app; si no hay, el de la variable de entorno."""
    with db.transaccion() as con:
        propio = con.execute(select(db.ajustes.c.valor).where(db.ajustes.c.clave == "limite_diario")).scalar()
    return int(propio if propio is not None else os.environ.get("AGENTE_LIMITE_DIARIO", "50"))


def poner_limite_diario(valor: int) -> None:
    with db.transaccion() as con:
        con.execute(delete(db.ajustes).where(db.ajustes.c.clave == "limite_diario"))
        con.execute(insert(db.ajustes).values(clave="limite_diario", valor=str(valor)))


# Lo que el agente hace solo (banco de pruebas, armado de reglas) se registra pero no gasta el tope de la persona.
SIN_TOPE = ("[banco]", "[armar reglas]", "[agente de la señal]", "[lectura]", "[parecidas]")


def pedidos_de_hoy(usuario: str) -> int:
    hoy = dt.datetime.combine(dt.date.today(), dt.time(0))
    t = db.uso_agente
    with db.transaccion() as con:
        return con.execute(select(func.count()).where(t.c.usuario == usuario, t.c.fecha >= hoy,
                                                      t.c.pedido.notin_(SIN_TOPE))).scalar()


# USD por millón de tokens (entrada, salida). Las lecturas de caché se cobran menos: es un tope, no la factura.
PRECIOS = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-opus-5-5": (4.0, 20.0),
}


def costo(modelo: str | None, tokens_entrada: int, tokens_salida: int) -> float | None:
    precio = PRECIOS.get(modelo or "")
    if precio is None:
        return None
    return (tokens_entrada * precio[0] + tokens_salida * precio[1]) / 1_000_000


def registrar(usuario: str, senal: str, pedido: str, vueltas: int, tokens_entrada: int,
              tokens_salida: int, logrado: bool, modelo: str | None = None) -> None:
    with db.transaccion() as con:
        con.execute(insert(db.uso_agente).values(
            usuario=usuario, fecha=dt.datetime.now().replace(microsecond=0), senal=senal, pedido=pedido[:2000],
            vueltas=vueltas, tokens_entrada=tokens_entrada, tokens_salida=tokens_salida, logrado=logrado,
            costo_usd=costo(modelo, tokens_entrada, tokens_salida)))


def _costo_de(fila) -> float:
    if fila.costo_usd is not None:
        return fila.costo_usd
    # Pedidos de antes de guardar el costo: la charla iba a Haiku y las propuestas a Opus.
    modelo = "claude-haiku-5-5" if fila.pedido.startswith("[charla]") else "claude-opus-5-5"
    return costo(modelo, fila.tokens_entrada, fila.tokens_salida) or 0.0


def resumen_del_mes() -> list[dict]:
    """Por persona: pedidos, tokens y lo que se gastó (estimado) en el mes y hoy."""
    hoy = dt.datetime.combine(dt.date.today(), dt.time(0))
    t = db.uso_agente
    with db.transaccion() as con:
        filas = con.execute(select(t.c.usuario, t.c.fecha, t.c.pedido, t.c.tokens_entrada, t.c.tokens_salida,
                                   t.c.logrado, t.c.costo_usd).where(t.c.fecha >= hoy.replace(day=1))).all()
    por_usuario: dict[str, dict] = {}
    for f in filas:
        u = por_usuario.setdefault(f.usuario, {"usuario": f.usuario, "pedidos": 0, "logrados": 0, "tokens_entrada": 0,
                                               "tokens_salida": 0, "usd_mes": 0.0, "usd_hoy": 0.0, "pedidos_hoy": 0})
        gasto = _costo_de(f)
        u["pedidos"] += 1
        u["logrados"] += int(bool(f.logrado))
        u["tokens_entrada"] += f.tokens_entrada
        u["tokens_salida"] += f.tokens_salida
        u["usd_mes"] += gasto
        if f.fecha >= hoy:
            u["usd_hoy"] += gasto
            u["pedidos_hoy"] += 1
    return sorted(por_usuario.values(), key=lambda u: u["usuario"])
