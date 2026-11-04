"""Lo que recibe y devuelve el código de una señal: datos simples que entran en JSON.

El lector recibe el archivo (celdas, texto o páginas). El paso final recibe el EPG como filas con los valores tal
como los ve una persona (01/10/2026, 06:00) y los devuelve igual; acá se vuelven a pasar a fecha y hora.
"""
import datetime as dt
import io
import math
import re

import pandas as pd

from app import export

MAX_HOJAS = 31
MAX_FILAS = 5000
MAX_COLUMNAS = 80
MAX_TEXTO = 2_000_000
MAX_PAGINAS = 40
FILA = "_fila"  # en el paso final: de qué fila del EPG viene cada una; las agregadas no la traen
FECHA_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2})?)?$")
HORA_ISO = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")


def valor(v):
    """Un valor de celda que entra en JSON: fechas y horas en ISO (2026-11-02T06:00:00, 06:00:00)."""
    if v is None or (isinstance(v, float) and math.isnan(v)) or v is pd.NaT:
        return None
    if isinstance(v, (dt.datetime, dt.date, dt.time)):
        return v.isoformat()
    if isinstance(v, (bool, int, float, str)):
        return v
    if hasattr(v, "item"):  # números de numpy
        return v.item()
    return str(v)


def del_archivo(contenido: bytes, nombre: str = "") -> dict:
    """El archivo de la grilla para un lector en código. Un zip trae cada archivo adentro, con su nombre."""
    from app import inputs
    from app.inputs import texto, varios

    try:
        tipo = inputs.detectar(contenido).tipo
    except ValueError:
        tipo = "texto"
    if tipo == "varios":
        return {"tipo": "varios", "nombre": nombre,
                "archivos": [del_archivo(datos, n) for n, datos in varios.archivos(contenido)]}
    if tipo == "excel":
        return {"tipo": "excel", "nombre": nombre, "hojas": _excel(contenido)}
    if tipo == "pdf":
        return {"tipo": "pdf", "nombre": nombre, "paginas": _pdf(contenido)}
    if tipo == "word":
        return {"tipo": "word", "nombre": nombre, **_word(contenido)}
    return {"tipo": tipo, "nombre": nombre, "texto": texto.decodificar(contenido)[:MAX_TEXTO]}


def _excel(contenido: bytes) -> list[dict]:
    from app.inputs import cuadricula

    hojas = []
    for nombre, celdas, combinadas in cuadricula.todas_las_celdas(contenido, MAX_HOJAS):
        ancho = max((i + 1 for fila in celdas for i, v in enumerate(fila[:MAX_COLUMNAS]) if v is not None), default=0)
        hojas.append({"nombre": nombre, "celdas": [[valor(v) for v in fila[:ancho]] for fila in celdas[:MAX_FILAS]],
                      "combinadas": [list(c) for c in combinadas], "recortada": len(celdas) > MAX_FILAS})
    return hojas


def _pdf(contenido: bytes) -> list[dict]:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(contenido)) as pdf:
        return [{"numero": i + 1, "texto": p.extract_text() or "", "tablas": p.extract_tables()}
                for i, p in enumerate(pdf.pages[:MAX_PAGINAS])]


def _word(contenido: bytes) -> dict:
    import zipfile

    from defusedxml import ElementTree

    from app.inputs.word import W, _texto

    raiz = ElementTree.fromstring(zipfile.ZipFile(io.BytesIO(contenido)).read("word/document.xml"))
    tablas = [[[_texto(c) for c in fila.iter(f"{W}tc")] for fila in t.iter(f"{W}tr")] for t in raiz.iter(f"{W}tbl")]
    return {"parrafos": [x for p in raiz.iter(f"{W}p") if (x := _texto(p))], "tablas": tablas}


def _clase(serie: pd.Series) -> str | None:
    """Cómo volver a pasar una columna del EPG desde texto: la clase de sus valores, si son todos de una."""
    clases = set()
    for v in serie:
        if v is None or (isinstance(v, float) and math.isnan(v)) or v is pd.NaT:
            continue
        if isinstance(v, pd.Timestamp):
            v = v.to_pydatetime()
        if isinstance(v, dt.datetime):
            clases.add("fecha" if v.time() == dt.time(0) else "fecha_hora")
        elif isinstance(v, dt.date):
            clases.add("fecha")
        elif isinstance(v, dt.time):
            clases.add("hora")
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            clases.add("numero")
        else:
            return None
    return clases.pop() if len(clases) == 1 else None


FORMATOS = {"fecha": ("%d/%m/%Y",), "fecha_hora": ("%d/%m/%Y %H:%M", "%d/%m/%Y"), "hora": ("%H:%M", "%H:%M:%S")}


def _volver(v, clase: str | None):
    if not isinstance(v, str) or clase is None:
        return v
    if clase == "numero":
        try:
            return int(v) if v.strip().lstrip("-").isdigit() else float(v.replace(",", "."))
        except ValueError:
            return v
    for formato in FORMATOS[clase]:
        try:
            momento = dt.datetime.strptime(v.strip(), formato)
        except ValueError:
            continue
        return momento.time() if clase == "hora" else momento
    return v


def de_tabla(df: pd.DataFrame) -> list[dict]:
    """El EPG como filas para el paso final, cada una con su número en `_fila`."""
    columnas = [str(c) for c in df.columns]
    return [{**dict(zip(columnas, fila)), FILA: i} for i, fila in enumerate(export.a_filas(df))]


def a_tabla(filas, antes: pd.DataFrame) -> tuple[pd.DataFrame, list[int | None]]:
    """Las filas que devolvió el paso final como tabla, y de qué fila del EPG viene cada una (None = agregada)."""
    if not isinstance(filas, list) or not all(isinstance(f, dict) for f in filas):
        raise ValueError("El paso final tiene que devolver una lista de filas (diccionarios columna → valor).")
    columnas = [str(c) for c in antes.columns]
    nuevas = list(dict.fromkeys(k for f in filas for k in f if k != FILA and k not in columnas))
    origen = [f.get(FILA) if isinstance(f.get(FILA), int) and 0 <= f.get(FILA) < len(antes) else None for f in filas]
    clases = {str(c): _clase(antes[c]) for c in antes.columns}
    datos = [[_volver(f.get(c), clases.get(c)) for c in columnas + nuevas] for f in filas]
    return pd.DataFrame(datos, columns=columnas + nuevas, dtype=object), origen


def _hora_iso(v: str) -> dt.time:
    return dt.datetime.strptime(v, "%H:%M:%S" if v.count(":") == 2 else "%H:%M").time()


def tipar(tabla: pd.DataFrame) -> pd.DataFrame:
    """Las columnas que devolvió un lector en código con fechas u horas ISO, como fecha y hora: igual que un Excel."""
    tabla = tabla.copy()
    for c in tabla.columns:
        valores = [v for v in tabla[c] if v is not None and not (isinstance(v, float) and math.isnan(v))]
        if not valores or not all(isinstance(v, str) for v in valores):
            continue
        if all(FECHA_ISO.match(v.strip()) for v in valores):
            tabla[c] = [dt.datetime.fromisoformat(v.strip()) if isinstance(v, str) else None for v in tabla[c]]
        elif all(HORA_ISO.match(v.strip()) for v in valores):
            tabla[c] = [_hora_iso(v.strip()) if isinstance(v, str) else None for v in tabla[c]]
    return tabla
