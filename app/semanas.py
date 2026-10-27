"""La semana abierta de cada señal: la última grilla subida, para que cualquiera la retome y el Inicio muestre en qué está."""
import datetime as dt

from sqlalchemy import delete, insert, select, update

from app import db, tablas

COLUMNAS_META = ("senal_id", "tabla_id", "nombre", "subida_por", "subida", "resumen", "confirmada_por", "confirmada")


def abrir(senal_id: str, contenido: bytes, nombre: str, usuario: str) -> str:
    """Reemplaza la semana abierta de la señal por esta grilla."""
    tabla_id = tablas.subir(contenido)
    with db.transaccion() as con:
        con.execute(delete(db.semanas).where(db.semanas.c.senal_id == senal_id))
        con.execute(insert(db.semanas).values(senal_id=senal_id, tabla_id=tabla_id, contenido=contenido,
                                              nombre=nombre[:200], subida_por=usuario, subida=dt.datetime.now()))
    return tabla_id


def _meta(fila) -> dict:
    datos = {c: getattr(fila, c) for c in COLUMNAS_META}
    for c in ("subida", "confirmada"):
        datos[c] = datos[c].isoformat(timespec="minutes") if datos[c] else None
    return datos


def leer(senal_id: str) -> dict | None:
    with db.transaccion() as con:
        fila = con.execute(select(db.semanas).where(db.semanas.c.senal_id == senal_id)).first()
    if fila is None:
        return None
    tablas.asegurar(fila.tabla_id, bytes(fila.contenido))
    return _meta(fila)


def todas() -> dict[str, dict]:
    columnas = [getattr(db.semanas.c, c) for c in COLUMNAS_META]
    with db.transaccion() as con:
        return {f.senal_id: _meta(f) for f in con.execute(select(*columnas))}


def guardar_resumen(senal_id: str, resumen: dict) -> None:
    with db.transaccion() as con:
        con.execute(update(db.semanas).where(db.semanas.c.senal_id == senal_id).values(resumen=resumen))


def confirmar(senal_id: str, usuario: str) -> None:
    with db.transaccion() as con:
        con.execute(update(db.semanas).where(db.semanas.c.senal_id == senal_id)
                    .values(confirmada_por=usuario, confirmada=dt.datetime.now()))
