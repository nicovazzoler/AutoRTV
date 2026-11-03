"""Un .docx: sus tablas (la primera fila de cada una es el encabezado) o, si no tiene, su texto línea por línea."""
import io
import zipfile

import pandas as pd
from defusedxml import ElementTree

from app.engine import model as m

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def es_word(contenido: bytes) -> bool:
    try:
        return "word/document.xml" in zipfile.ZipFile(io.BytesIO(contenido)).namelist()
    except zipfile.BadZipFile:
        return False


def _texto(elemento) -> str:
    return "".join(t.text or "" for t in elemento.iter(f"{W}t")).strip()


def leer(contenido: bytes, entrada: m.EntradaWord) -> pd.DataFrame:
    from app.inputs import texto

    raiz = ElementTree.fromstring(zipfile.ZipFile(io.BytesIO(contenido)).read("word/document.xml"))
    tablas = []
    for tabla in raiz.iter(f"{W}tbl"):
        filas = [[_texto(celda) for celda in fila.iter(f"{W}tc")] for fila in tabla.iter(f"{W}tr")]
        filas = [f for f in filas if any(f)]
        if len(filas) > 1:
            ancho = max(len(f) for f in filas)
            encabezado = [c or f"Columna {i + 1}" for i, c in enumerate(filas[0] + [""] * (ancho - len(filas[0])))]
            tablas.append(pd.DataFrame([f + [None] * (ancho - len(f)) for f in filas[1:]], columns=encabezado, dtype=object))
    if tablas:
        return pd.concat(tablas, ignore_index=True).astype(object)
    lineas = [_texto(p) for p in raiz.iter(f"{W}p")]
    return texto.leer("\n".join(x for x in lineas if x).encode("utf-8"),
                      m.EntradaTexto(tipo="texto", fecha_inicio=entrada.fecha_inicio))
