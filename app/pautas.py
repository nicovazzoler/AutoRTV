"""Base de pautas: cada fila cruda (sin fecha, hora ni duración) se reconoce por su hash y reusa su salida."""
import datetime as dt
import hashlib
import io
import re
import unicodedata

import pandas as pd
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.dialects import postgresql, sqlite

from app import db, export
from app.catalogo import clave
from app.engine import model as m
from app.engine.tarjetas.estructura import a_fecha, a_hora
from app import inputs
from app.validate import grilla

# Palabras de un nombre de columna cruda que indican horario. "end" y "fin" van enteras (no "Legend", "Final").
PREFIJOS_HORARIO = ("fecha", "hora", "dur", "date", "time", "start", "inicio")
PALABRAS_HORARIO = {"end", "fin", "dia", "day"}
# Identificadores de cada emisión (event_id, data-schedule-id): cambian en cada salida y no dicen qué programa es.
PALABRAS_ID = {"id", "uid", "key"}
TEXTO_DE_HORARIO = re.compile(r"^\s*(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(/\d{2,4})?|\d{1,2}:\d{2})")
# Una columna aparte con solo "AM" / "PM" (o "a.m.") también es parte de la hora.
AM_PM = re.compile(r"^\s*[ap]\.?\s?m\.?\s*$", re.IGNORECASE)
# Columnas de salida que siempre salen de las reglas, nunca de la base.
NO_CONTENIDO = {"n", "dia", "fecha", "hora", "duracion", "dur", "ampm"}
POR_PAGINA = 200
# Las celdas normalizadas solo tienen letras y números: el separador no se confunde con el contenido.
SEPARADOR = "///"
# Cambia cuando cambia cómo se calcula el hash: al arrancar, las bases guardadas se recalculan una vez.
VERSION_HASH = "2"


def _es_de_horario(v) -> bool:
    if isinstance(v, str):
        return bool(TEXTO_DE_HORARIO.match(v) or AM_PM.match(v))
    return isinstance(v, (dt.date, dt.time, dt.timedelta, pd.Timestamp))


def _mayoria_de_horario(valores, parte: float) -> bool:
    valores = [v for v in valores if v is not None and not (isinstance(v, float) and pd.isna(v))]
    return bool(valores) and sum(map(_es_de_horario, valores)) > len(valores) * parte


def columnas_de_horario(tabla: pd.DataFrame) -> list[str]:
    """Columnas crudas que no identifican a la pauta: horario, día e identificadores de cada emisión."""
    elegidas = []
    for c in tabla.columns:
        palabras = re.findall(r"[a-z]+", clave(c))
        por_nombre = any(p.startswith(PREFIJOS_HORARIO) or p in PALABRAS_HORARIO | PALABRAS_ID for p in palabras)
        if por_nombre or _mayoria_de_horario(tabla[c], 0.5):
            elegidas.append(c)
    return elegidas


def columnas_de_contenido(tabla: pd.DataFrame | list[str], v: m.Validaciones | None = None) -> list[str]:
    """Columnas de salida que guarda la base. Con la tabla, también descarta fecha, hora y día por su contenido."""
    columnas = list(tabla.columns) if isinstance(tabla, pd.DataFrame) else list(tabla)
    fuera = {c for c in grilla.detectar_columnas(columnas, v or m.Validaciones()).values() if c}
    if isinstance(tabla, pd.DataFrame):
        fuera |= set(columnas_por_tipo(tabla).values()) | set(_columnas_de_dia(tabla))
        # Horas escritas como texto ("08:00 PM"): más exigente que en la cruda para no sacar contenido.
        fuera |= {c for c in columnas if _mayoria_de_horario(tabla[c], 0.9)}
    return [c for c in columnas if clave(c) not in NO_CONTENIDO and c not in fuera]


def _columnas_de_dia(df: pd.DataFrame) -> list[str]:
    from app.inputs.pdf import dia_de

    elegidas = []
    for c in df.columns:
        valores = [x for x in df[c] if isinstance(x, str) and x.strip()]
        if valores and sum(dia_de(x) is not None and len(x.split()) == 1 for x in valores) > len(valores) * 0.9:
            elegidas.append(c)
    return elegidas


def normalizar(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = unicodedata.normalize("NFD", str(v)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


def hash_pauta(fila: dict) -> str:
    return hashlib.sha1(SEPARADOR.join(normalizar(v) for v in fila.values()).encode()).hexdigest()[:16]


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


def _como_fecha(v):
    """Un texto con fecha ("2026-10-23 00:00:00", "2026-10-19T21:00:00") pasa a fecha; lo demás queda igual."""
    if isinstance(v, str) and re.match(r"^\s*\d{4}-\d{2}-\d{2}", v):
        convertida = pd.to_datetime(v.strip(), errors="coerce")
        return None if pd.isna(convertida) else convertida.to_pydatetime()
    if isinstance(v, str):
        return a_hora(v) or v
    return v


def _clave_horario(fila: pd.Series, columnas: list[str]) -> tuple | None:
    fecha = hora = None
    for c in columnas:
        v = _como_fecha(fila[c])
        if isinstance(v, (dt.datetime, pd.Timestamp)) and v.time() != dt.time(0):
            fecha, hora = fecha or v.date(), hora or v.time()
        elif fecha is None and isinstance(v, (dt.date, dt.datetime)):
            fecha = a_fecha(v)
        elif hora is None and isinstance(v, dt.time) and "dur" not in clave(c):
            hora = v
    return (fecha, hora.strftime("%H:%M")) if fecha and hora else None


def columnas_por_tipo(df: pd.DataFrame) -> dict[str, str]:
    """Fecha y hora del EPG terminado cuando sus columnas no tienen un nombre conocido ("f", "h")."""
    elegidas = {}
    for c in df.columns:
        valores = [x for x in df[c] if x is not None]
        if not valores:
            continue
        fechas = sum(isinstance(x, (dt.date, dt.datetime)) and a_hora(x) in (None, dt.time(0)) for x in valores)
        horas = sum(isinstance(x, dt.time) for x in valores)
        if fechas > len(valores) / 2:
            elegidas.setdefault("fecha", c)
        elif horas > len(valores) / 2:
            elegidas.setdefault("hora", c)
    return elegidas


def desde_ejemplo(crudo: pd.DataFrame, esperado: pd.DataFrame, v: m.Validaciones | None = None
                  ) -> tuple[dict[str, dict], int]:
    """Pautas del par grilla cruda → EPG terminado: {hash: {crudo, salida}} y cuántos conflictos hubo.

    Empareja la fila i con la fila i; si las cantidades no coinciden, por fecha y hora.
    Si un mismo hash aparece con dos salidas distintas, queda la primera.
    """
    contenido = columnas_de_contenido(esperado, v)
    filas_crudas = crudas(crudo)
    if len(crudo) == len(esperado):
        pares = list(range(len(crudo)))
    else:
        cols = grilla.detectar_columnas(list(esperado.columns), v or m.Validaciones())
        cols = {**columnas_por_tipo(esperado), **{k: c for k, c in cols.items() if c}}
        if not cols.get("fecha") or not cols.get("hora"):
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


def limpiar(senal_id: str) -> dict:
    """Recalcula hash y salida de cada pauta guardada con la detección de horario de hoy.

    Si dos pautas quedan con el mismo hash se queda una: la editada a mano, y si no la más nueva.
    """
    with db.transaccion() as con:
        return _rehacer(con, senal_id, sacar_horario=True)


def _rehacer(con, senal_id: str, sacar_horario: bool) -> dict:
    filas = con.execute(select(db.pautas).where(db.pautas.c.senal_id == senal_id)).all()
    if not filas:
        return {"antes": 0, "despues": 0, "columnas": []}
    sacar_crudo, sacar_salida = set(), set()
    if sacar_horario:
        sacar_crudo = set(columnas_de_horario(pd.DataFrame([f.crudo for f in filas])))
        salidas = pd.DataFrame([f.salida for f in filas])
        sacar_salida = set(salidas.columns) - set(columnas_de_contenido(salidas))
    nuevas = {}
    for f in sorted(filas, key=lambda f: (f.estado != "editada", -f.actualizado.timestamp())):
        crudo = {c: v for c, v in f.crudo.items() if c not in sacar_crudo}
        salida = {c: v for c, v in f.salida.items() if c not in sacar_salida}
        h = hash_pauta(crudo)
        nuevas.setdefault(h, {"senal_id": senal_id, "hash": h, "crudo": crudo, "salida": salida,
                              "estado": f.estado, "usuario": f.usuario, "actualizado": f.actualizado,
                              "texto": _texto(crudo, salida)})
    con.execute(delete(db.pautas).where(db.pautas.c.senal_id == senal_id))
    filas_nuevas = list(nuevas.values())
    for k in range(0, len(filas_nuevas), 500):
        _insertar(con, filas_nuevas[k:k + 500], pisar=False)
    return {"antes": len(filas), "despues": len(nuevas), "columnas": sorted(sacar_crudo | sacar_salida)}


def migrar_hashes(con) -> None:
    """Recalcula los hashes guardados con una forma anterior. Corre al arrancar; si ya está hecho, no hace nada."""
    hecha = con.execute(select(db.ajustes.c.valor).where(db.ajustes.c.clave == "version_hash")).scalar()
    if hecha == VERSION_HASH:
        return
    for senal_id in con.execute(select(db.pautas.c.senal_id).distinct()).scalars().all():
        _rehacer(con, senal_id, sacar_horario=False)
    con.execute(delete(db.ajustes).where(db.ajustes.c.clave == "version_hash"))
    con.execute(insert(db.ajustes).values(clave="version_hash", valor=VERSION_HASH))


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


def _filtro_sql(senal_id: str, estado: str | None, q: str) -> list:
    c = db.pautas.c
    filtro = [c.senal_id == senal_id]
    if estado:
        filtro.append(c.estado == estado)
    for palabra in _texto({}, {"q": q}).split():
        filtro.append(c.texto.contains(palabra, autoescape=True))
    return filtro


def _cumple(salida: dict, filtros: dict[str, str]) -> bool:
    return all(normalizar(salida.get(col)) == normalizar(valor) for col, valor in filtros.items())


def listar(senal_id: str, estado: str | None = None, q: str = "", desde: int = 0,
           filtros: dict[str, str] | None = None) -> dict:
    """Pautas de la señal. `filtros` = {columna: valor} sobre la salida, sin importar mayúsculas ni signos."""
    c = db.pautas.c
    consulta = (select(c.hash, c.crudo, c.salida, c.estado, c.usuario, c.actualizado)
                .where(*_filtro_sql(senal_id, estado, q)).order_by(c.actualizado.desc(), c.hash))
    with db.transaccion() as con:
        if filtros:
            # La salida es JSON: filtrar por columna en SQL depende del motor, y una señal tiene pocas miles.
            todas = [f for f in con.execute(consulta).all() if _cumple(f.salida, filtros)]
            total, filas = len(todas), todas[desde:desde + POR_PAGINA]
        else:
            total = con.execute(select(func.count()).select_from(db.pautas)
                                .where(*_filtro_sql(senal_id, estado, q))).scalar()
            filas = con.execute(consulta.offset(desde).limit(POR_PAGINA)).all()
        por_estado = dict(con.execute(select(c.estado, func.count()).where(c.senal_id == senal_id)
                                      .group_by(c.estado)).all())
    return {"total": total, "por_estado": por_estado,
            "pautas": [{**f._mapping, "actualizado": f.actualizado.isoformat(timespec="minutes")} for f in filas]}


def hashes_filtrados(senal_id: str, estado: str | None = None, q: str = "",
                     filtros: dict[str, str] | None = None) -> list[str]:
    c = db.pautas.c
    with db.transaccion() as con:
        filas = con.execute(select(c.hash, c.salida).where(*_filtro_sql(senal_id, estado, q))).all()
    return [h for h, salida in filas if _cumple(salida, filtros or {})]


def valores(senal_id: str, columna: str) -> list[dict]:
    """Valores distintos de una columna de salida, con cuántas pautas tienen cada uno, para los filtros."""
    with db.transaccion() as con:
        salidas = con.execute(select(db.pautas.c.salida).where(db.pautas.c.senal_id == senal_id)).scalars()
        cuenta: dict[str, dict] = {}
        for salida in salidas:
            v = salida.get(columna)
            if v is None or v == "":
                continue
            g = cuenta.setdefault(normalizar(v), {"valor": v, "pautas": 0})
            g["pautas"] += 1
    return sorted(cuenta.values(), key=lambda g: (-g["pautas"], str(g["valor"])))


def editar_varias(senal_id: str, hashes: list[str], columna: str, valor, usuario: str) -> int:
    """Pone `valor` en `columna` de todas esas pautas, que quedan como editadas."""
    c = db.pautas.c
    ahora = dt.datetime.now()
    with db.transaccion() as con:
        filas = con.execute(select(c.hash, c.crudo, c.salida)
                            .where(c.senal_id == senal_id, c.hash.in_(hashes))).all()
        for h, crudo, salida in filas:
            nueva = {**salida, columna: valor}
            con.execute(update(db.pautas).where(c.senal_id == senal_id, c.hash == h).values(
                salida=nueva, estado="editada", usuario=usuario, actualizado=ahora, texto=_texto(crudo, nueva)))
    return len(filas)


def olvidar_varias(senal_id: str, hashes: list[str]) -> int:
    with db.transaccion() as con:
        return con.execute(delete(db.pautas).where(db.pautas.c.senal_id == senal_id,
                                                   db.pautas.c.hash.in_(hashes))).rowcount


def cargar_ejemplo(receta: m.Senal, entrada: bytes, esperado: bytes, usuario: str) -> dict:
    """Suma a la base las pautas de un ejemplo, sin pisar las que ya están."""
    crudo = inputs.leer_ejemplo(entrada, receta.entrada)
    terminado = pd.read_excel(io.BytesIO(esperado), dtype=object)
    terminado = terminado.astype(object).where(terminado.notna(), None)
    pautas, conflictos = desde_ejemplo(crudo, terminado, receta.validaciones)
    return {"agregadas": guardar(receta.id, pautas, "revisada", usuario), "conflictos": conflictos}
