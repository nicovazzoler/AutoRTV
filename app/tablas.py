"""Grillas subidas para la vista previa (Excel, PDF, XML, HTML o texto). Viven en la base, así cualquier réplica los encuentra.

Cada proceso guarda además un cache chico de tablas ya leídas, para no releer el Excel en cada tecla.
"""
import datetime as dt
import secrets
from collections import OrderedDict

import pandas as pd
from sqlalchemy import delete, insert, select

from app import db
from app import inputs

MAXIMO_EN_MEMORIA = 20
VIGENCIA = dt.timedelta(hours=24)
_leidas: OrderedDict[tuple[str, str], pd.DataFrame] = OrderedDict()


def subir(contenido: bytes) -> str:
    tabla_id = secrets.token_urlsafe(12)
    ahora = dt.datetime.now()
    with db.transaccion() as con:
        con.execute(delete(db.tablas_subidas).where(db.tablas_subidas.c.creada < ahora - VIGENCIA))
        con.execute(insert(db.tablas_subidas).values(id=tabla_id, contenido=contenido, creada=ahora))
    return tabla_id


def asegurar(tabla_id: str, contenido: bytes) -> None:
    """Vuelve a guardar una grilla que venció, con el mismo id: la semana abierta de una señal dura más de 24 h."""
    with db.transaccion() as con:
        if con.execute(select(db.tablas_subidas.c.id).where(db.tablas_subidas.c.id == tabla_id)).first() is None:
            con.execute(insert(db.tablas_subidas).values(id=tabla_id, contenido=contenido, creada=dt.datetime.now()))


def tabla(tabla_id: str, entrada) -> pd.DataFrame:
    """La tabla leída con esa config de entrada. KeyError si el archivo no existe o venció."""
    clave = (tabla_id, entrada.model_dump_json())
    if clave not in _leidas:
        with db.transaccion() as con:
            contenido = con.execute(select(db.tablas_subidas.c.contenido)
                                    .where(db.tablas_subidas.c.id == tabla_id)).scalar()
        if contenido is None:
            raise KeyError(tabla_id)
        _leidas[clave] = inputs.leer(bytes(contenido), entrada)
        while len(_leidas) > MAXIMO_EN_MEMORIA:
            _leidas.popitem(last=False)
    _leidas.move_to_end(clave)
    return _leidas[clave].copy()


def olvidar_cache() -> None:
    """Simula otra réplica (tests)."""
    _leidas.clear()
