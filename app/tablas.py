"""Grillas subidas para la vista previa (Excel, PDF, XML, HTML o texto). Viven en la base, así cualquier réplica los encuentra.

Cada proceso guarda además un cache chico de tablas ya leídas, para no releer el Excel en cada tecla.
"""
import datetime as dt
import secrets
from collections import OrderedDict

import pandas as pd
from sqlalchemy import delete, insert, select, update

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


def asegurar(tabla_id: str, contenido: bytes, lunes: dt.date | None = None) -> None:
    """Vuelve a guardar una grilla que venció, con el mismo id: la semana abierta de una señal dura más de 24 h."""
    with db.transaccion() as con:
        if con.execute(select(db.tablas_subidas.c.id).where(db.tablas_subidas.c.id == tabla_id)).first() is None:
            con.execute(insert(db.tablas_subidas).values(id=tabla_id, contenido=contenido, creada=dt.datetime.now(),
                                                         lunes=lunes))


def fijar_lunes(tabla_id: str, lunes: dt.date | None) -> None:
    """La grilla pasa a leerse con las fechas de la semana de `lunes` (None = como vino)."""
    with db.transaccion() as con:
        con.execute(update(db.tablas_subidas).where(db.tablas_subidas.c.id == tabla_id).values(lunes=lunes))
    for clave in [k for k in _leidas if k[0] == tabla_id]:
        del _leidas[clave]


def tabla(tabla_id: str, entrada) -> pd.DataFrame:
    """La tabla leída con esa config de entrada. KeyError si el archivo no existe o venció."""
    clave = (tabla_id, entrada.model_dump_json())
    if clave not in _leidas:
        with db.transaccion() as con:
            fila = con.execute(select(db.tablas_subidas.c.contenido, db.tablas_subidas.c.lunes)
                               .where(db.tablas_subidas.c.id == tabla_id)).first()
        if fila is None:
            raise KeyError(tabla_id)
        leida = inputs.leer(bytes(fila.contenido), entrada)
        if fila.lunes:
            from app.fechar import fechar
            leida = fechar(leida, fila.lunes)
        _leidas[clave] = leida
        while len(_leidas) > MAXIMO_EN_MEMORIA:
            _leidas.popitem(last=False)
    _leidas.move_to_end(clave)
    return _leidas[clave].copy()


def olvidar_cache() -> None:
    """Simula otra réplica (tests)."""
    _leidas.clear()
