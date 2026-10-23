"""Excel subidos, en memoria, para que la vista previa no reenvíe el archivo en cada cambio."""
import io
import secrets
from collections import OrderedDict

import pandas as pd

from app.engine import model as m
from app.inputs import excel

MAXIMO = 20
_archivos: OrderedDict[str, bytes] = OrderedDict()
_leidas: dict[tuple[str, str], pd.DataFrame] = {}


def subir(contenido: bytes) -> str:
    tabla_id = secrets.token_urlsafe(12)
    _archivos[tabla_id] = contenido
    while len(_archivos) > MAXIMO:
        viejo, _ = _archivos.popitem(last=False)
        for clave in [k for k in _leidas if k[0] == viejo]:
            del _leidas[clave]
    return tabla_id


def tabla(tabla_id: str, entrada: m.EntradaExcel) -> pd.DataFrame:
    """La tabla leída con esa config de entrada. KeyError si el archivo ya no está."""
    contenido = _archivos[tabla_id]
    _archivos.move_to_end(tabla_id)
    clave = (tabla_id, entrada.model_dump_json())
    if clave not in _leidas:
        _leidas[clave] = excel.leer(io.BytesIO(contenido), entrada)
    return _leidas[clave].copy()
