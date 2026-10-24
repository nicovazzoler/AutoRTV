"""Catálogo general de columnas del EPG: orden por defecto y reglas de cada columna.

Lo carga el admin desde un Excel (columna, regla, significado). Vive en la base porque es el
formato del laburo y no va al repo.
"""
import io
import re
import unicodedata
from dataclasses import asdict, dataclass

import pandas as pd
from sqlalchemy import delete, insert, select

from app import db

# Van primero aunque el Excel no las traiga.
FIJAS = [("N", "entero"), ("DIA", "texto")]
OBLIGATORIAS = {"fecha": "si", "hora": "si", "duracion": "si", "tit orig": "si", "tit princ": "si",
                "tit ing": "ing", "tit port": "port"}


@dataclass
class ColumnaCatalogo:
    nombre: str
    tipo: str
    regla: str = ""
    significado: str = ""
    maximo: int | None = None
    valores: list[str] | None = None
    obligatoria: str = "no"


def clave(nombre: str) -> str:
    """Nombre comparable: sin tildes, minúsculas y espacios simples ("Duración " → "duracion")."""
    s = unicodedata.normalize("NFD", str(nombre)).encode("ascii", "ignore").decode()
    return " ".join(s.lower().split())


def interpretar(nombre: str, regla) -> ColumnaCatalogo:
    """Pasa la regla escrita a mano ("99 caracteres como max", "INT 720 max", "A - M") a algo chequeable."""
    texto = "" if regla is None else str(regla).strip()
    bajo = texto.lower()
    numeros = [int(n) for n in re.findall(r"\d+", texto)]
    c = ColumnaCatalogo(nombre=str(nombre).strip(), tipo="texto", regla=texto,
                        obligatoria=OBLIGATORIAS.get(clave(nombre), "no"))
    if bajo in ("fecha", "hora"):
        c.tipo = bajo
    elif bajo.startswith("int"):
        if "caracter" in bajo and numeros:  # "INT si o si 4 caracteres numerales"
            c.tipo, c.maximo = "anio", numeros[0]
        else:
            c.tipo, c.maximo = "entero", (numeros[0] if numeros else None)
    elif "caracter" in bajo:
        c.tipo, c.maximo = "texto", (numeros[0] if numeros else None)
    elif " - " in texto:
        c.tipo, c.valores = "valores", [v.strip() for v in texto.split(" - ") if v.strip()]
    elif texto:  # un valor fijo: "X" o 1
        c.tipo, c.valores = "valores", [texto[:-2] if texto.endswith(".0") else texto]
    return c


def desde_excel(contenido: bytes) -> list[ColumnaCatalogo]:
    df = pd.read_excel(io.BytesIO(contenido), dtype=object)
    if df.shape[1] < 2:
        raise ValueError("El Excel tiene que tener al menos dos columnas: columna y regla")
    columnas = []
    for _, fila in df.iterrows():
        nombre = fila.iloc[0]
        if nombre is None or (isinstance(nombre, float) and pd.isna(nombre)) or not str(nombre).strip():
            continue
        regla = fila.iloc[1] if not (isinstance(fila.iloc[1], float) and pd.isna(fila.iloc[1])) else None
        c = interpretar(nombre, regla)
        if df.shape[1] > 2 and isinstance(fila.iloc[2], str):
            c.significado = fila.iloc[2].strip()
        columnas.append(c)
    ya = {clave(c.nombre) for c in columnas}
    fijas = [ColumnaCatalogo(nombre=n, tipo=t) for n, t in FIJAS if clave(n) not in ya]
    return fijas + columnas


def guardar(columnas: list[ColumnaCatalogo]) -> None:
    with db.transaccion() as con:
        con.execute(delete(db.catalogo))
        for i, c in enumerate(columnas):
            con.execute(insert(db.catalogo).values(orden=i, **asdict(c)))


def leer() -> list[ColumnaCatalogo]:
    with db.transaccion() as con:
        filas = con.execute(select(db.catalogo).order_by(db.catalogo.c.orden)).mappings().all()
    return [ColumnaCatalogo(**{k: v for k, v in f.items() if k != "orden"}) for f in filas]


def ordenar(columnas: list[str], catalogo: list[ColumnaCatalogo]) -> list[str]:
    """Las del catálogo primero, en su orden; las que no están, después y como venían."""
    posicion = {clave(c.nombre): i for i, c in enumerate(catalogo)}
    return sorted(columnas, key=lambda c: (posicion.get(clave(c), len(posicion)), columnas.index(c)))
