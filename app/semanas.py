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


def borrar(senal_id: str) -> None:
    """Saca la grilla abierta: si era una versión corregida vuelve la anterior; si no, la señal queda sin grilla."""
    with db.transaccion() as con:
        fila = con.execute(select(db.semanas).where(db.semanas.c.senal_id == senal_id)).first()
        if fila is None:
            return
        if not fila.anterior_tabla_id:
            con.execute(delete(db.semanas).where(db.semanas.c.senal_id == senal_id))
            return
        con.execute(update(db.semanas).where(db.semanas.c.senal_id == senal_id).values(
            tabla_id=fila.anterior_tabla_id, contenido=fila.anterior_contenido, nombre=fila.anterior_nombre,
            version=max(1, (fila.version or 1) - 1), anterior_tabla_id=None, anterior_contenido=None,
            anterior_nombre=None, confirmada=None, confirmada_por=None, resumen=None))
    tablas.asegurar(fila.anterior_tabla_id, bytes(fila.anterior_contenido))


def fijar_lunes(senal_id: str, lunes: dt.date | None) -> None:
    """La semana abierta pasa a las fechas de la semana de `lunes` (una grilla semanal sin fechas o con fechas viejas)."""
    with db.transaccion() as con:
        fila = con.execute(select(db.semanas.c.tabla_id).where(db.semanas.c.senal_id == senal_id)).first()
        if fila is None:
            return
        con.execute(update(db.semanas).where(db.semanas.c.senal_id == senal_id).values(lunes=lunes))
    tablas.fijar_lunes(fila.tabla_id, lunes)


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


FORMATOS_FECHA = ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y", "%d.%m.%Y")


def fin_de_mes(dia: dt.date, meses_despues: int = 0) -> dt.date:
    primero = dia.replace(day=1)
    for _ in range(meses_despues + 1):
        primero = (primero + dt.timedelta(days=32)).replace(day=1)
    return primero - dt.timedelta(days=1)


def _correr_fecha(v, dias: int):
    """La misma fecha `dias` después, con el mismo tipo o formato de texto que traía."""
    if isinstance(v, (dt.date, pd.Timestamp)):
        return v + dt.timedelta(days=dias)
    texto = _texto(v)
    for formato in FORMATOS_FECHA:
        try:
            return (dt.datetime.strptime(texto, formato) + dt.timedelta(days=dias)).strftime(formato)
        except ValueError:
            pass
    dia = a_fecha(v)
    return dia + dt.timedelta(days=dias) if dia else v


def repetir_ultima(salida: pd.DataFrame, fecha: str, hora: str | None, hasta: dt.date) -> pd.DataFrame:
    """Copia los últimos 7 días de la grilla, semana tras semana, hasta `hasta` inclusive.

    Se toma por momento (fecha + hora) y no por día: una grilla de lunes 06:00 a lunes 05:59 sigue pegada al copiarse.
    """
    horas = salida[hora] if hora in salida.columns else [None] * len(salida)
    momentos = [dt.datetime.combine(d, a_hora(h) or dt.time(0)) if (d := a_fecha(f)) else None
                for f, h in zip(salida[fecha], horas)]
    validos = [x for x in momentos if x]
    if not validos:
        raise ValueError("La grilla no tiene fechas que se puedan leer")
    ultimo = max(validos)
    bloque = [i for i, x in enumerate(momentos) if x and x > ultimo - dt.timedelta(days=7)]
    dias = {momentos[i].date() for i in bloque}
    if len(dias) < 7:
        raise ValueError(f"Para repetir hace falta una semana entera y la grilla trae {len(dias)} días")
    primero = min(dias)
    copias = []
    semanas = 1
    while primero + dt.timedelta(days=7 * semanas) <= hasta:
        corridos = 7 * semanas
        filas = [i for i in bloque if momentos[i].date() + dt.timedelta(days=corridos) <= hasta]
        copia = salida.iloc[filas].copy()
        copia[fecha] = [_correr_fecha(v, corridos) for v in copia[fecha]]
        copias.append(copia)
        semanas += 1
    return pd.concat([salida, *copias], ignore_index=True) if copias else salida


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
    tablas.asegurar(fila.tabla_id, bytes(fila.contenido), fila.lunes)
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
