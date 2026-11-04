"""Corridas del banco de agentes: se lanzan en un hilo aparte (tardan minutos) y van guardando el progreso en la base."""
import datetime as dt
import threading

from sqlalchemy import desc, insert, select, update

from app import almacen, db
from app.agent import banco, uso

MAX_SENALES = 20
MAX_SENALES_SIN_AGENTE = 600  # el diagnóstico no gasta: puede pasar por todas
_candado = threading.Lock()


class YaCorriendo(Exception):
    pass


def _ahora() -> dt.datetime:
    return dt.datetime.now().replace(microsecond=0)


def _fila(r) -> dict:
    return {"id": r.id, "usuario": r.usuario, "inicio": r.inicio.isoformat(), "fin": r.fin.isoformat() if r.fin else None,
            "estado": r.estado, "parametros": r.parametros, "progreso": r.progreso, "gastado": round(r.gastado or 0, 4),
            "resultado": r.resultado}


def leer(corrida_id: int) -> dict | None:
    with db.transaccion() as con:
        r = con.execute(select(db.banco_corridas).where(db.banco_corridas.c.id == corrida_id)).first()
    return _fila(r) if r else None


def listar(limite: int = 10) -> list[dict]:
    t = db.banco_corridas
    with db.transaccion() as con:
        filas = con.execute(select(t).order_by(desc(t.c.id)).limit(limite)).all()
    return [{**_fila(r), "resultado": None} for r in filas]


def _guardar(corrida_id: int, **cambios) -> None:
    with db.transaccion() as con:
        con.execute(update(db.banco_corridas).where(db.banco_corridas.c.id == corrida_id).values(**cambios))


def cortar_colgadas() -> None:
    """Las que quedaron "corriendo" de antes de un reinicio no van a terminar nunca."""
    with db.transaccion() as con:
        con.execute(update(db.banco_corridas).where(db.banco_corridas.c.estado == "corriendo")
                    .values(estado="cortada", fin=_ahora(), progreso="Se reinició el servidor en el medio"))


def tope_de_senales(pasos: list[str]) -> int:
    return MAX_SENALES_SIN_AGENTE if set(pasos) <= banco.SIN_AGENTE else MAX_SENALES


def pares_de(senales: list[str], tope: int = MAX_SENALES) -> list[banco.Par]:
    """El ejemplo más reciente de cada señal: la grilla como vino, la macro hecha y cómo la lee hoy la señal."""
    pares = []
    for senal_id in senales[:tope]:
        nombres = almacen.listar_ejemplos(senal_id)
        if not nombres:
            continue
        grilla, esperado = almacen.leer_ejemplo(senal_id, nombres[-1])
        receta = almacen.leer(senal_id)
        pares.append(banco.Par(receta.nombre, grilla, esperado, senal_id, receta.entrada.model_dump()))
    return pares


def lanzar(usuario: str, senales: list[str], tope: float, pasos: list[str], proveedor, en_hilo: bool = True) -> int:
    """Arranca una corrida y devuelve su id. `en_hilo=False` la corre acá mismo (tests)."""
    if not _candado.acquire(blocking=False):
        raise YaCorriendo("Ya hay una corrida del banco en marcha")
    try:
        parametros = {"senales": senales[:tope_de_senales(pasos)], "tope": tope, "pasos": pasos}
        with db.transaccion() as con:
            corrida_id = con.execute(insert(db.banco_corridas).values(
                usuario=usuario, inicio=_ahora(), estado="corriendo", parametros=parametros,
                progreso="Arrancando", gastado=0.0)).inserted_primary_key[0]
    except Exception:
        _candado.release()
        raise
    trabajo = lambda: _correr(corrida_id, usuario, senales, tope, pasos, proveedor)  # noqa: E731
    if en_hilo:
        threading.Thread(target=trabajo, daemon=True, name=f"banco-{corrida_id}").start()
    else:
        trabajo()
    return corrida_id


def _correr(corrida_id: int, usuario: str, senales: list[str], tope: float, pasos: list[str], proveedor) -> None:
    def registrar(senal, modelo, entrada, salida, vueltas, logrado):
        uso.registrar(usuario, senal, "[banco]", vueltas, entrada, salida, logrado, modelo)

    caja = banco.Caja(tope, registrar)
    try:
        resultados, corte = banco.correr_banco(
            pares_de(senales, tope_de_senales(pasos)), proveedor, caja, pasos,
            lambda texto, parciales: _guardar(corrida_id, progreso=texto, gastado=caja.gastado,
                                              resultado={"senales": parciales, "resumen": banco.resumen(parciales)}))
        _guardar(corrida_id, estado="cortada" if corte else "terminada", fin=_ahora(), gastado=caja.gastado,
                 progreso=corte or "Listo",
                 resultado={"senales": resultados, "resumen": banco.resumen(resultados)})
    except Exception as e:
        _guardar(corrida_id, estado="error", fin=_ahora(), gastado=caja.gastado, progreso=f"{type(e).__name__}: {e}")
    finally:
        _candado.release()
