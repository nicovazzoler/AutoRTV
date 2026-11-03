"""El historial: cada corrección, aceptación, confirmación y cambio de reglas, con quién y en qué carga de la semana."""
import datetime as dt
from collections import Counter

from sqlalchemy import and_, desc, insert, select

from app import db

MAX_CARGAS = 100
TIPOS = ("corregida", "aceptada", "confirmada", "base", "reglas")


def anotar(senal_id: str, usuario: str, tipo: str, filas: list[dict]) -> None:
    """`filas`: {pauta, programa, columna, antes, despues} (columna y valores pueden faltar, como en "aceptada")."""
    if not filas:
        return
    from app import semanas
    meta = semanas.leer(senal_id) or {}
    resumen = meta.get("resumen") or {}
    ahora = dt.datetime.now().replace(microsecond=0)
    with db.transaccion() as con:
        con.execute(insert(db.cambios), [{
            "usuario": usuario, "fecha": ahora, "senal_id": senal_id, "carga": meta.get("tabla_id"),
            "desde": resumen.get("desde"), "hasta": resumen.get("hasta"), "tipo": tipo,
            "pauta": f.get("pauta"), "programa": _texto(f.get("programa")), "columna": f.get("columna"),
            "antes": f.get("antes"), "despues": f.get("despues")} for f in filas])


def _texto(v) -> str | None:
    return None if v is None else " ".join(str(v).split())[:200]


def cargas(usuario: str | None = None) -> list[dict]:
    """Una fila por carga de semana (o por señal, si no había ninguna abierta), la más reciente primero."""
    c = db.cambios.c
    consulta = select(c.senal_id, c.carga, c.desde, c.hasta, c.usuario, c.tipo, c.fecha)
    if usuario:
        consulta = consulta.where(c.usuario == usuario)
    with db.transaccion() as con:
        filas = con.execute(consulta.order_by(desc(c.fecha))).all()
    grupos: dict[tuple, dict] = {}
    for f in filas:
        g = grupos.setdefault((f.senal_id, f.carga or ""), {
            "senal_id": f.senal_id, "carga": f.carga or "", "desde": f.desde, "hasta": f.hasta, "ultima": f.fecha.isoformat(),
            "primera": f.fecha.isoformat(), "usuarios": [], "cuenta": Counter()})
        g["primera"] = f.fecha.isoformat()
        g["desde"], g["hasta"] = g["desde"] or f.desde, g["hasta"] or f.hasta
        if f.usuario not in g["usuarios"]:
            g["usuarios"].append(f.usuario)
        g["cuenta"][f.tipo] += 1
    lista = list(grupos.values())[:MAX_CARGAS]
    for g in lista:
        g["cuenta"] = dict(g["cuenta"])
        g["confirmada"] = "confirmada" in g["cuenta"]
    return lista


def detalle(senal_id: str, carga: str, usuario: str | None = None) -> list[dict]:
    c = db.cambios.c
    condicion = and_(c.senal_id == senal_id, c.carga == carga if carga else c.carga.is_(None))
    if usuario:
        condicion = and_(condicion, c.usuario == usuario)
    with db.transaccion() as con:
        filas = con.execute(select(db.cambios).where(condicion).order_by(c.fecha, c.id)).all()
    return [{"usuario": f.usuario, "fecha": f.fecha.isoformat(), "tipo": f.tipo, "pauta": f.pauta, "programa": f.programa,
             "columna": f.columna, "antes": f.antes, "despues": f.despues} for f in filas]


def correcciones(senal_id: str) -> list[dict]:
    """Las celdas corregidas de la señal (en la semana o en la Base), para buscar las que se repiten."""
    c = db.cambios.c
    with db.transaccion() as con:
        filas = con.execute(select(c.columna, c.antes, c.despues, c.programa, c.fecha, c.desde)
                            .where(c.senal_id == senal_id, c.tipo.in_(("corregida", "base")), c.columna.is_not(None))
                            .order_by(c.fecha)).all()
    return [dict(f._mapping) for f in filas]
