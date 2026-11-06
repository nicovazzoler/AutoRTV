"""El agente arma las reglas de una señal solo, en segundo plano, al crearla o al sumarle ejemplos si no tiene reglas."""
import datetime as dt
import io
import threading

import pandas as pd
from sqlalchemy import delete, insert, select, update

from app import almacen, catalogo, conversaciones, db, inputs, pautas, trabajos
from app.agent import armado, asistente, cliente, senal, uso
from app.engine import model as m

MAX_EJEMPLOS = 3
# Con esto o más, lo de Haiku alcanza; con menos sigue el agente de la señal.
ALCANZA = 98.0
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


def lanzar(senal_id: str, usuario: str, pedido: str = "") -> bool:
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
    trabajos.lanzar(f"armado-{senal_id}", _correr, (senal_id, usuario, pedido),
                    lambda codigo: _al_terminar(senal_id, usuario, codigo), en_hilo=EN_HILO)
    return True


def _crudos(receta) -> list[tuple[senal.EjemploCrudo, bytes]]:
    """Los ejemplos más recientes primero (el primero es el que tiene que quedar al 100 %), con el EPG en bytes."""
    lista = []
    for nombre in list(reversed(almacen.listar_ejemplos(receta.id)))[:MAX_EJEMPLOS]:
        entrada, esperado = almacen.leer_ejemplo(receta.id, nombre)
        lista.append((senal.EjemploCrudo(nombre, entrada, pd.read_excel(io.BytesIO(esperado), dtype=object)), esperado))
    return lista


def _ejemplos(receta, crudos: list[tuple[senal.EjemploCrudo, bytes]]) -> list[asistente.Ejemplo]:
    """Los ejemplos leídos con la lectura de la señal; vacío si alguno no se lee (eso lo resuelve el agente de la señal)."""
    try:
        return [asistente.Ejemplo(e.nombre, inputs.leer_ejemplo(e.contenido, receta.entrada, esperado), e.esperado)
                for e, esperado in crudos]
    except Exception:
        return []


def _correr(senal_id: str, usuario: str, pedido: str = "") -> None:
    """El armado en sí. Corre en el proceso de las tareas (app.trabajos): trae su propio agente."""
    proveedor = cliente.proveedor_configurado()
    try:
        receta, version = almacen.leer(senal_id), almacen.version(senal_id)
        crudos = _crudos(receta)
        mejor, antes, despues, explicacion, faltan = None, None, None, "", ""
        ejemplos = _ejemplos(receta, crudos)
        # Primero lo barato: Haiku con las tarjetas. Si alguien pidió algo puntual, va directo al agente de la señal.
        if ejemplos and not pedido:
            cat = catalogo.leer()
            entorno = asistente.Entorno(reglas_catalogo=[f"{c.nombre}: {c.regla or c.tipo}" for c in cat])
            r = armado.armar(receta, ejemplos, ejemplos[0].nombre, proveedor, [c.nombre for c in cat], entorno,
                             escalera=False)
            for p in r.pedidos:
                uso.registrar(usuario, senal_id, "[armar reglas]", p.vueltas, p.tokens_entrada, p.tokens_salida,
                              p.logrado, p.modelo)
            mejor, antes, despues = r.receta, r.antes, r.despues
            faltan = " ".join(r.problemas)
        if getattr(proveedor, "con_agente_de_la_senal", True) and (pedido or _le_falta(mejor or receta, [e for e, _ in crudos])):
            _guardar(senal_id, mensaje="El agente está trabajando en la señal")
            t = senal.trabajar(mejor or receta, [e for e, _ in crudos], proveedor, pedido,
                               avisar=lambda texto: _guardar(senal_id, mensaje=f"El agente está trabajando en la señal: {texto}"))
            uso.registrar(usuario, senal_id, "[agente de la señal]", t.pasos, t.tokens_entrada, t.tokens_salida,
                          t.receta is not None, t.modelo)
            antes = t.antes if antes is None else antes
            if t.receta is not None:
                mejor, despues, explicacion = t.receta, t.despues, f"{t.resultado} {t.explicacion}"
            else:
                despues, faltan = despues if despues is not None else t.antes, t.final or faltan
        if mejor is None:
            _guardar(senal_id, estado="sin_mejora", fin=_ahora(), antes=antes, despues=antes,
                     mensaje=("El agente no encontró cómo mejorar el ejemplo. " + faltan)[:1500])
            return
        try:
            _guardar_receta(receta, mejor, version, usuario, crudos)
        except almacen.Conflicto:
            _guardar(senal_id, estado="sin_mejora", fin=_ahora(), antes=antes, despues=despues,
                     mensaje="Alguien cambió las reglas mientras el agente trabajaba: no se pisaron. Probá de nuevo.")
            return
        _guardar(senal_id, estado="aplicado", fin=_ahora(), antes=antes, despues=despues,
                 mensaje=(explicacion.strip() or f"El agente dejó el ejemplo en {despues:g} % (estaba en {antes:g} %).")[:1500])
    except Exception as e:
        _guardar(senal_id, estado="error", fin=_ahora(), mensaje=f"{type(e).__name__}: {e}"[:1500])


def _guardar_receta(antes, despues, version: str, usuario: str, crudos) -> None:
    """Guarda lo del agente sin pisar un cambio del medio, recarga la base si cambió la lectura y avisa si hay
    código."""
    almacen.guardar(despues, "agente", esperada=version)
    if despues.entrada != antes.entrada:  # otra lectura da otras filas crudas: la base se vuelve a cargar con ellas
        for e, esperado in crudos:
            pautas.cargar_ejemplo(despues, e.contenido, esperado, usuario)
    _avisar_codigo(usuario, antes.id, antes, despues)


class CambioLaSenal(Exception):
    pass


def aplicar_del_banco(senal_id: str, receta: dict, version: str, usuario: str) -> str:
    """Guarda la receta que logró el agente en una corrida del Banco, si la señal no cambió desde entonces y si, con
    todos sus ejemplos, mejora el principal sin empeorar los otros (el Banco la probó solo con el más reciente)."""
    actual = almacen.leer(senal_id)
    if almacen.version(senal_id) != version:
        raise CambioLaSenal("La señal cambió desde la corrida: volvé a correr el Banco para esa señal.")
    crudos = _crudos(actual)
    if not crudos:
        raise ValueError("La señal ya no tiene ejemplos con qué comprobarlo.")
    nueva = m.Senal(**receta)
    ejemplos = [e for e, _ in crudos]
    principal = ejemplos[0].nombre
    antes, despues = senal.medir(actual, ejemplos), senal.medir(nueva, ejemplos)
    if not senal.mejora(antes, despues, principal):
        raise ValueError(f"Con los ejemplos de hoy no mejora: {principal} da {despues.de(principal):g} % y hoy da "
                         f"{antes.de(principal):g} %.")
    if peores := senal.empeoran(antes, despues):
        raise ValueError(f"No se aplica: empeoran {', '.join(peores)}.")
    try:
        _guardar_receta(actual, nueva, version, usuario, crudos)
    except almacen.Conflicto:
        raise CambioLaSenal("Alguien cambió las reglas recién: no se pisaron. Volvé a correr el Banco para esa "
                            "señal.")
    return f"El ejemplo {principal} pasó de {antes.de(principal):g} % a {despues.de(principal):g} %."


def _al_terminar(senal_id: str, usuario: str, codigo: int | None) -> None:
    """En el servidor, cuando termina el proceso del armado. Si murió sin anotar el final (memoria), lo anota acá."""
    if codigo != 0 and (estado := leer(senal_id)) and estado["estado"] == "armando":
        _guardar(senal_id, estado="error", fin=_ahora(),
                 mensaje=f"El trabajo del agente se cortó (código {codigo}): se quedó sin memoria o falló. Probá de nuevo.")
    with _candado:
        _en_marcha.discard(senal_id)
        otra_vez = senal_id in _repetir
        _repetir.discard(senal_id)
    if otra_vez:
        lanzar(senal_id, usuario)


def _le_falta(receta, ejemplos: list[senal.EjemploCrudo]) -> bool:
    """Lo de Haiku no alcanza: el ejemplo principal no se lee, no llega a ALCANZA o le faltan filas."""
    medida = senal.medir(receta, ejemplos[:1])
    principal = ejemplos[0].nombre
    return bool(medida.error_lectura) or medida.de(principal) < ALCANZA or medida.cuantas_faltan(principal) > 0


def _avisar_codigo(usuario: str, senal_id: str, antes, despues) -> None:
    """Cada código nuevo le deja un aviso al admin con qué hace y cómo dio, para que lo pueda apagar."""
    nuevos = []
    if despues.entrada.tipo == "codigo" and despues.entrada != antes.entrada:
        nuevos.append(("Lector en código", despues.entrada.lector))
    if despues.final is not None and despues.final != antes.final:
        nuevos.append(("Paso final en código", despues.final))
    for nombre, codigo in nuevos:
        conversaciones.avisar(usuario, senal_id, "codigo", f"{nombre}: {codigo.explicacion} {codigo.resultado}")
