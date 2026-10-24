"""Base de pautas: cada fila cruda (sin fecha, hora ni duración) se reconoce por su hash y reusa su salida."""
import datetime as dt
import hashlib
import io
import re
import unicodedata

import pandas as pd
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects import postgresql, sqlite

from app import db, export
from app.catalogo import clave
from app.engine import model as m
from app.engine.tarjetas.estructura import a_fecha, a_hora
from app.inputs import excel
from app.validate import grilla

# Palabras de un nombre de columna cruda que indican horario. "end" y "fin" van enteras (no "Legend", "Final").
PREFIJOS_HORARIO = ("fecha", "hora", "dur", "date", "time", "start", "inicio")
PALABRAS_HORARIO = {"end", "fin"}
# Columnas de salida que siempre salen de las reglas, nunca de la base.
NO_CONTENIDO = {"n", "dia", "fecha", "hora", "duracion", "dur"}
POR_PAGINA = 200


def _es_de_horario(v) -> bool:
    return isinstance(v, (dt.date, dt.time, dt.timedelta, pd.Timestamp))


def columnas_de_horario(tabla: pd.DataFrame) -> list[str]:
    elegidas = []
    for c in tabla.columns:
        palabras = re.findall(r"[a-z]+", clave(c))
        por_nombre = any(p.startswith(PREFIJOS_HORARIO) or p in PALABRAS_HORARIO for p in palabras)
        valores = [v for v in tabla[c] if v is not None and not (isinstance(v, float) and pd.isna(v))]
        por_tipo = bool(valores) and sum(map(_es_de_horario, valores)) > len(valores) / 2
        if por_nombre or por_tipo:
            elegidas.append(c)
    return elegidas


def columnas_de_contenido(columnas: list[str], v: m.Validaciones | None = None) -> list[str]:
    horario = {c for c in grilla.detectar_columnas(columnas, v or m.Validaciones()).values() if c}
    return [c for c in columnas if clave(c) not in NO_CONTENIDO and c not in horario]


def _norma(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = unicodedata.normalize("NFD", str(v)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


def hash_pauta(fila: dict) -> str:
    return hashlib.sha1("|".join(_norma(v) for v in fila.values()).encode()).hexdigest()[:16]


def valor_json(v):
    """Valor de celda apto para JSON: los números y textos quedan igual; fechas como las ve una persona."""
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):  # escalares de numpy
        v = v.item()
    return export.celda_json(v)


def crudas(tabla: pd.DataFrame) -> list[dict]:
    """Cada fila cruda sin sus columnas de horario: lo que identifica a la pauta."""
    cols = [c for c in tabla.columns if c not in set(columnas_de_horario(tabla))]
    return [{c: valor_json(v) for c, v in zip(cols, fila)} for fila in tabla[cols].itertuples(index=False)]


def aplicar(crudo: pd.DataFrame, procesada: pd.DataFrame, base: dict[str, dict]
            ) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Pisa las columnas de contenido de cada fila con lo guardado en la base.

    Las tarjetas no agregan ni sacan filas: la fila i cruda es la fila i procesada.
    Devuelve la tabla, el estado de cada fila (conocida | editada | nueva) y su hash.
    """
    hashes = [hash_pauta(f) for f in crudas(crudo)]
    if len(hashes) != len(procesada):
        return procesada, ["nueva"] * len(procesada), [""] * len(procesada)
    df = procesada.copy()
    estados = []
    for i, h in enumerate(hashes):
        pauta = base.get(h)
        if pauta is None:
            estados.append("nueva")
            continue
        estados.append("editada" if pauta["estado"] == "editada" else "conocida")
        for col, valor in pauta["salida"].items():
            if col not in df.columns:
                df[col] = None
            df.at[df.index[i], col] = valor
    return df, estados, hashes


def _clave_horario(fila: pd.Series, columnas: list[str]) -> tuple | None:
    fecha = hora = None
    for c in columnas:
        v = fila[c]
        if isinstance(v, (dt.datetime, pd.Timestamp)) and v.time() != dt.time(0):
            fecha, hora = fecha or v.date(), hora or v.time()
        elif fecha is None and isinstance(v, (dt.date, dt.datetime)):
            fecha = a_fecha(v)
        elif hora is None and isinstance(v, dt.time) and "dur" not in clave(c):
            hora = v
    return (fecha, hora.strftime("%H:%M")) if fecha and hora else None


def desde_ejemplo(crudo: pd.DataFrame, esperado: pd.DataFrame, v: m.Validaciones | None = None
                  ) -> tuple[dict[str, dict], int]:
    """Pautas del par grilla cruda → EPG terminado: {hash: {crudo, salida}} y cuántos conflictos hubo.

    Empareja la fila i con la fila i; si las cantidades no coinciden, por fecha y hora.
    Si un mismo hash aparece con dos salidas distintas, queda la primera.
    """
    contenido = columnas_de_contenido(list(esperado.columns), v)
    filas_crudas = crudas(crudo)
    if len(crudo) == len(esperado):
        pares = list(range(len(crudo)))
    else:
        cols = grilla.detectar_columnas(list(esperado.columns), v or m.Validaciones())
        if not cols["fecha"] or not cols["hora"]:
            return {}, 0
        por_horario = {}
        for j, f in esperado.iterrows():
            fecha, hora = a_fecha(f[cols["fecha"]]), a_hora(f[cols["hora"]])
            if fecha and hora:
                por_horario.setdefault((fecha, hora.strftime("%H:%M")), j)
        horario = columnas_de_horario(crudo)
        pares = [por_horario.get(_clave_horario(f, horario)) for _, f in crudo.iterrows()]

    pautas, conflictos = {}, 0
    for i, j in enumerate(pares):
        if j is None:
            continue
        salida = {c: valor_json(esperado.iloc[j][c]) for c in contenido}
        h = hash_pauta(filas_crudas[i])
        if h in pautas:
            conflictos += pautas[h]["salida"] != salida
            continue
        pautas[h] = {"crudo": filas_crudas[i], "salida": salida}
    return pautas, conflictos


# --- Base de datos ---

def _texto(crudo: dict, salida: dict) -> str:
    """Texto normalizado para buscar sin importar tildes ni mayúsculas."""
    partes = [str(v) for v in [*crudo.values(), *salida.values()] if v is not None]
    return " ".join(unicodedata.normalize("NFD", " ".join(partes)).encode("ascii", "ignore").decode().lower().split())


def _insertar(con, filas: list[dict], pisar: bool) -> None:
    dialecto = postgresql if con.dialect.name == "postgresql" else sqlite
    sentencia = dialecto.insert(db.pautas).values(filas)
    clave_pk = ["senal_id", "hash"]
    if pisar:
        cambios = {c: sentencia.excluded[c] for c in ("crudo", "salida", "estado", "usuario", "actualizado", "texto")}
        sentencia = sentencia.on_conflict_do_update(index_elements=clave_pk, set_=cambios)
    else:
        sentencia = sentencia.on_conflict_do_nothing(index_elements=clave_pk)
    con.execute(sentencia)


def guardar(senal_id: str, pautas: dict[str, dict], estado: str, usuario: str, pisar: bool = False) -> int:
    """Guarda las pautas. Sin `pisar`, las que ya están en la base no se tocan. Devuelve cuántas había nuevas."""
    if not pautas:
        return 0
    ahora = dt.datetime.now()
    filas = [{"senal_id": senal_id, "hash": h, "crudo": p["crudo"], "salida": p["salida"], "estado": estado,
              "usuario": usuario, "actualizado": ahora, "texto": _texto(p["crudo"], p["salida"])}
             for h, p in pautas.items()]
    with db.transaccion() as con:
        ya = set(con.execute(select(db.pautas.c.hash).where(db.pautas.c.senal_id == senal_id,
                                                              db.pautas.c.hash.in_(list(pautas)))).scalars())
        for k in range(0, len(filas), 500):
            _insertar(con, filas[k:k + 500], pisar)
    return len(set(pautas) - ya)


def base(senal_id: str) -> dict[str, dict]:
    with db.transaccion() as con:
        filas = con.execute(select(db.pautas.c.hash, db.pautas.c.salida, db.pautas.c.estado)
                            .where(db.pautas.c.senal_id == senal_id)).all()
    return {h: {"salida": s, "estado": e} for h, s, e in filas}


def leer(senal_id: str, h: str) -> dict | None:
    with db.transaccion() as con:
        fila = con.execute(select(db.pautas).where(db.pautas.c.senal_id == senal_id, db.pautas.c.hash == h)).first()
    return dict(fila._mapping) if fila else None


def editar(senal_id: str, h: str, salida: dict, usuario: str) -> bool:
    actual = leer(senal_id, h)
    if actual is None:
        return False
    with db.transaccion() as con:
        con.execute(update(db.pautas).where(db.pautas.c.senal_id == senal_id, db.pautas.c.hash == h).values(
            salida=salida, estado="editada", usuario=usuario, actualizado=dt.datetime.now(),
            texto=_texto(actual["crudo"], salida)))
    return True


def olvidar(senal_id: str, h: str) -> None:
    with db.transaccion() as con:
        con.execute(delete(db.pautas).where(db.pautas.c.senal_id == senal_id, db.pautas.c.hash == h))


def listar(senal_id: str, estado: str | None = None, q: str = "", desde: int = 0) -> dict:
    c = db.pautas.c
    filtro = [c.senal_id == senal_id]
    if estado:
        filtro.append(c.estado == estado)
    for palabra in _texto({}, {"q": q}).split():
        filtro.append(c.texto.contains(palabra, autoescape=True))
    with db.transaccion() as con:
        total = con.execute(select(func.count()).select_from(db.pautas).where(*filtro)).scalar()
        filas = con.execute(select(c.hash, c.crudo, c.salida, c.estado, c.usuario, c.actualizado).where(*filtro)
                            .order_by(c.actualizado.desc(), c.hash).offset(desde).limit(POR_PAGINA)).all()
        por_estado = dict(con.execute(select(c.estado, func.count()).where(c.senal_id == senal_id)
                                      .group_by(c.estado)).all())
    return {"total": total, "por_estado": por_estado,
            "pautas": [{**f._mapping, "actualizado": f.actualizado.isoformat(timespec="minutes")} for f in filas]}


def cargar_ejemplo(receta: m.Senal, entrada: bytes, esperado: bytes, usuario: str) -> dict:
    """Suma a la base las pautas de un ejemplo, sin pisar las que ya están."""
    crudo = excel.leer(io.BytesIO(entrada), receta.entrada)
    terminado = pd.read_excel(io.BytesIO(esperado), dtype=object)
    terminado = terminado.astype(object).where(terminado.notna(), None)
    pautas, conflictos = desde_ejemplo(crudo, terminado, receta.validaciones)
    return {"agregadas": guardar(receta.id, pautas, "revisada", usuario), "conflictos": conflictos}
