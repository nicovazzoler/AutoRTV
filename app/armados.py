"""El agente arma las reglas de una señal solo, en segundo plano, al crearla o al sumarle ejemplos si no tiene reglas."""
import datetime as dt
import io
import threading

import pandas as pd
from sqlalchemy import delete, insert, select, update

from app import almacen, catalogo, db, inputs
from app.agent import armado, asistente, cliente, uso

MAX_EJEMPLOS = 3
# Los tests lo apagan para que el armado corra en el mismo pedido.
EN_HILO = True
_en_marcha: set[str] = set()
_repetir: set[str] = set()
_candado = threading.Lock()


def _ahora() -> dt.datetime:
    return dt.datetime.now().replace(microsecond=0)


def leer(senal_id: str) -> dict | None:
    with db.transaccion() as con:
        r = con.execute(select(db.armados).where(db.armados.c.senal_id == senal_id)).first()
    if r is None:
        return None
    return {"estado": r.estado, "usuario": r.usuario, "inicio": r.inicio.isoformat(),
            "fin": r.fin.isoformat() if r.fin else None, "mensaje": r.mensaje, "antes": r.antes, "despues": r.despues}


def _guardar(senal_id: str, **valores) -> None:
    with db.transaccion() as con:
        con.execute(update(db.armados).where(db.armados.c.senal_id == senal_id).values(**valores))


def cortar_colgados() -> None:
    with db.transaccion() as con:
        con.execute(update(db.armados).where(db.armados.c.estado == "armando")
                    .values(estado="error", fin=_ahora(), mensaje="Se reinició el servidor en el medio: probá de nuevo."))


def lanzar(senal_id: str, usuario: str) -> bool:
    """Arranca el armado si hay agente y ejemplos. Si ya hay uno en marcha, se repite al terminar (llegó un ejemplo nuevo)."""
    proveedor = cliente.proveedor_configurado()
    if proveedor is None or not almacen.listar_ejemplos(senal_id):
        return False
    with _candado:
        if senal_id in _en_marcha:
            _repetir.add(senal_id)
            return True
        _en_marcha.add(senal_id)
    with db.transaccion() as con:
        con.execute(delete(db.armados).where(db.armados.c.senal_id == senal_id))
        con.execute(insert(db.armados).values(senal_id=senal_id, usuario=usuario, inicio=_ahora(), estado="armando",
                                              mensaje="El agente está armando las reglas desde los ejemplos"))
    trabajo = lambda: _correr(senal_id, usuario, proveedor)  # noqa: E731
    if EN_HILO:
        threading.Thread(target=trabajo, daemon=True, name=f"armado-{senal_id}").start()
    else:
        trabajo()
    return True


def _ejemplos(receta) -> list[asistente.Ejemplo]:
    """Los más recientes primero: el primero es el que tiene que quedar al 100 %."""
    lista = []
    for nombre in list(reversed(almacen.listar_ejemplos(receta.id)))[:MAX_EJEMPLOS]:
        entrada, esperado = almacen.leer_ejemplo(receta.id, nombre)
        lista.append(asistente.Ejemplo(nombre, inputs.leer_ejemplo(entrada, receta.entrada),
                                       pd.read_excel(io.BytesIO(esperado), dtype=object)))
    return lista


def _correr(senal_id: str, usuario: str, proveedor) -> None:
    try:
        receta, version = almacen.leer(senal_id), almacen.version(senal_id)
        ejemplos = _ejemplos(receta)
        cat = catalogo.leer()
        entorno = asistente.Entorno(reglas_catalogo=[f"{c.nombre}: {c.regla or c.tipo}" for c in cat])
        r = armado.armar(receta, ejemplos, ejemplos[0].nombre, proveedor, [c.nombre for c in cat], entorno)
        for p in r.pedidos:
            uso.registrar(usuario, senal_id, "[armar reglas]", p.vueltas, p.tokens_entrada, p.tokens_salida,
                          p.logrado, p.modelo)
        if r.receta is None:
            _guardar(senal_id, estado="sin_mejora", fin=_ahora(), antes=r.antes, despues=r.antes,
                     mensaje="El agente no encontró reglas que mejoren el ejemplo. " + " ".join(r.problemas)[:1500])
            return
        try:
            almacen.guardar(r.receta, "agente", esperada=version)
        except almacen.Conflicto:
            _guardar(senal_id, estado="sin_mejora", fin=_ahora(), antes=r.antes, despues=r.despues,
                     mensaje="Alguien cambió las reglas mientras el agente trabajaba: no se pisaron. Probá de nuevo.")
            return
        modelos = " y ".join(dict.fromkeys(r.modelos))
        _guardar(senal_id, estado="aplicado", fin=_ahora(), antes=r.antes, despues=r.despues,
                 mensaje=f"Reglas armadas por el agente ({modelos}): el ejemplo pasó de {r.antes:g} % a {r.despues:g} %.")
    except Exception as e:
        _guardar(senal_id, estado="error", fin=_ahora(), mensaje=f"{type(e).__name__}: {e}"[:1500])
    finally:
        with _candado:
            _en_marcha.discard(senal_id)
            otra_vez = senal_id in _repetir
            _repetir.discard(senal_id)
        if otra_vez:
            lanzar(senal_id, usuario)
