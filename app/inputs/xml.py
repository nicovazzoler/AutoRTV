"""XML: XMLTV (el estándar de EPG) o cualquier XML con un elemento por programa."""
import datetime as dt
import re
from typing import BinaryIO

import pandas as pd
from defusedxml import ElementTree

from app.engine import model as m

# XMLTV: "20261013171910 -0300". Se respeta la hora como viene, sin pasar a otra zona.
FECHA_XMLTV = re.compile(r"^(\d{14})(?:\s*[+-]\d{4})?$")


def _sin_espacio(etiqueta: str) -> str:
    return etiqueta.rsplit("}", 1)[-1]


def _valor(texto: str | None):
    if texto is None:
        return None
    texto = " ".join(texto.split())
    if g := FECHA_XMLTV.match(texto):
        return dt.datetime.strptime(g[1], "%Y%m%d%H%M%S")
    return texto or None


def leer(origen: BinaryIO, entrada: m.EntradaXml) -> pd.DataFrame:
    raiz = ElementTree.parse(origen).getroot()
    etiqueta = entrada.elemento or "programme"
    filas = []
    for el in raiz.iter():
        if _sin_espacio(el.tag) != etiqueta:
            continue
        fila = {k: _valor(v) for k, v in el.attrib.items()}
        for hijo in el:
            nombre = _sin_espacio(hijo.tag)
            texto = _valor("".join(hijo.itertext()))
            if texto is not None and fila.get(nombre) is None:
                fila[nombre] = texto
            for k, v in hijo.attrib.items():  # p. ej. <episode-num system="xmltv_ns">
                fila.setdefault(f"{nombre} {k}", _valor(v))
        filas.append(fila)
    if not filas:
        raise ValueError(f"El XML no tiene elementos <{etiqueta}>")
    return pd.DataFrame(filas).astype(object).where(lambda d: d.notna(), None)
