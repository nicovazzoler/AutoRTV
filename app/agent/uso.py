"""Registro de pedidos al asistente y tope diario por usuario."""
import datetime as dt
import os

from sqlalchemy import Integer, delete, func, insert, select

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


def pedidos_de_hoy(usuario: str) -> int:
    hoy = dt.datetime.combine(dt.date.today(), dt.time(0))
    t = db.uso_agente
    with db.transaccion() as con:
        return con.execute(select(func.count()).where(t.c.usuario == usuario, t.c.fecha >= hoy)).scalar()


def registrar(usuario: str, senal: str, pedido: str, vueltas: int, tokens_entrada: int,
              tokens_salida: int, logrado: bool) -> None:
    with db.transaccion() as con:
        con.execute(insert(db.uso_agente).values(
            usuario=usuario, fecha=dt.datetime.now().replace(microsecond=0), senal=senal, pedido=pedido[:2000],
            vueltas=vueltas, tokens_entrada=tokens_entrada, tokens_salida=tokens_salida, logrado=logrado))


def resumen_del_mes() -> list[dict]:
    desde = dt.datetime.combine(dt.date.today().replace(day=1), dt.time(0))
    t = db.uso_agente
    consulta = (select(t.c.usuario, func.count(), func.sum(t.c.tokens_entrada), func.sum(t.c.tokens_salida),
                       func.sum(func.cast(t.c.logrado, Integer)))
                .where(t.c.fecha >= desde).group_by(t.c.usuario).order_by(t.c.usuario))
    with db.transaccion() as con:
        filas = con.execute(consulta).all()
    return [{"usuario": u, "pedidos": n, "tokens_entrada": te or 0, "tokens_salida": ts or 0, "logrados": ok or 0}
            for u, n, te, ts, ok in filas]
