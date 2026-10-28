"""La semana abierta de cada señal: la última grilla subida, para que cualquiera la retome y el Inicio muestre en qué está."""
import datetime as dt

import pandas as pd
from sqlalchemy import delete, insert, select, update

from app import db, tablas
from app.engine.tarjetas.estructura import a_fecha, a_hora

COLUMNAS_META = ("senal_id", "tabla_id", "nombre", "subida_por", "subida", "resumen", "confirmada_por", "confirmada",
                 "version", "anterior_nombre")
# Más días en común que esto con la semana abierta = es otra versión de esa misma semana.
DIAS_PARA_VERSION = 3
MAX_CAMBIOS = 300


def abrir(senal_id: str, tabla_id: str, contenido: bytes, nombre: str, usuario: str, es_version: bool) -> None:
    """Reemplaza la semana abierta. Si es otra versión de la misma semana, la anterior queda para comparar."""
    with db.transaccion() as con:
        vieja = con.execute(select(db.semanas).where(db.semanas.c.senal_id == senal_id)).first()
        extra = {"version": 1}
        if es_version and vieja is not None:
            extra = {"version": (vieja.version or 1) + 1, "anterior_tabla_id": vieja.tabla_id,
                     "anterior_contenido": vieja.contenido, "anterior_nombre": vieja.nombre}
        con.execute(delete(db.semanas).where(db.semanas.c.senal_id == senal_id))
        con.execute(insert(db.semanas).values(senal_id=senal_id, tabla_id=tabla_id, contenido=contenido,
                                              nombre=nombre[:200], subida_por=usuario, subida=dt.datetime.now(),
                                              **extra))


def es_version(desde: str | None, hasta: str | None, abierta: dict | None) -> bool:
    """Si las fechas nuevas se pisan con las de la semana abierta en más de DIAS_PARA_VERSION días."""
    resumen = (abierta or {}).get("resumen") or {}
    if not (desde and hasta and resumen.get("desde") and resumen.get("hasta")):
        return False
    inicio = max(dt.date.fromisoformat(desde), dt.date.fromisoformat(resumen["desde"]))
    fin = min(dt.date.fromisoformat(hasta), dt.date.fromisoformat(resumen["hasta"]))
    return (fin - inicio).days + 1 > DIAS_PARA_VERSION


def contenido(senal_id: str) -> bytes | None:
    """El archivo de la grilla abierta, tal como se subió."""
    with db.transaccion() as con:
        valor = con.execute(select(db.semanas.c.contenido).where(db.semanas.c.senal_id == senal_id)).scalar()
    return bytes(valor) if valor is not None else None


def anterior(senal_id: str) -> str | None:
    """El tabla_id de la versión anterior, si hay."""
    with db.transaccion() as con:
        fila = con.execute(select(db.semanas.c.anterior_tabla_id, db.semanas.c.anterior_contenido)
                           .where(db.semanas.c.senal_id == senal_id)).first()
    if fila is None or not fila.anterior_tabla_id:
        return None
    tablas.asegurar(fila.anterior_tabla_id, bytes(fila.anterior_contenido))
    return fila.anterior_tabla_id


def _claves(df: pd.DataFrame, fecha: str, hora: str) -> list[tuple]:
    return [(a_fecha(f), a_hora(h)) for f, h in zip(df[fecha], df[hora])]


def _texto(v) -> str:
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()


def comparar(antes: pd.DataFrame, ahora: pd.DataFrame, fecha: str, hora: str, columnas: list[str]) -> list[dict]:
    """Qué cambió de una versión a otra, emisión por emisión (fecha + hora): agregado, sacado o cambiado."""
    columnas = [c for c in columnas if c in antes.columns and c in ahora.columns]

    def por_clave(df):
        return {k: {c: _texto(df.iloc[i][c]) for c in columnas}
                for i, k in enumerate(_claves(df, fecha, hora)) if k[0] and k[1] is not None}

    viejas, nuevas = por_clave(antes), por_clave(ahora)
    cambios = []
    for k in sorted(viejas.keys() | nuevas.keys()):
        fila = {"fecha": k[0].isoformat(), "hora": k[1].strftime("%H:%M")}
        if k not in viejas:
            cambios.append({**fila, "tipo": "agregado", "ahora": nuevas[k]})
        elif k not in nuevas:
            cambios.append({**fila, "tipo": "sacado", "antes": viejas[k]})
        elif campos := [c for c in columnas if viejas[k][c] != nuevas[k][c]]:
            cambios.append({**fila, "tipo": "cambiado", "campos": campos,
                            "antes": {c: viejas[k][c] for c in campos}, "ahora": {c: nuevas[k][c] for c in campos}})
        if len(cambios) >= MAX_CAMBIOS:
            break
    return cambios


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


def guardar_resumen(senal_id: str, resumen: dict, foto: list[list] | None = None) -> None:
    valores = {"resumen": resumen} | ({"foto": foto} if foto is not None else {})
    with db.transaccion() as con:
        con.execute(update(db.semanas).where(db.semanas.c.senal_id == senal_id).values(**valores))


def fotos() -> dict[str, list[list] | None]:
    """La foto de cada semana abierta; None si la semana todavía no se armó desde que existen las fotos."""
    with db.transaccion() as con:
        return dict(con.execute(select(db.semanas.c.senal_id, db.semanas.c.foto)).all())


def confirmar(senal_id: str, usuario: str) -> None:
    with db.transaccion() as con:
        con.execute(update(db.semanas).where(db.semanas.c.senal_id == senal_id)
                    .values(confirmada_por=usuario, confirmada=dt.datetime.now()))
