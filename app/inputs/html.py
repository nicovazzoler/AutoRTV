"""HTML de una página de grilla (el outerHTML copiado del navegador): un bloque por programa."""
from collections import Counter
from typing import BinaryIO

import pandas as pd

from app.engine import model as m

ATRIBUTOS_IGNORADOS = {"class", "style", "id", "tabindex", "role", "href", "src", "aria-hidden"}
MINIMO_BLOQUES = 5


def _sopa(origen: BinaryIO):
    from bs4 import BeautifulSoup  # solo hace falta si llega un HTML

    return BeautifulSoup(origen.read(), "html.parser")


def _texto(el) -> str | None:
    return " ".join(el.get_text(" ").split()) or None


def _nombre(clase: str) -> str:
    # "tve-schedule__show" → "show": el prefijo se repite en todas y no dice nada.
    return clase.rsplit("__", 1)[-1]


def _clases_hijas(el) -> list[str]:
    return [h["class"][0] for h in el.find_all(class_=True) if _texto(h)]


def detectar_bloque(sopa) -> str | None:
    """El elemento con clase que más se repite y que adentro tiene al menos dos datos con clase propia."""
    cuenta = Counter((el.name, el["class"][0]) for el in sopa.find_all(class_=True))
    candidatos = []
    for (tag, clase), n in cuenta.items():
        if n < MINIMO_BLOQUES:
            continue
        muestra = sopa.find(tag, class_=clase)
        hijas = set(_clases_hijas(muestra))
        datos = len(hijas) + sum(a.startswith("data-") for a in muestra.attrs)
        if datos >= 2:
            candidatos.append((n, datos, f"{tag}.{clase}"))
    return max(candidatos)[2] if candidatos else None


def _campos_automaticos(bloques) -> dict[str, m.CampoHtml]:
    campos: dict[str, m.CampoHtml] = {}
    for b in bloques[:20]:
        for a in b.attrs:
            if a not in ATRIBUTOS_IGNORADOS:
                campos.setdefault(a, m.CampoHtml(attr=a))
        for clase in _clases_hijas(b):
            campos.setdefault(_nombre(clase), m.CampoHtml(css=f".{clase}"))
    return campos


def _leer_campo(bloque, campo: m.CampoHtml):
    el = bloque.select_one(campo.css) if campo.css else bloque
    if el is None:
        return None
    if campo.attr:
        v = el.get(campo.attr)
        return " ".join(v) if isinstance(v, list) else v
    return _texto(el)


def leer(origen: BinaryIO, entrada: m.EntradaHtml) -> pd.DataFrame:
    sopa = _sopa(origen)
    selector = entrada.bloque or detectar_bloque(sopa)
    if not selector:
        raise ValueError("No encontré un bloque que se repita por programa: hay que indicar el selector")
    bloques = sopa.select(selector)
    if not bloques:
        raise ValueError(f"No hay elementos que cumplan {selector!r}")
    campos = entrada.campos or _campos_automaticos(bloques)
    filas = [{nombre: _leer_campo(b, c) for nombre, c in campos.items()} for b in bloques]
    return pd.DataFrame(filas, columns=list(campos)).astype(object).where(lambda d: d.notna(), None)
