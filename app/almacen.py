"""Recetas (con historial) y ejemplos antes/después, guardados en la base."""
import datetime as dt
import hashlib
import json
import re
from dataclasses import dataclass

from sqlalchemy import delete, insert, select, update

from app import db
from app.engine import model as m

ID_VALIDO = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class NoExiste(Exception):
    pass


@dataclass
class Conflicto(Exception):
    """Otro guardó la señal después de que la abriste."""
    usuario: str
    fecha: dt.datetime


def _validar_id(valor: str, que: str = "Id") -> str:
    # Los ids salen de la URL: se limitan a algo predecible.
    if not ID_VALIDO.match(valor):
        raise ValueError(f"{que} inválido: {valor!r} (solo minúsculas, números, - y _)")
    return valor


def calcular_version(receta: dict) -> str:
    texto = json.dumps(receta, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(texto.encode()).hexdigest()[:16]


def listar() -> list[dict]:
    with db.transaccion() as con:
        filas = con.execute(select(db.senales.c.id, db.senales.c.nombre).order_by(db.senales.c.id)).all()
    return [{"id": i, "nombre": n} for i, n in filas]


def leer(senal_id: str) -> m.Senal:
    with db.transaccion() as con:
        receta = con.execute(select(db.senales.c.receta).where(db.senales.c.id == _validar_id(senal_id))).scalar()
    if receta is None:
        raise NoExiste(senal_id)
    return m.Senal.model_validate(receta)


def version(senal_id: str) -> str | None:
    with db.transaccion() as con:
        return con.execute(select(db.senales.c.version).where(db.senales.c.id == _validar_id(senal_id))).scalar()


def guardar(senal: m.Senal, usuario: str, esperada: str | None = None) -> str:
    """Guarda y devuelve la versión nueva. Con `esperada`, falla con Conflicto si alguien guardó antes.

    El chequeo es parte del mismo UPDATE, así dos guardados simultáneos no se pisan, y el historial
    va en la misma transacción: o queda todo o no queda nada.
    """
    _validar_id(senal.id)
    receta = senal.model_dump(mode="json", exclude_none=True)
    nueva, ahora = calcular_version(receta), dt.datetime.now()
    valores = dict(nombre=senal.nombre, receta=receta, version=nueva, actualizado=ahora, actualizado_por=usuario)
    with db.transaccion() as con:
        filtro = db.senales.c.id == senal.id
        if esperada is not None:
            filtro &= db.senales.c.version == esperada
        if con.execute(update(db.senales).where(filtro).values(**valores)).rowcount == 0:
            actual = con.execute(select(db.senales.c.actualizado_por, db.senales.c.actualizado)
                                 .where(db.senales.c.id == senal.id)).first()
            if actual is not None:
                if esperada is not None:
                    raise Conflicto(*actual)
            else:
                con.execute(insert(db.senales).values(id=senal.id, **valores))
        con.execute(insert(db.senales_historial).values(senal_id=senal.id, receta=receta, usuario=usuario, fecha=ahora))
    return nueva


def historial(senal_id: str) -> list[dict]:
    with db.transaccion() as con:
        filas = con.execute(select(db.senales_historial.c.usuario, db.senales_historial.c.fecha)
                            .where(db.senales_historial.c.senal_id == _validar_id(senal_id))
                            .order_by(db.senales_historial.c.fecha)).all()
    return [{"usuario": u, "fecha": f} for u, f in filas]


def guardar_ejemplo(senal_id: str, nombre: str, entrada: bytes, esperado: bytes, usuario: str = "") -> None:
    _validar_id(senal_id)
    _validar_id(nombre, "Nombre de ejemplo")
    clave = (db.ejemplos.c.senal_id == senal_id) & (db.ejemplos.c.nombre == nombre)
    with db.transaccion() as con:
        con.execute(delete(db.ejemplos).where(clave))
        con.execute(insert(db.ejemplos).values(senal_id=senal_id, nombre=nombre, entrada=entrada, esperado=esperado,
                                               subido_por=usuario, fecha=dt.datetime.now()))


def listar_ejemplos(senal_id: str) -> list[str]:
    with db.transaccion() as con:
        return list(con.execute(select(db.ejemplos.c.nombre).where(db.ejemplos.c.senal_id == _validar_id(senal_id))
                                .order_by(db.ejemplos.c.nombre)).scalars())


def leer_ejemplo(senal_id: str, nombre: str) -> tuple[bytes, bytes]:
    """(entrada, esperado) como bytes de Excel."""
    with db.transaccion() as con:
        fila = con.execute(select(db.ejemplos.c.entrada, db.ejemplos.c.esperado)
                           .where(db.ejemplos.c.senal_id == _validar_id(senal_id),
                                  db.ejemplos.c.nombre == _validar_id(nombre, "Nombre de ejemplo"))).first()
    if fila is None:
        raise NoExiste(nombre)
    return bytes(fila[0]), bytes(fila[1])


def borrar_ejemplo(senal_id: str, nombre: str) -> None:
    with db.transaccion() as con:
        con.execute(delete(db.ejemplos).where(db.ejemplos.c.senal_id == _validar_id(senal_id),
                                              db.ejemplos.c.nombre == _validar_id(nombre, "Nombre de ejemplo")))
