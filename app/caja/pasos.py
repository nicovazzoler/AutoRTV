"""El código de una señal dentro del circuito: el lector que lee el archivo y el paso final sobre el EPG armado.

Contratos para el código: `leer(datos)` recibe el archivo (app.caja.datos.del_archivo) y devuelve las filas de la
grilla; `ajustar(filas)` recibe el EPG como filas con `_fila` y devuelve las filas finales (las agregadas sin `_fila`).
"""
import hashlib
import json
import threading
from collections import OrderedDict

import pandas as pd

from app import caja
from app.caja import autoprueba, datos

LEER = "leer"
AJUSTAR = "ajustar"
# La misma semana se arma muchas veces (vista previa, Revisar, exportar): con los mismos datos no se vuelve a correr.
MAX_GUARDADOS = 16
_guardados: OrderedDict[str, dict] = OrderedDict()
_cerrojo = threading.Lock()


def apagada() -> str | None:
    """Por qué el código de las señales no puede correr en este servidor, o None si puede."""
    return None if autoprueba.disponible() else autoprueba.estado()["motivo"]


def correr(codigo: str, entrada, funcion: str) -> dict:
    clave = hashlib.sha1(json.dumps([codigo, funcion, entrada], ensure_ascii=False, default=str).encode()).hexdigest()
    with _cerrojo:
        if clave in _guardados:
            _guardados.move_to_end(clave)
            return _guardados[clave]
    r = caja.correr(codigo, entrada, funcion=funcion)
    if r["ok"]:  # un error no se guarda: puede haber sido el servidor ocupado (se cortó por tiempo)
        with _cerrojo:
            _guardados[clave] = r
            while len(_guardados) > MAX_GUARDADOS:
                _guardados.popitem(last=False)
    return r


def leer(contenido: bytes, entrada) -> pd.DataFrame:
    """La grilla con el lector en código de la señal."""
    if not entrada.lector.activo:
        raise ValueError("el lector en código de esta señal está apagado")
    if motivo := apagada():
        raise ValueError(f"el lector en código no puede correr: {motivo}")
    r = correr(entrada.lector.codigo, datos.del_archivo(contenido), LEER)
    if not r["ok"]:
        raise ValueError(f"el lector en código falló: {autoprueba._ultima_linea(r['error'])}")
    filas = r["resultado"]
    if not isinstance(filas, list) or not filas or not all(isinstance(f, dict) for f in filas):
        raise ValueError("el lector en código tiene que devolver una lista de filas (diccionarios columna → valor)")
    columnas = list(dict.fromkeys(k for f in filas for k in f))
    return datos.tipar(pd.DataFrame([[f.get(c) for c in columnas] for f in filas], columns=columnas, dtype=object))


def final(salida: pd.DataFrame, codigo) -> tuple[pd.DataFrame, list[int | None] | None, str | None]:
    """(EPG después del paso final, de qué fila viene cada una, error).

    En el origen, None es una fila que agregó el código. Si el paso no corre, el EPG queda igual y el origen es None.
    """
    if codigo is None or not codigo.activo:
        return salida, None, None
    if motivo := apagada():
        return salida, None, f"El paso final en código no corrió: {motivo}"
    r = correr(codigo.codigo, datos.de_tabla(salida), AJUSTAR)
    if not r["ok"]:
        return salida, None, f"El paso final en código falló: {autoprueba._ultima_linea(r['error'])}"
    try:
        tabla, origen = datos.a_tabla(r["resultado"], salida)
    except ValueError as e:
        return salida, None, str(e)
    return tabla, origen, None
